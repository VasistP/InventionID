import boto3
import json
import time

class BedrockLLMClient:
    def __init__(self, model="anthropic.claude-3-haiku-20240307-v1:0", region="us-east-1"):
        self.model_id = model
        self.client = boto3.client('bedrock-runtime', region_name=region)
        self.rate_limiter = None

    def generate(self, prompt, files=None, max_tokens=4000, temperature=0.2, web_search=False):
        if self.rate_limiter:
            self.rate_limiter.acquire()
        
        response = self.client.invoke_model(
            modelId=self.model_id,
            contentType='application/json',
            accept='application/json',
            body=json.dumps({
                "anthropic_version": "bedrock-2023-05-31",
                "max_tokens": max_tokens,
                "temperature": temperature,
                "messages": [{"role": "user", "content": prompt}]
                ,"tools": [{"type": "web_search"}] if web_search else None
            })
        )
        result = json.loads(response['body'].read())
        return result['content'][0]['text']

# Quick test
if __name__ == "__main__":
    client = BedrockLLMClient()
    print(client.generate("Say hello in 5 words"))
