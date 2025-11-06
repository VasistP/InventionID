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
    
    def generate(self, prompt: str, max_tokens: int = 4000, temperature: float = 0.3) -> str:
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
            return self._generate_claude(prompt, max_tokens, temperature)
        elif 'gpt' in self.model.lower():
            return self._generate_openai(prompt, max_tokens, temperature)
        else:
            raise ValueError(f"Unknown model: {self.model}")
    
    def _generate_claude(self, prompt: str, max_tokens: int, temperature: float) -> str:
        """Generate using Claude"""
        if not self.anthropic:
            raise ValueError("ANTHROPIC_API_KEY not set")
        
        message = self.anthropic.messages.create(
            model=self.model,
            max_tokens=max_tokens,
            temperature=temperature,
            messages=[
                {"role": "user", "content": prompt}
            ]
        )
        
        return message.content[0].text
    
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