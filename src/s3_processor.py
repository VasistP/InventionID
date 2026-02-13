"""
S3 PDF Processor - Uses Prompt Templates
"""
import boto3
import json
import time
import re
from prompt_templates import PromptTemplates

s3 = boto3.client('s3')
textract = boto3.client('textract')
bedrock = boto3.client('bedrock-runtime', region_name='us-east-1')

BUCKET = "patent-pdf-input-786827631714"

def extract_with_textract(bucket, key):
    """Extract text using Textract"""
    print(f"  Starting Textract on {key}...")
    response = textract.start_document_text_detection(
        DocumentLocation={'S3Object': {'Bucket': bucket, 'Name': key}}
    )
    job_id = response['JobId']
    
    while True:
        result = textract.get_document_text_detection(JobId=job_id)
        status = result['JobStatus']
        print(f"    Status: {status}")
        if status in ['SUCCEEDED', 'FAILED']:
            break
        time.sleep(5)
    
    if status == 'FAILED':
        return None
    
    text = "\n".join([b['Text'] for b in result.get('Blocks', []) if b['BlockType'] == 'LINE'])
    return text

def call_bedrock(prompt, max_tokens=4000):
    """Call Bedrock Claude"""
    response = bedrock.invoke_model(
        modelId='anthropic.claude-3-haiku-20240307-v1:0',
        contentType='application/json',
        accept='application/json',
        body=json.dumps({
            "anthropic_version": "bedrock-2023-05-31",
            "max_tokens": max_tokens,
            "temperature": 0.2,
            "messages": [{"role": "user", "content": prompt}]
        })
    )
    return json.loads(response['body'].read())['content'][0]['text']

def parse_json(text):
    """Extract JSON from response"""
    try:
        match = re.search(r'```json\s*([\s\S]*?)\s*```', text)
        if match:
            return json.loads(match.group(1))
        match = re.search(r'[\[{].*[\]}]', text, re.DOTALL)
        if match:
            return json.loads(match.group())
    except:
        pass
    return None

def extract_invention(text):
    """Extract invention using PromptTemplates"""
    # USE TEMPLATE INSTEAD OF HARDCODED PROMPT
    prompt = PromptTemplates.get_inventions() + f"\n\nDOCUMENT:\n{text[:15000]}"
    response = call_bedrock(prompt)
    return parse_json(response) or {"raw": response}

def process_new_pdfs():
    """Find and process unprocessed PDFs"""
    response = s3.list_objects_v2(Bucket=BUCKET, Prefix='input/')
    pdfs = [obj['Key'] for obj in response.get('Contents', []) if obj['Key'].endswith('.pdf')]
    
    processed = s3.list_objects_v2(Bucket=BUCKET, Prefix='results/')
    done = [obj['Key'].replace('results/', '').replace('_invention.json', '.pdf') 
            for obj in processed.get('Contents', [])]
    
    for pdf_key in pdfs:
        name = pdf_key.replace('input/', '')
        if name in done:
            print(f"Skipping {name} (already processed)")
            continue
        
        print(f"\n{'='*50}")
        print(f"Processing: {pdf_key}")
        
        text = extract_with_textract(BUCKET, pdf_key)
        if not text:
            print("  Textract failed")
            continue
        
        print(f"  Extracted {len(text)} chars")
        invention = extract_invention(text)
        
        output_key = f"results/{name.replace('.pdf', '_invention.json')}"
        s3.put_object(Bucket=BUCKET, Key=output_key, Body=json.dumps(invention, indent=2))
        print(f"  Saved: {output_key}")
        print(json.dumps(invention, indent=2)[:500])

if __name__ == "__main__":
    print("Upload PDFs to: s3://" + BUCKET + "/input/")
    process_new_pdfs()
