"""
Simple LLM client supporting Claude and OpenAI
"""
import os
from typing import Optional
from anthropic import Anthropic
from openai import OpenAI
from google import genai
from google.genai import types
from modules.rate_limiter import RateLimiter


class LLMClient:
    """Unified LLM client"""

    def __init__(self, rate_limiter, model: str = None, tools: Optional[list] = None, ):
        """
        Initialize LLM client

        Args:
            model: Model name (claude-sonnet-4, gpt-4-turbo, etc.)
            tools: Optional list of tools to be used by the client
        """

        self.tools = tools
        self.rate_limiter = rate_limiter

        # Initialize clients
        anthropic_key = os.getenv('ANTHROPIC_API_KEY')
        openai_key = os.getenv('OPENAI_API_KEY')
        gemini_key = os.getenv('GEMINI_API_KEY')

        if anthropic_key:
            self.model = model or os.getenv(
                'DEFAULT_MODEL', 'claude-sonnet-4-5')
            self.anthropic = Anthropic(api_key=anthropic_key)
        else:
            self.anthropic = None

        if openai_key:
            self.model = model or os.getenv('DEFAULT_MODEL', 'gpt-4o-mini')
            self.openai = OpenAI(api_key=openai_key)
        else:
            self.openai = None

        if gemini_key:
            self.model = model or os.getenv(
                'DEFAULT_MODEL', 'gemini-2.5-flash')
            self.gemini = genai.Client(api_key=gemini_key)
        else:
            self.gemini = None

        # Validate at least one API key exists
        if not self.anthropic and not self.openai and not self.gemini:
            raise ValueError(
                "At least one API key (ANTHROPIC_API_KEY or OPENAI_API_KEY or GEMINI_API_KEY) must be set")

    def generate(self, prompt: str, files: Optional[list] = None, max_tokens: int = 4000, temperature: float = 0.3) -> str:
        """
        Generate completion from LLM

        Args:
            prompt: Input prompt
            max_tokens: Maximum tokens to generate
            temperature: Sampling temperature

        Returns:
            Generated text
        """
        if 'claude' in self.model.lower():
            print("Using Claude model ")
            return self._generate_claude(prompt, files, max_tokens, temperature)
        elif 'gpt' in self.model.lower():
            print("Using OpenAI model ")
            return self._generate_openai(prompt, files, max_tokens, temperature)
        elif 'gemini' in self.model.lower():
            print("Using Gemini model ")
            return self._generate_gemini(prompt, files, max_tokens, temperature)
        else:
            raise ValueError(f"Unknown model: {self.model}")

    def _generate_claude(self, prompt: str, files: Optional[list], max_tokens: int, temperature: float) -> str:
        """Generate using Claude"""
        if not self.anthropic:
            raise ValueError("ANTHROPIC_API_KEY not set")

        if self.rate_limiter:
            self.rate_limiter.acquire()

        if self.tools == None:
            self. tools = [{
                "type": "web_search_20250305",
                "name": "web_search",
                "max_uses": 5
            }]

        message = self.anthropic.messages.create(
            model=self.model,
            max_tokens=max_tokens,
            temperature=temperature,
            messages=[
                {"role": "user", "content": prompt}
            ],
            tools=self.tools
        )

        response_text = ""
        for block in message.content:
            if block.type == "text":
                response_text += block.text

        print("Message: ", response_text)
        return response_text

    def _generate_openai(self, prompt: str, files: Optional[list], max_tokens: int, temperature: float) -> str:
        """Generate using OpenAI"""
        if not self.openai:
            raise ValueError("OPENAI_API_KEY not set")

        if self.rate_limiter:
            self.rate_limiter.acquire()

        response = self.openai.chat.completions.create(
            model=self.model,
            max_tokens=max_tokens,
            temperature=temperature,
            messages=[
                {"role": "user", "content": prompt}
            ]
        )

        return response.choices[0].message.content

    def _generate_gemini(self, prompt: str, files: Optional[list], max_tokens: int, temperature: float) -> str:
        """Generate using Gemini"""
        if not self.gemini:
            raise ValueError("GEMINI_API_KEY not set")

        if self.rate_limiter:
            self.rate_limiter.acquire()

        if files:
            uploaded_files = []
            for file in files:
                uploaded = self.gemini.files.upload(file=file)  # <-- FIX
                uploaded_files.append(uploaded)

            # Combine prompt + file(s)
            content = [prompt] + uploaded_files
        else:
            content = prompt

        if self.tools == None:
            grounding_tool = types.Tool(
                google_search=types.GoogleSearch()
            )
            self.tools = [grounding_tool]

        config = types.GenerateContentConfig(
            tools=self.tools,
            temperature=temperature,
            max_output_tokens=max_tokens
        )

        response = self.gemini.models.generate_content(
            model=self.model,
            contents=content,
            config=config,
        )

        return response.text


if __name__ == "__main__":
    from dotenv import load_dotenv
    load_dotenv()

    client = LLMClient()
    response = client.generate("What is a patent?")
    print(response)
