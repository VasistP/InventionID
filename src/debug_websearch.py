"""
Minimal debug script to test Bedrock web search functionality
"""
import boto3
import json

bedrock = boto3.client('bedrock-runtime', region_name='us-east-1')

def test_web_search():
    """Test web search with minimal configuration"""
    
    prompt = """Search Google Patents for: "multi-robot cooperative transport"

Find 3 relevant patents and return them as JSON:
```json
[{"patent_number": "US...", "title": "..."}]
```"""

    request_body = {
        "anthropic_version": "bedrock-2023-05-31",
        "max_tokens": 2000,
        "temperature": 0.2,
        "messages": [{"role": "user", "content": prompt}],
        "tools": [{
            "type": "web_search_20250305",
            "name": "web_search",
            "max_uses": 5
            # No domain restrictions
        }]
    }
    
    print("="*60)
    print("REQUEST")
    print("="*60)
    print(json.dumps(request_body, indent=2))
    
    print("\n" + "="*60)
    print("CALLING BEDROCK...")
    print("="*60)
    
    response = bedrock.invoke_model(
        modelId='us.anthropic.claude-sonnet-4-5-20250929-v1:0',
        contentType='application/json',
        accept='application/json',
        body=json.dumps(request_body)
    )
    
    result = json.loads(response['body'].read())
    
    print("\n" + "="*60)
    print("FULL RAW RESPONSE")
    print("="*60)
    print(json.dumps(result, indent=2, default=str))
    
    print("\n" + "="*60)
    print("CONTENT BLOCK ANALYSIS")
    print("="*60)
    
    for i, block in enumerate(result.get('content', [])):
        block_type = block.get('type', 'unknown')
        print(f"\nBlock {i}: type={block_type}")
        
        if block_type == 'text':
            print(f"  Text: {block.get('text', '')[:500]}")
        elif block_type == 'tool_use':
            print(f"  Tool: {block.get('name')}")
            print(f"  Input: {json.dumps(block.get('input', {}), indent=4)}")
        elif block_type == 'server_tool_use':
            print(f"  Server Tool: {block.get('name')}")
            print(f"  Input: {json.dumps(block.get('input', {}), indent=4)}")
        elif block_type == 'web_search_tool_result':
            print(f"  Web Search Results:")
            results = block.get('content', [])
            print(f"  Number of results: {len(results)}")
            for r in results[:3]:  # Show first 3
                print(f"    - {r.get('title', 'N/A')[:60]}")
                print(f"      URL: {r.get('url', 'N/A')}")
        else:
            print(f"  Raw: {json.dumps(block, indent=4, default=str)[:500]}")
    
    print("\n" + "="*60)
    print("STOP REASON")
    print("="*60)
    print(f"Stop reason: {result.get('stop_reason')}")
    
    # Check usage
    usage = result.get('usage', {})
    print(f"\nUsage:")
    print(f"  Input tokens: {usage.get('input_tokens')}")
    print(f"  Output tokens: {usage.get('output_tokens')}")

if __name__ == "__main__":
    test_web_search()
