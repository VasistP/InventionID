"""
Simple LLM client supporting Claude and OpenAI
"""
import os
from typing import Optional
from anthropic import Anthropic
from openai import OpenAI


class LLMClient:
    """Unified LLM client"""
    
    def __init__(self, model: str = None):
        """
        Initialize LLM client
        
        Args:
            model: Model name (claude-sonnet-4, gpt-4-turbo, etc.)
        """
        self.model = model or os.getenv('DEFAULT_MODEL', 'claude-sonnet-4')
        
        # Initialize clients
        anthropic_key = os.getenv('ANTHROPIC_API_KEY')
        openai_key = os.getenv('OPENAI_API_KEY')
        
        if anthropic_key:
            self.anthropic = Anthropic(api_key=anthropic_key)
        else:
            self.anthropic = None
            
        if openai_key:
            self.openai = OpenAI(api_key=openai_key)
        else:
            self.openai = None
        
        # Validate at least one API key exists
        if not self.anthropic and not self.openai:
            raise ValueError("At least one API key (ANTHROPIC_API_KEY or OPENAI_API_KEY) must be set")
    
    def generate(self, prompt: str, max_tokens: int = 4000, temperature: float = 0.3,
                 use_web_search: bool = False, max_web_searches: int = 5) -> str:
        """
        Generate completion from LLM

        Args:
            prompt: Input prompt
            max_tokens: Maximum tokens to generate
            temperature: Sampling temperature
            use_web_search: Enable web search (Claude only)
            max_web_searches: Maximum number of web searches to perform

        Returns:
            Generated text
        """
        if 'claude' in self.model.lower():
            return self._generate_claude(prompt, max_tokens, temperature, use_web_search, max_web_searches)
        elif 'gpt' in self.model.lower():
            if use_web_search:
                print("   ⚠ Web search not available for OpenAI models, proceeding without it")
            return self._generate_openai(prompt, max_tokens, temperature)
        else:
            raise ValueError(f"Unknown model: {self.model}")
    
    def _generate_claude(self, prompt: str, max_tokens: int, temperature: float,
                         use_web_search: bool = False, max_web_searches: int = 5) -> str:
        """Generate using Claude with optional web search"""
        if not self.anthropic:
            raise ValueError("ANTHROPIC_API_KEY not set")

        # Build request parameters
        request_params = {
            "model": self.model,
            "max_tokens": max_tokens,
            "temperature": temperature,
            "messages": [
                {"role": "user", "content": prompt}
            ]
        }

        # Add web search tool if requested
        if use_web_search:
            request_params["tools"] = [{
                "type": "web_search_20250305",
                "name": "web_search",
                "max_uses": max_web_searches
            }]

        message = self.anthropic.messages.create(**request_params)

        # Extract text from response
        # Claude may return multiple content blocks if it used tools
        text_parts = []
        for content in message.content:
            if hasattr(content, 'text'):
                text_parts.append(content.text)

        return '\n'.join(text_parts) if text_parts else ""
    
    def _generate_openai(self, prompt: str, max_tokens: int, temperature: float) -> str:
        """Generate using OpenAI"""
        if not self.openai:
            raise ValueError("OPENAI_API_KEY not set")
        
        response = self.openai.chat.completions.create(
            model=self.model,
            max_tokens=max_tokens,
            temperature=temperature,
            messages=[
                {"role": "user", "content": prompt}
            ]
        )
        
        return response.choices[0].message.content


# Test function
if __name__ == "__main__":
    from dotenv import load_dotenv
    load_dotenv()
    
    client = LLMClient()
    response = client.generate("What is a patent?")
    print(response)