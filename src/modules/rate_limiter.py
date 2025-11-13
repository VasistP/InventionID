"""
Rate Limiter Module

Enforces API rate limits to prevent hitting service quotas.
Tracks request timing and enforces minimum intervals between calls.

This module is independent and used by:
- batch_processor.py
- patent_analyzer.py
- Any module making API calls
"""
import time
from typing import Optional
from collections import deque
from datetime import datetime, timedelta


class RateLimiter:
    """
    Rate limiter for API calls

    Tracks request history and enforces rate limits by delaying
    requests when necessary.

    Example:
        >>> limiter = RateLimiter(requests_per_minute=10)
        >>> limiter.acquire()  # Will wait if needed
        >>> # Make your API call here
    """

    def __init__(
        self,
        requests_per_minute: int = 10,
        min_request_interval: float = 6.0,
        verbose: bool = True
    ):
        """
        Initialize rate limiter

        Args:
            requests_per_minute: Maximum requests allowed per minute
            min_request_interval: Minimum seconds between consecutive requests
            verbose: Whether to print rate limiting messages
        """
        self.requests_per_minute = requests_per_minute
        self.min_request_interval = min_request_interval
        self.verbose = verbose

        # Track request timestamps (use deque for efficient operations)
        self.request_history = deque(maxlen=requests_per_minute)

        # Track last request time for minimum interval enforcement
        self.last_request_time: Optional[float] = None

    def acquire(self) -> float:
        """
        Acquire permission to make a request

        Blocks (sleeps) if necessary to enforce rate limits.
        Call this before making each API request.

        Returns:
            float: Time waited in seconds (0 if no wait needed)
        """
        wait_time = self._calculate_wait_time()

        if wait_time > 0:
            if self.verbose:
                print(f"⏳ Rate limit: waiting {wait_time:.2f}s...")
            time.sleep(wait_time)

        # Record this request
        self._record_request()

        return wait_time

    def _calculate_wait_time(self) -> float:
        """
        Calculate how long to wait before next request

        Returns:
            float: Seconds to wait (0 if can proceed immediately)
        """
        current_time = time.time()
        wait_times = []

        # Check 1: Minimum interval since last request
        if self.last_request_time is not None:
            time_since_last = current_time - self.last_request_time
            if time_since_last < self.min_request_interval:
                interval_wait = self.min_request_interval - time_since_last
                wait_times.append(interval_wait)

        # Check 2: Requests per minute limit
        if len(self.request_history) >= self.requests_per_minute:
            # Window is full, need to wait for oldest request to expire
            oldest_request = self.request_history[0]
            window_duration = 60.0  # 1 minute in seconds
            time_since_oldest = current_time - oldest_request

            if time_since_oldest < window_duration:
                rpm_wait = window_duration - time_since_oldest
                wait_times.append(rpm_wait)

        # Return the maximum wait time needed
        return max(wait_times) if wait_times else 0.0

    def _record_request(self):
        """Record that a request was made"""
        current_time = time.time()
        self.request_history.append(current_time)
        self.last_request_time = current_time

    def reset(self):
        """Reset the rate limiter (clear history)"""
        self.request_history.clear()
        self.last_request_time = None
        if self.verbose:
            print("🔄 Rate limiter reset")

    def get_stats(self) -> dict:
        """
        Get current rate limiter statistics

        Returns:
            dict: Statistics about current state
        """
        current_time = time.time()

        # Calculate requests in last minute
        minute_ago = current_time - 60.0
        recent_requests = sum(
            1 for t in self.request_history if t > minute_ago)

        # Time since last request
        time_since_last = None
        if self.last_request_time:
            time_since_last = current_time - self.last_request_time

        # Time until next allowed request
        wait_time = self._calculate_wait_time()

        return {
            'requests_per_minute_limit': self.requests_per_minute,
            'min_request_interval': self.min_request_interval,
            'requests_in_last_minute': recent_requests,
            'total_requests_tracked': len(self.request_history),
            'time_since_last_request': time_since_last,
            'wait_time_for_next_request': wait_time,
            'can_proceed_immediately': wait_time == 0
        }

    def __repr__(self) -> str:
        """String representation"""
        return (
            f"RateLimiter(rpm={self.requests_per_minute}, "
            f"interval={self.min_request_interval}s, "
            f"requests_tracked={len(self.request_history)})"
        )


# Testing and demonstration
if __name__ == "__main__":
    print("=" * 80)
    print("TESTING RATE LIMITER")
    print("=" * 80)

    # Test 1: Basic rate limiting with minimum interval
    print("\n[TEST 1] Minimum Interval Enforcement (6s between requests)")
    print("-" * 80)
    limiter = RateLimiter(requests_per_minute=10,
                          min_request_interval=6.0, verbose=True)

    print("Making 3 rapid requests...")
    for i in range(3):
        print(f"\nRequest {i+1}:")
        wait_time = limiter.acquire()
        print(f"  Proceeded after {wait_time:.2f}s wait")
        print(f"  {limiter}")

    # Test 2: Requests per minute limit
    print("\n[TEST 2] Requests Per Minute Limit (10 RPM)")
    print("-" * 80)
    fast_limiter = RateLimiter(
        requests_per_minute=5, min_request_interval=0.1, verbose=True)

    print("Making 7 requests quickly (limit is 5 per minute)...")
    start_time = time.time()
    for i in range(7):
        print(f"\nRequest {i+1}:")
        wait_time = fast_limiter.acquire()
        elapsed = time.time() - start_time
        print(f"  Total elapsed: {elapsed:.2f}s")

    total_time = time.time() - start_time
    print(f"\nTotal time for 7 requests: {total_time:.2f}s")

    # Test 3: Statistics
    print("\n[TEST 3] Rate Limiter Statistics")
    print("-" * 80)
    stats = limiter.get_stats()
    print("Current stats:")
    for key, value in stats.items():
        if isinstance(value, float) and value is not None:
            print(f"  {key}: {value:.2f}")
        else:
            print(f"  {key}: {value}")

    # Test 4: Reset
    print("\n[TEST 4] Reset Functionality")
    print("-" * 80)
    print(f"Before reset: {limiter}")
    limiter.reset()
    print(f"After reset: {limiter}")

    print("\n" + "=" * 80)
    print("TESTING COMPLETE")
    print("=" * 80)
