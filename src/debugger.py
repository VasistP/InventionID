from llm_client import LLMClient

client = LLMClient()
resp = client.generate("Say 'hello world' as JSON",
                       files=None, max_tokens=100, temperature=0.0)

print("Type:", type(resp))
print("Value:", repr(resp))
