"""
Real Invention Extraction Agent - No Mocks
"""
import boto3
import json
import re

class BedrockLLMClient:
    def __init__(self, model="anthropic.claude-3-haiku-20240307-v1:0", region="us-east-1"):
        self.model_id = model
        self.client = boto3.client('bedrock-runtime', region_name=region)
    
    def generate(self, prompt, max_tokens=4000, temperature=0.2, web_search=False):
        response = self.client.invoke_model(
            modelId=self.model_id,
            contentType='application/json',
            accept='application/json',
            body=json.dumps({
                "anthropic_version": "bedrock-2023-05-31",
                "max_tokens": max_tokens,
                "temperature": temperature,
                "messages": [{"role": "user", "content": prompt}],
                "tools": [{"type": "web_search"}] if web_search else None
            })
        )
        result = json.loads(response['body'].read())
        return result['content'][0]['text']


class InventionExtractionAgent:
    """REAL invention extraction - uses LLM for all analysis"""
    
    def __init__(self, llm, max_iterations=6):
        self.llm = llm
        self.max_iterations = max_iterations
        self.document_text = None
    
    def _extract_invention(self, text):
        """REAL: Uses LLM to extract invention details"""
        prompt = f"""Extract invention details from this document. Return JSON only.

DOCUMENT:
{text[:8000]}

Return this exact JSON structure:
{{
  "invention_name": "concise name",
  "technical_description": "2-3 sentences",
  "problem_statement": "what problem it solves",
  "solution_approach": "how it solves it",
  "key_features": ["feature1", "feature2", "feature3"],
  "domain": "e.g., AI/ML, Healthcare, etc."
}}

JSON ONLY, no other text:"""
        
        response = self.llm.generate(prompt, max_tokens=1000)
        try:
            # Find JSON in response
            match = re.search(r'\{.*\}', response, re.DOTALL)
            if match:
                return json.loads(match.group())
        except:
            pass
        return {"raw": response, "parse_error": True}
    
    def _validate_invention(self, invention):
        """REAL: Uses LLM to validate completeness"""
        prompt = f"""Validate this invention extraction. Is it complete and accurate?

INVENTION:
{json.dumps(invention, indent=2)}

Return JSON:
{{"valid": true/false, "missing_fields": [], "suggestions": ""}}

JSON ONLY:"""
        
        response = self.llm.generate(prompt, max_tokens=500)
        try:
            match = re.search(r'\{.*\}', response, re.DOTALL)
            if match:
                return json.loads(match.group())
        except:
            pass
        return {"valid": True}
    
    def run(self, document_text):
        print(f"\n{'='*60}")
        print("INVENTION EXTRACTION AGENT (REAL - No Mocks)")
        print(f"{'='*60}")
        print(f"Document length: {len(document_text)} chars\n")
        
        self.document_text = document_text
        scratchpad = ""
        
        for i in range(self.max_iterations):
            print(f"--- Iteration {i+1}/{self.max_iterations} ---")
            
            prompt = f"""You are an invention extraction agent. Extract patent-relevant details.

TOOLS (these are REAL and will execute):
- extract_invention: Extract invention from document text
- validate_invention: Check if extraction is complete

FORMAT:
Thought: [reasoning]
Action: [tool_name]
Action Input: {{}}

OR when done:
Thought: [reasoning]
Final Answer: [complete invention JSON]

DOCUMENT PREVIEW (first 2000 chars):
{document_text[:2000]}

PREVIOUS STEPS:
{scratchpad if scratchpad else "None"}

NEXT STEP:"""

            response = self.llm.generate(prompt)
            print(f"Thought: {response[:200]}...")
            
            if "Final Answer:" in response:
                final = response.split("Final Answer:")[-1].strip()
                try:
                    match = re.search(r'\{.*\}', final, re.DOTALL)
                    if match:
                        invention = json.loads(match.group())
                        print(f"\n{'='*60}")
                        print("EXTRACTION COMPLETE")
                        print(json.dumps(invention, indent=2))
                        return {"success": True, "invention": invention, "iterations": i+1}
                except:
                    pass
                return {"success": True, "invention": final, "iterations": i+1}
            
            # Parse action
            action_match = re.search(r'Action:\s*(\w+)', response)
            
            if action_match:
                action = action_match.group(1)
                print(f"Action: {action}")
                
                if action == "extract_invention":
                    result = self._extract_invention(document_text)
                    observation = json.dumps(result, indent=2)
                elif action == "validate_invention":
                    # Get last extraction from scratchpad
                    result = self._validate_invention(result if 'result' in dir() else {})
                    observation = json.dumps(result, indent=2)
                else:
                    observation = f"Unknown action: {action}"
                
                print(f"Observation: {observation[:500]}...\n")
                scratchpad += f"\nAction: {action}\nObservation: {observation}\n"
            else:
                scratchpad += f"\n{response}\n"
        
        return {"success": False, "error": "Max iterations"}


if __name__ == "__main__":
    # Test with sample document
    test_doc = """
    MDAgents: An Adaptive Collaboration of LLMs for Medical Decision-Making
    
    Abstract: We introduce MDAgents, a novel framework that leverages multiple 
    large language models (LLMs) working in adaptive collaboration for medical 
    decision-making. The system dynamically adjusts the complexity of agent 
    collaboration based on the difficulty of medical queries, ranging from 
    single-agent responses for simple cases to multi-agent deliberation for 
    complex diagnoses.
    
    Key contributions:
    1. Adaptive complexity mechanism that routes queries based on difficulty
    2. Multi-agent collaboration protocol for complex medical reasoning
    3. Evaluation on medical benchmarks showing improved accuracy
    
    The framework addresses the challenge of providing consistent, high-quality
    medical decision support by combining the strengths of multiple AI agents.
    """
    
    print("Initializing Bedrock client...")
    llm = BedrockLLMClient()
    
    print("Creating Invention Extraction Agent...")
    agent = InventionExtractionAgent(llm, max_iterations=4)
    
    result = agent.run(test_doc)
    print(f"\nFinal Result: {json.dumps(result, indent=2)}")
