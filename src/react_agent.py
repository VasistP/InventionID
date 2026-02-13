"""
Minimal ReAct Agent with AWS Bedrock
"""
import boto3
import json
import re

class BedrockLLMClient:
    def __init__(self, model="anthropic.claude-3-haiku-20240307-v1:0", region="us-east-1"):
        self.model_id = model
        self.client = boto3.client('bedrock-runtime', region_name=region)
    
    def generate(self, prompt, max_tokens=4000, temperature=0.2):
        response = self.client.invoke_model(
            modelId=self.model_id,
            contentType='application/json',
            accept='application/json',
            body=json.dumps({
                "anthropic_version": "bedrock-2023-05-31",
                "max_tokens": max_tokens,
                "temperature": temperature,
                "messages": [{"role": "user", "content": prompt}]
            })
        )
        result = json.loads(response['body'].read())
        return result['content'][0]['text']


class SimpleReActAgent:
    def __init__(self, llm, max_iterations=5):
        self.llm = llm
        self.max_iterations = max_iterations
        self.tools = {
            "search_patents": self._search_patents,
            "analyze_patent": self._analyze_patent,
            "get_invention_summary": self._get_invention_summary
        }
    
    # Mock tools
    def _search_patents(self, query):
        return {
            "patents": [
                {"id": "US11875894B2", "title": "Medical AI diagnosis system"},
                {"id": "US11694808B1", "title": "Adaptive neural network for healthcare"}
            ],
            "total": 2
        }
    
    def _analyze_patent(self, patent_id):
        return {
            "patent_id": patent_id,
            "relevance": "high",
            "overlap": "Claims 1-3 overlap with multi-agent approach"
        }
    
    def _get_invention_summary(self, text):
        return {
            "name": "Multi-Agent Medical AI",
            "domain": "Healthcare AI",
            "key_features": ["adaptive collaboration", "LLM agents", "medical decision support"]
        }
    
    def run(self, goal):
        print(f"\n{'='*60}")
        print(f"GOAL: {goal}")
        print(f"{'='*60}\n")
        
        scratchpad = ""
        
        for i in range(self.max_iterations):
            print(f"--- Iteration {i+1}/{self.max_iterations} ---")
            
            prompt = f"""You are a ReAct agent. Reason step by step, then take actions.

AVAILABLE TOOLS:
- search_patents(query): Search for relevant patents
- analyze_patent(patent_id): Analyze a specific patent
- get_invention_summary(text): Extract invention details

FORMAT YOUR RESPONSE EXACTLY AS:
Thought: [your reasoning]
Action: [tool_name]
Action Input: {{"param": "value"}}

OR if done:
Thought: [final reasoning]
Final Answer: [your conclusion]

GOAL: {goal}

PREVIOUS STEPS:
{scratchpad if scratchpad else "None yet"}

YOUR TURN:"""

            response = self.llm.generate(prompt)
            print(f"LLM Response:\n{response}\n")
            
            # Parse response
            if "Final Answer:" in response:
                final = response.split("Final Answer:")[-1].strip()
                print(f"\n{'='*60}")
                print(f"FINAL ANSWER: {final}")
                print(f"{'='*60}")
                return {"success": True, "answer": final, "iterations": i+1}
            
            # Extract action
            action_match = re.search(r'Action:\s*(\w+)', response)
            input_match = re.search(r'Action Input:\s*(\{.*?\})', response, re.DOTALL)
            
            if action_match:
                action = action_match.group(1)
                try:
                    action_input = json.loads(input_match.group(1)) if input_match else {}
                except:
                    action_input = {}
                
                print(f"Executing: {action}({action_input})")
                
                if action in self.tools:
                    result = self.tools[action](**action_input) if action_input else self.tools[action]("")
                    observation = json.dumps(result, indent=2)
                else:
                    observation = f"Error: Unknown tool '{action}'"
                
                print(f"Observation: {observation}\n")
                scratchpad += f"\nThought: {response.split('Thought:')[-1].split('Action:')[0].strip()}\nAction: {action}\nObservation: {observation}\n"
            else:
                scratchpad += f"\n{response}\n"
        
        return {"success": False, "error": "Max iterations reached"}


if __name__ == "__main__":
    print("Initializing Bedrock client...")
    llm = BedrockLLMClient()
    
    print("Creating ReAct agent...")
    agent = SimpleReActAgent(llm, max_iterations=5)
    
    result = agent.run("Find patents related to multi-agent AI systems for medical diagnosis")
    
    print(f"\nResult: {json.dumps(result, indent=2)}")
