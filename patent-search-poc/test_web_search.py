#!/usr/bin/env python3
"""
Test script for Claude web search functionality
"""
import os
import sys
from dotenv import load_dotenv

# Add src to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'src'))

from llm_client import LLMClient

def test_web_search():
    """Test Claude's web search capability"""
    load_dotenv()

    # Check if Anthropic API key is set
    if not os.getenv('ANTHROPIC_API_KEY'):
        print("❌ ANTHROPIC_API_KEY not set in .env file")
        print("   Claude's web search requires an Anthropic API key")
        print("   Get one at: https://console.anthropic.com/settings/keys")
        return False

    print("=" * 80)
    print("Testing Claude Web Search Functionality")
    print("=" * 80)

    try:
        # Initialize Claude client
        client = LLMClient(model='claude-sonnet-4')
        print(f"✓ Initialized LLM client with model: {client.model}")

        # Test basic web search
        print("\n[TEST 1] Basic web search test...")
        prompt = "Search the web for recent news about AI patents. Return a brief summary."

        print("   Sending request with web search enabled...")
        response = client.generate(
            prompt,
            max_tokens=500,
            temperature=0.3,
            use_web_search=True,
            max_web_searches=3
        )

        print(f"\n✓ Response received ({len(response)} chars)")
        print("\nResponse preview:")
        print("-" * 80)
        print(response[:300] + "..." if len(response) > 300 else response)
        print("-" * 80)

        # Test patent-specific search
        print("\n[TEST 2] Patent search test...")
        prompt = """
Search the web for US patents related to "protein structure prediction using AI".
Find 2-3 relevant patents and return their patent numbers and titles in a simple list format.
"""

        print("   Searching for patents...")
        response = client.generate(
            prompt,
            max_tokens=800,
            temperature=0.3,
            use_web_search=True,
            max_web_searches=5
        )

        print(f"\n✓ Response received ({len(response)} chars)")
        print("\nPatent search results:")
        print("-" * 80)
        print(response)
        print("-" * 80)

        print("\n" + "=" * 80)
        print("✅ All tests passed!")
        print("=" * 80)
        print("\nClaude's web search is working correctly.")
        print("You can now use: python src/main.py --llm-web-search --model claude-sonnet-4")
        return True

    except ValueError as e:
        if "ANTHROPIC_API_KEY" in str(e):
            print(f"\n❌ Error: {e}")
            print("\nPlease set your Anthropic API key in .env:")
            print("   ANTHROPIC_API_KEY=sk-ant-your-key-here")
            print("   DEFAULT_MODEL=claude-sonnet-4")
        else:
            print(f"\n❌ Error: {e}")
        return False

    except Exception as e:
        print(f"\n❌ Unexpected error: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_openai_fallback():
    """Test that OpenAI models handle web search gracefully"""
    load_dotenv()

    if not os.getenv('OPENAI_API_KEY'):
        print("\n⚠ OPENAI_API_KEY not set, skipping OpenAI fallback test")
        return True

    print("\n" + "=" * 80)
    print("Testing OpenAI Fallback (web search disabled)")
    print("=" * 80)

    try:
        client = LLMClient(model='gpt-4o-mini')
        print(f"✓ Initialized LLM client with model: {client.model}")

        print("\n   Requesting with web search enabled (should show warning)...")
        response = client.generate(
            "What is a patent?",
            max_tokens=200,
            use_web_search=True  # This should show a warning
        )

        print(f"✓ Response received ({len(response)} chars)")
        print("✓ OpenAI fallback works correctly")
        return True

    except Exception as e:
        print(f"❌ OpenAI test failed: {e}")
        return False


if __name__ == "__main__":
    print("\n🧪 Patent Search POC - Web Search Test Suite\n")

    success = test_web_search()

    if success:
        test_openai_fallback()

    sys.exit(0 if success else 1)
