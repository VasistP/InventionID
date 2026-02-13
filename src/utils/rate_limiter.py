"""
Centralized rate limiter, circuit breaker, and retry logic for Bedrock LLM calls.

All LLM calls in the pipeline should flow through invoke_bedrock_with_retry()
to get consistent rate limiting, exponential backoff on throttling errors,
and circuit-breaker protection against sustained outages.
"""

import json
import random
import threading
import time
from enum import Enum


class CircuitBreakerOpenError(Exception):
    """Raised when the circuit breaker is open and rejecting calls."""

    def __init__(self, recovery_seconds_remaining: float):
        self.recovery_seconds_remaining = recovery_seconds_remaining
        super().__init__(
            f"Circuit breaker is OPEN. "
            f"Retry in {recovery_seconds_remaining:.0f}s."
        )


class _CircuitState(Enum):
    CLOSED = "CLOSED"
    OPEN = "OPEN"
    HALF_OPEN = "HALF_OPEN"


class CircuitBreaker:
    """
    Thread-safe circuit breaker for Bedrock API calls.

    State transitions:
        CLOSED  --[failure_threshold consecutive failures]--> OPEN
        OPEN    --[recovery_timeout elapsed]----------------> HALF_OPEN
        HALF_OPEN --[next call succeeds]--------------------> CLOSED
        HALF_OPEN --[next call fails]-----------------------> OPEN
    """

    def __init__(self, failure_threshold: int = 5, recovery_timeout: float = 60.0):
        self.failure_threshold = failure_threshold
        self.recovery_timeout = recovery_timeout
        self._state = _CircuitState.CLOSED
        self._failure_count = 0
        self._last_failure_time = 0.0
        self._lock = threading.Lock()

    @property
    def state(self) -> str:
        with self._lock:
            self._maybe_transition_to_half_open()
            return self._state.value

    def _maybe_transition_to_half_open(self):
        if (
            self._state == _CircuitState.OPEN
            and time.time() - self._last_failure_time >= self.recovery_timeout
        ):
            self._state = _CircuitState.HALF_OPEN

    def check(self):
        """Raise CircuitBreakerOpenError if the breaker is OPEN."""
        with self._lock:
            self._maybe_transition_to_half_open()
            if self._state == _CircuitState.OPEN:
                remaining = self.recovery_timeout - (
                    time.time() - self._last_failure_time
                )
                raise CircuitBreakerOpenError(max(0.0, remaining))

    def record_success(self):
        with self._lock:
            self._failure_count = 0
            self._state = _CircuitState.CLOSED

    def record_failure(self):
        with self._lock:
            self._failure_count += 1
            self._last_failure_time = time.time()
            if self._failure_count >= self.failure_threshold:
                self._state = _CircuitState.OPEN
                print(
                    f"  [CircuitBreaker] OPEN after {self._failure_count} "
                    f"consecutive failures. Will retry in {self.recovery_timeout}s."
                )
            elif self._state == _CircuitState.HALF_OPEN:
                self._state = _CircuitState.OPEN


class BedrockRateLimiter:
    """
    Thread-safe minimum-interval rate limiter.

    Ensures at least `min_interval` seconds elapse between consecutive
    Bedrock API calls, even from different threads.
    """

    def __init__(self, min_interval: float = 2.0):
        self.min_interval = min_interval
        self._last_request = 0.0
        self._lock = threading.Lock()

    def wait(self):
        with self._lock:
            now = time.time()
            earliest = self._last_request + self.min_interval
            delay = max(0.0, earliest - now)
            # Reserve our slot before releasing the lock so the next
            # thread computes its wait relative to our planned time.
            self._last_request = now + delay
        if delay > 0:
            time.sleep(delay)


# Bedrock error codes that indicate transient throttling / capacity issues.
_RETRYABLE_ERROR_CODES = frozenset({
    "ThrottlingException",
    "TooManyRequestsException",
    "ServiceUnavailableException",
    "ModelTimeoutException",
})


def _is_retryable(exc: Exception) -> bool:
    """Check if a botocore ClientError is a retryable throttle/capacity error."""
    error_code = getattr(getattr(exc, "response", None), "get", lambda *_: None)
    if error_code is None:
        # Try the botocore-style access
        resp = getattr(exc, "response", None)
        if isinstance(resp, dict):
            code = resp.get("Error", {}).get("Code", "")
            return code in _RETRYABLE_ERROR_CODES
        return False
    return False


def invoke_bedrock_with_retry(
    bedrock_client,
    *,
    model_id: str,
    body: str,
    rate_limiter: BedrockRateLimiter,
    circuit_breaker: CircuitBreaker,
    max_retries: int = 4,
    base_delay: float = 2.0,
) -> dict:
    """
    Call bedrock_client.invoke_model with rate limiting, circuit breaker,
    and exponential backoff on transient errors.

    Parameters
    ----------
    bedrock_client : boto3 bedrock-runtime client
    model_id : str
    body : str
        JSON-encoded request body.
    rate_limiter : BedrockRateLimiter
    circuit_breaker : CircuitBreaker
    max_retries : int
        Maximum number of retry attempts after the initial call.
    base_delay : float
        Base delay in seconds for exponential backoff.

    Returns
    -------
    dict
        Parsed JSON response body from Bedrock.

    Raises
    ------
    CircuitBreakerOpenError
        If the circuit breaker is open.
    botocore.exceptions.ClientError
        If a non-retryable error occurs, or retries are exhausted.
    """
    last_exception = None

    for attempt in range(1 + max_retries):
        # 1. Circuit breaker gate
        circuit_breaker.check()

        # 2. Rate limit
        rate_limiter.wait()

        try:
            # 3. Make the call
            response = bedrock_client.invoke_model(
                modelId=model_id,
                contentType="application/json",
                accept="application/json",
                body=body,
            )
            result = json.loads(response["body"].read())

            # 4. Success
            circuit_breaker.record_success()
            return result

        except Exception as exc:
            # Check if this is a retryable throttle/capacity error
            resp = getattr(exc, "response", None)
            error_code = ""
            if isinstance(resp, dict):
                error_code = resp.get("Error", {}).get("Code", "")

            if error_code in _RETRYABLE_ERROR_CODES:
                circuit_breaker.record_failure()
                last_exception = exc

                if attempt < max_retries:
                    delay = base_delay * (2 ** attempt) + random.uniform(0, 1)
                    print(
                        f"  [Retry] {error_code} on attempt {attempt + 1}/"
                        f"{1 + max_retries}. Backing off {delay:.1f}s..."
                    )
                    time.sleep(delay)
                    continue
                else:
                    print(
                        f"  [Retry] Exhausted {1 + max_retries} attempts. "
                        f"Last error: {error_code}"
                    )
                    raise
            else:
                # Non-retryable error — propagate immediately
                raise

    # Should not reach here, but just in case
    raise last_exception  # type: ignore[misc]
