"""
Full Patent Search Pipeline with Integrated Invention Agent
"""
import boto3
import json
import re
import time
import os
from datetime import datetime
from prompt_templates import PromptTemplates, get_invention_description
from tools.chunk_retriever import get_chunks, retrieve_top_chunks
from tools.schema_validator import validate_schema
from tools.evidence_extractor import extract_evidence
from parallel_search import parallel_search_queries

# Initialize clients
textract = boto3.client('textract')
bedrock = boto3.client('bedrock-runtime', region_name='us-east-2')
s3 = boto3.client('s3')

BUCKET = "patent-pdf-input-786827631714"

# Model IDs
MODEL_SONNET = "us.anthropic.claude-sonnet-4-5-20250929-v1:0"  # For agent
MODEL_OPUS = "us.anthropic.claude-opus-4-20250514-v1:0"        # For analysis


# ============================================================
# INVENTION EXTRACTION AGENT (Integrated)
# ============================================================

class InventionExtractionAgent:
    """ReAct-based invention extraction with iterative refinement and quality threshold"""
    
    CONFIDENCE_THRESHOLD = 0.85
    
    def __init__(self, bedrock_client, model_id, max_iterations=6, log_dir="logs"):
        self.bedrock = bedrock_client
        self.model_id = model_id
        self.max_iterations = max_iterations
        self.log_dir = log_dir
        self.logs = []
    
    def _call_llm(self, prompt, max_tokens=4000):
        """Call Bedrock LLM"""
        request_body = {
            "anthropic_version": "bedrock-2023-05-31",
            "max_tokens": max_tokens,
            "temperature": 0.2,
            "messages": [{"role": "user", "content": prompt}],
        }
        
        response = self.bedrock.invoke_model(
            modelId=self.model_id,
            contentType='application/json',
            accept='application/json',
            body=json.dumps(request_body)
        )
        
        result = json.loads(response['body'].read())
        return result['content'][0]['text']
    
    def _log(self, entry_type, content):
        """Add log entry"""
        self.logs.append({
            "timestamp": datetime.now().isoformat(),
            "type": entry_type,
            "content": content
        })
    
    def _parse_json_response(self, response):
        """Parse JSON from response, stripping markdown fences first"""
        text = response.strip()
        
        # Strip markdown code fences if present
        if text.startswith("```"):
            text = re.sub(r'^```(?:json)?\s*\n?', '', text)
            text = re.sub(r'\n?```\s*$', '', text)
        
        # Try direct parse first
        try:
            return json.loads(text.strip())
        except json.JSONDecodeError:
            pass
        
        # Fallback: regex extraction
        try:
            match = re.search(r'\{.*\}', text, re.DOTALL)
            if match:
                return json.loads(match.group())
        except json.JSONDecodeError:
            pass
        
        return None
    
    def _extract_invention(self, text, chunks):
        """Uses LLM to extract invention details"""
        top = retrieve_top_chunks(
            query="Describe the invention, the problem it solves, how it works, and key technical features.",
            chunks=chunks,
            k=6
        )

        context = "\n\n".join([f"[CHUNK {c['id']}] {c['text']}" for c in top])
        prompt = f"""Extract invention details from this document.

CONTEXT CHUNKS:
{context}

Return this exact JSON structure (use these exact field names):
{{
  "invention_name": "concise name (max 10 words)",
  "technical_description": "2-4 sentences",
  "problem_statement": "what problem it solves (2-3 sentences)",
  "solution_approach": "how it solves it (2-3 sentences)",
  "key_technical_features": ["feature1", "feature2", "feature3", "feature4", "feature5"],
  "domain_classification": "e.g., AI/ML, Robotics, Healthcare, etc.",
  "statutory_category": "Process, Machine, Manufacture, or Composition of Matter",
  "inventor_keywords": ["keyword1", "keyword2", "keyword3"],
  "citations": {{
    "invention_name": ["c0"],
    "technical_description": ["c0"],
    "problem_statement": ["c0"],
    "solution_approach": ["c0"],
    "key_technical_features": ["c0"],
    "domain_classification": ["c0"],
    "statutory_category": ["c0"],
    "inventor_keywords": ["c0"]
  }}
}}

IMPORTANT:
- Return JSON only, no other text.
- Do NOT wrap in ```json fences or any markdown.
- All fields must be non-empty.
- The "citations" object is REQUIRED.
- The "citations" object is REQUIRED and must not be empty.
- For EACH field in "citations", include 1-3 chunk IDs that SUPPORT that field.
- Use ONLY chunk IDs that appear in the CONTEXT CHUNKS above (e.g., c12, c4, etc).
- Do NOT put the same chunk for everything unless it truly contains everything.
- Use ONLY chunk IDs that appear in CONTEXT CHUNKS above. Do not invent IDs."""
        
        response = self._call_llm(prompt, max_tokens=1500)
        self._log("extract_invention", {"prompt_preview": prompt[:500], "response": response})
        
        parsed = self._parse_json_response(response)
        if parsed:
            ok, errors = validate_schema(parsed)
            self._log("schema_validation_extract", {"ok": ok, "errors": errors})

            if not ok:
                parsed["_schema_errors"] = errors   # attach errors (optional)
                parsed["_schema_ok"] = False
            else:
                parsed["_schema_ok"] = True

            return parsed
        
        self._log("extraction_parse_error", {"raw": response[:500]})
        return {"raw": response, "parse_error": True}
    
    def _validate_invention(self, invention):
        """Uses LLM to validate completeness with confidence score"""
        required_fields = [
            "invention_name", "technical_description", "problem_statement",
            "solution_approach", "key_technical_features", "domain_classification", 
        ]
        
        prompt = f"""Validate this invention extraction for completeness and accuracy.

INVENTION:
{json.dumps(invention, indent=2)}

REQUIRED FIELDS: {required_fields}

Evaluate:
1. Are all required fields present and non-empty?
2. Is the technical description specific and detailed enough?
3. Are key_technical_features actually technical (not vague)?
4. Is the problem_statement clear?
5. Does solution_approach explain HOW the invention works?

Return JSON with these exact keys:
{{
  "valid": true or false,
  "missing_fields": ["field1", "field2"] or [],
  "suggestions": "specific improvement suggestions as a single string",
  "confidence": 0.0 to 1.0
}}

RULES:
- confidence must be a number from 0.0 to 1.0.
- valid can be true even if suggestions exist, but confidence should reflect quality.
- If the output is missing important details or is vague, confidence should be low.
- If extraction is complete and high-quality, confidence should be >= 0.85.
- Return JSON only, no markdown fences, no other text."""
        
        response = self._call_llm(prompt, max_tokens=600)
        self._log("validate_invention", {"invention": invention, "response": response})
        
        parsed = self._parse_json_response(response)
        
        # Fail closed: if parse fails, return low confidence to continue loop
        if not parsed:
            self._log("validation_parse_error", {"raw": response[:500]})
            return {
                "valid": False,
                "missing_fields": ["unknown"],
                "suggestions": "Validator returned non-JSON; please return strict JSON only.",
                "confidence": 0.0
            }
        
        # Ensure all required keys exist with safe defaults
        return {
            "valid": parsed.get("valid", False),
            "missing_fields": parsed.get("missing_fields", []),
            "suggestions": parsed.get("suggestions", ""),
            "confidence": float(parsed.get("confidence", 0.0))
        }
    
    def _normalize_suggestions(self, suggestions):
        """Normalize suggestions to string and check if empty"""
        if suggestions is None:
            return "", True
        if isinstance(suggestions, list):
            suggestions = " ".join(str(s) for s in suggestions)
        suggestions = str(suggestions).strip()
        return suggestions, len(suggestions) == 0
    
    def _refine_invention(self, invention, suggestions, document_text, chunks):
        """Refine extraction based on validation feedback"""
        top = retrieve_top_chunks(
            query=f"Find evidence/details to fix these issues: {suggestions}",
            chunks=chunks,
            k=6
        )
        context = "\n\n".join([f"[CHUNK {c['id']}] {c['text']}" for c in top])
        prompt = f"""Improve this invention extraction based on the feedback.

CURRENT EXTRACTION:
{json.dumps(invention, indent=2)}

FEEDBACK/SUGGESTIONS:
{suggestions}

CONTEXT CHUNKS:
{context}

Return improved JSON with the same structure INCLUDING the "citations" field, and update citations if any text changes.
- Making technical descriptions more specific
- Adding concrete technical features
- Ensuring all fields are complete and detailed

IMPORTANT:
- Return JSON only, no other text.
- Do NOT wrap in ```json fences or any markdown.
- Include the "citations" object in the output.
- All citations must reference only the chunk IDs shown in CONTEXT CHUNKS."""
        
        response = self._call_llm(prompt, max_tokens=1500)
        self._log("refine_invention", {"suggestions": suggestions, "response": response})
        
        parsed = self._parse_json_response(response)
        if parsed and not parsed.get("parse_error"):
            ok, errors = validate_schema(parsed)
            self._log("schema_validation_refine", {"ok": ok, "errors": errors})
            parsed["_schema_ok"] = ok
            if not ok:
                parsed["_schema_errors"] = errors
            return parsed
        
        self._log("refinement_parse_error", {"raw": response[:500]})
        return invention  # Return original if refinement fails
    
    def save_logs(self, filename=None):
        """Save logs to file"""
        os.makedirs(self.log_dir, exist_ok=True)
        if not filename:
            filename = f"react_agent_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
        
        filepath = os.path.join(self.log_dir, filename)
        with open(filepath, 'w') as f:
            json.dump(self.logs, f, indent=2)
        return filepath
    
    def run(self, document_text):
        """Run ReAct agent loop with quality threshold"""
        self.logs = []
        self._log("start", {"document_length": len(document_text)})
        
        chunks = get_chunks(document_text)
        self._log("chunking", {"num_chunks": len(chunks)})
        
        print(f"\n{'='*60}")
        print("INVENTION EXTRACTION AGENT (ReAct)")
        print(f"{'='*60}")
        print(f"Document length: {len(document_text)} chars")
        print(f"Model: {self.model_id}")
        print(f"Confidence threshold: {self.CONFIDENCE_THRESHOLD}\n")
        
        invention = None
        stop_reason = "max_iters_reached"
        final_confidence = 0.0
        
        for i in range(self.max_iterations):
            print(f"--- Iteration {i+1}/{self.max_iterations} ---")
            self._log("iteration_start", {"iteration": i+1})
            
            # EXTRACTION PHASE
            if invention is None:
                print("Action: extract_invention")
                invention = self._extract_invention(document_text, chunks)
                
                # Handle extraction parse error - reset and retry
                if invention.get("parse_error"):
                    print("  Parse error in extraction, retrying...")
                    invention = None  # Reset so next iteration retries extraction
                    continue
                
                print(f"  Extracted: {invention.get('invention_name', 'Unknown')}")
                # If schema is bad, force immediate refinement next iteration
                if invention.get("_schema_ok") is False:
                    self._log("forced_refine_reason", {"reason": "schema_failed_on_extract"})
                    # Set invention so we go to validation/refine path next
                    # and give validator clear suggestions:
                continue  # Go to next iteration to validate
            
            # VALIDATION PHASE
            print("Action: validate_invention")
            validation = self._validate_invention(invention)
            
            confidence = float(validation.get("confidence", 0.0))
            final_confidence = confidence
            suggestions_str, no_suggestions = self._normalize_suggestions(validation.get("suggestions"))
            
            # If schema invalid, override validator output and force refinement
            if invention.get("_schema_ok") is False:
                stop_reason = "schema_failed_needs_refine"
                suggestions_str = (
                    f"Schema errors: {invention.get('_schema_errors', [])}. "
                    f"Fix to match required JSON fields/types."
                )
                no_suggestions = False
                confidence = 0.0
                final_confidence = 0.0
                self._log("forced_refine_schema", {"errors": invention.get("_schema_errors", [])})            
                        # Debug log
            print(f"  Confidence: {confidence:.2f}")
            print(f"  Suggestions empty: {no_suggestions}")
            print(f"  Valid: {validation.get('valid')}")
            if validation.get("missing_fields"):
                print(f"  Missing fields: {validation.get('missing_fields')}")
            
            self._log("validation_result", {
                "iteration": i + 1,
                "confidence": confidence,
                "no_suggestions": no_suggestions,
                "valid": validation.get("valid"),
                "suggestions_preview": suggestions_str[:200] if suggestions_str else ""
            })
            
            # STOP CONDITIONS
            if confidence >= self.CONFIDENCE_THRESHOLD:
                stop_reason = f"confidence>={self.CONFIDENCE_THRESHOLD}"
                print(f"  STOP: {stop_reason}")
                break
            
            if no_suggestions:
                stop_reason = "no_suggestions"
                print(f"  STOP: {stop_reason}")
                break
            
            # REFINEMENT PHASE - continue if confidence < threshold and suggestions exist
            print(f"  Continuing: confidence={confidence:.2f} < {self.CONFIDENCE_THRESHOLD}, has suggestions")
            print(f"Action: refine_invention")
            print(f"  Suggestions: {suggestions_str[:100]}...")
            
            invention = self._refine_invention(invention, suggestions_str, document_text, chunks)
            
            # Check if refinement returned parse error
            if invention.get("parse_error"):
                print("  Refinement parse error, keeping previous version")
            else:
                print(f"  Refined: {invention.get('invention_name', 'Unknown')}")
        
        # Ensure required fields exist with defaults
        final_invention = self._ensure_fields(invention)
        evidence = extract_evidence(final_invention, chunks)
        final_invention["evidence"] = evidence
        self._log("evidence", {"count": len(evidence)})
        
        self._log("complete", {
            "invention": final_invention,
            "iterations": i + 1,
            "stop_reason": stop_reason,
            "final_confidence": final_confidence
        })
        
        print(f"\n{'='*60}")
        print("EXTRACTION COMPLETE")
        print(f"Invention: {final_invention.get('invention_name', 'Unknown')}")
        print("Citations:", final_invention.get("citations", {}))
        print(f"Iterations: {i+1}")
        print(f"Stop reason: {stop_reason}")
        print(f"Final confidence: {final_confidence:.2f}")
        
        return {
            "success": True,
            "invention": final_invention,
            "iterations": i + 1,
            "stop_reason": stop_reason,
            "confidence": final_confidence
        }
    
    def _ensure_fields(self, invention):
        """Ensure all required fields exist"""
        defaults = {
            "invention_name": "Unknown Invention",
            "technical_description": "N/A",
            "problem_statement": "N/A",
            "solution_approach": "N/A",
            "key_technical_features": [],
            "domain_classification": "Unknown",
            "statutory_category": "Process",
            "inventor_keywords": [],
            "citations": {"invention_name": ["c0"]}
        }
        
        if invention is None or invention.get("parse_error"):
            return defaults
        
        for key, default in defaults.items():
            if key not in invention or not invention[key]:
                invention[key] = default
        
        return invention


# ============================================================
# PATENT SEARCHER (SerpAPI)
# ============================================================

class PatentSearcher:
    """Search Google Patents via SerpAPI"""
    
    def __init__(self, api_key: str, delay=0.5):
        self.api_key = api_key
        self.delay = delay
        try:
            from serpapi import GoogleSearch
            self.GoogleSearch = GoogleSearch
        except ImportError:
            print("ERROR: serpapi not installed. Run: pip install google-search-results --break-system-packages")
            self.GoogleSearch = None
    
    def search(self, query: str, max_results: int = 10) -> list:
        if not self.GoogleSearch:
            return []
        
        try:
            params = {
                "engine": "google_patents",
                "q": query,
                "api_key": self.api_key,
                "before": "publication:20220101"
            }
            
            time.sleep(self.delay)
            search = self.GoogleSearch(params)
            results = search.get_dict()
            
            return self._parse_results(results, max_results)
        except Exception as e:
            print(f"    SerpAPI error: {e}")
            return []
    
    def _extract_patent_number(self, patent_id: str) -> str:
        if not patent_id:
            return ""
        parts = patent_id.split("/")
        if len(parts) >= 2:
            return parts[1] if parts[0] == "patent" else parts[0]
        return patent_id
    
    def _parse_results(self, data: dict, max_results: int) -> list:
        patents = []
        
        for result in data.get("organic_results", [])[:max_results]:
            patent_id = result.get("patent_id", "")
            patent_number = self._extract_patent_number(patent_id)
            
            patent = {
                "patent_number": patent_number,
                "title": result.get("title", ""),
                "url": f"https://patents.google.com/{patent_id}" if patent_id else "",
                "abstract": result.get("snippet", ""),
                "filing_date": result.get("filing_date", ""),
                "publication_date": result.get("publication_date", ""),
                "grant_date": result.get("grant_date", ""),
                "inventors": result.get("inventor", ""),
                "assignee": result.get("assignee", ""),
            }
            if patent_number:
                patents.append(patent)
        
        return patents
    
    def get_patent_details(self, patent_number: str) -> dict:
        if not self.GoogleSearch:
            return {"patent_number": patent_number, "error": "serpapi not installed"}
        
        try:
            params = {
                "engine": "google_patents",
                "q": patent_number,
                "api_key": self.api_key
            }
            
            time.sleep(self.delay)
            search = self.GoogleSearch(params)
            data = search.get_dict()
            
            results = data.get("organic_results", [])
            if results:
                r = results[0]
                patent_id = r.get("patent_id", "")
                return {
                    "patent_number": self._extract_patent_number(patent_id) or patent_number,
                    "title": r.get("title", ""),
                    "abstract": r.get("snippet", ""),
                    "url": f"https://patents.google.com/{patent_id}" if patent_id else "",
                    "filing_date": r.get("filing_date", ""),
                    "publication_date": r.get("publication_date", ""),
                    "inventors": r.get("inventor", ""),
                    "assignee": r.get("assignee", ""),
                    "claim_1": ""
                }
            return {"patent_number": patent_number, "error": "Not found"}
        except Exception as e:
            print(f"    SerpAPI error for {patent_number}: {e}")
            return {"patent_number": patent_number, "error": str(e)}


# ============================================================
# RATE LIMITER
# ============================================================

class RateLimiter:
    def __init__(self, min_interval=2.0):
        self.min_interval = min_interval
        self.last_request = 0
    
    def wait(self):
        elapsed = time.time() - self.last_request
        if elapsed < self.min_interval:
            time.sleep(self.min_interval - elapsed)
        self.last_request = time.time()


# ============================================================
# INITIALIZE COMPONENTS
# ============================================================

SERPAPI_KEY = os.environ.get("SERPAPI_KEY", "")
if not SERPAPI_KEY:
    print("WARNING: SERPAPI_KEY not set. Set with: export SERPAPI_KEY='your_key'")

patent_searcher = PatentSearcher(api_key=SERPAPI_KEY, delay=0.5)
rate_limiter = RateLimiter(min_interval=2.0)
invention_agent = InventionExtractionAgent(bedrock, MODEL_SONNET, max_iterations=4)


# ============================================================
# LLM CALL FUNCTIONS
# ============================================================

def call_bedrock(prompt, max_tokens=4000, model_id=MODEL_OPUS):
    """Call Bedrock with rate limiting"""
    rate_limiter.wait()
    
    request_body = {
        "anthropic_version": "bedrock-2023-05-31",
        "max_tokens": max_tokens,
        "temperature": 0.2,
        "messages": [{"role": "user", "content": prompt}],
    }
    
    response = bedrock.invoke_model(
        modelId=model_id,
        contentType='application/json',
        accept='application/json',
        body=json.dumps(request_body)
    )
    
    result = json.loads(response['body'].read())
    return result['content'][0]['text']


def parse_json(text):
    """Extract JSON from LLM response"""
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


def extract_text_from_s3(bucket, key):
    """Extract text from PDF using Textract"""
    print(f"  Starting Textract...")
    response = textract.start_document_text_detection(
        DocumentLocation={'S3Object': {'Bucket': bucket, 'Name': key}}
    )
    job_id = response['JobId']
    
    while True:
        result = textract.get_document_text_detection(JobId=job_id)
        if result['JobStatus'] in ['SUCCEEDED', 'FAILED']:
            break
        time.sleep(3)
    
    if result['JobStatus'] == 'FAILED':
        return None
    
    text = "\n".join([b['Text'] for b in result.get('Blocks', []) if b['BlockType'] == 'LINE'])
    print(f"  Extracted {len(text)} chars")
    return text


# ============================================================
# PIPELINE STAGES
# ============================================================

def stage_1_extract_invention(document_text):
    """Stage 1: Extract invention using ReAct agent"""
    print("\n" + "="*60)
    print("STAGE 1: INVENTION EXTRACTION (ReAct Agent)")
    print("="*60)
    
    result = invention_agent.run(document_text)
    
    # Save agent logs
    log_file = invention_agent.save_logs()
    print(f"  Agent logs saved: {log_file}")
    
    if result["success"]:
        invention = result["invention"]
        return {"1": invention}  # Match expected format
    
    return None


def stage_2_generate_queries(invention):
    """Stage 2: Generate search queries (using Sonnet)"""
    print("\n" + "="*60)
    print("STAGE 2: GENERATE SEARCH QUERIES")
    print("="*60)
    
    prompt = PromptTemplates.generate_search_queries(invention, num_queries=5)
    response = call_bedrock(prompt, max_tokens=500, model_id=MODEL_SONNET)
    queries = parse_json(response)
    
    if queries:
        print(f"  Generated {len(queries)} queries:")
        for q in queries:
            print(f"    - {q}")
    
    return queries or []


# def stage_3_search_patents(queries):
#     """Stage 3: Search patents via SerpAPI"""
#     print("\n" + "="*60)
#     print("STAGE 3: PATENT SEARCH (SerpAPI)")
#     print("="*60)
    
#     all_patents = []
#     seen = set()
    
#     for query in queries[:3]:
#         print(f"  Searching: {query}")
#         results = patent_searcher.search(query, max_results=5)
        
#         for p in results:
#             num = p.get('patent_number', '')
#             if num and num not in seen:
#                 seen.add(num)
#                 all_patents.append(p)
#                 print(f"    Found: {num} - {p.get('title', '')[:50]}")
    
#     print(f"  Total unique patents: {len(all_patents)}")
#     return all_patents

def stage_3_search_patents(queries, max_concurrent: int = 5):
    """Stage 3: Search patents via SerpAPI (parallel)."""
    print("\n" + "="*60)
    print("STAGE 3: PATENT SEARCH (SerpAPI, parallel)")
    print("="*60)

    # Limit how many queries you actually fire (you had [:3] before)
    target_queries = queries[:3]

    all_patents = []
    seen = set()

    # Parallel search: local now, same code later on AWS
    results_by_query = parallel_search_queries(
        patent_searcher,
        target_queries,
        max_results_per_query=5,
        max_concurrent=max_concurrent,
    )

    for query, results in results_by_query:
        print(f"  Merging results for: {query!r}")
        for p in results:
            num = p.get("patent_number", "")
            if num and num not in seen:
                seen.add(num)
                all_patents.append(p)

    print(f"  Total unique patents: {len(all_patents)}")
    return all_patents

def stage_4_fetch_details(patents):
    """Stage 4: Fetch patent details"""
    print("\n" + "="*60)
    print("STAGE 4: FETCH PATENT DETAILS")
    print("="*60)
    
    if not patents:
        return []
    
    detailed_patents = []
    for p in patents[:10]:
        patent_num = p.get('patent_number', '')
        
        if p.get('abstract') and len(p.get('abstract', '')) > 50:
            print(f"  Using cached: {patent_num}")
            detailed_patents.append(p)
        elif patent_num:
            print(f"  Fetching: {patent_num}")
            details = patent_searcher.get_patent_details(patent_num)
            merged = {**p, **details}
            detailed_patents.append(merged)
    
    print(f"  Got details for {len(detailed_patents)} patents")
    return detailed_patents


def stage_5_analyze_patents(invention, patents):
    """Stage 5: Analyze patents (using Opus)"""
    print("\n" + "="*60)
    print("STAGE 5: PATENT ANALYSIS (Opus)")
    print("="*60)
    
    if not patents:
        return []
    
    inv_desc = get_invention_description(invention)
    
    prompt = PromptTemplates.analyze_patents_batch(inv_desc, patents[:5])
    response = call_bedrock(prompt, max_tokens=3000, model_id=MODEL_OPUS)
    analysis = parse_json(response)
    
    if analysis:
        print(f"  Analyzed {len(analysis)} patents:")
        for a in analysis:
            print(f"    {a.get('patent_number')}: {a.get('classification')} ({a.get('relevance_score')})")
    
    return analysis or []


def stage_6_generate_report(invention, patents, analysis):
    """Stage 6: Generate final report"""
    print("\n" + "="*60)
    print("STAGE 6: FINAL REPORT")
    print("="*60)
    
    analysis_map = {a['patent_number']: a for a in analysis}
    
    results = []
    for p in patents:
        num = p.get('patent_number')
        result = {**p}
        if num in analysis_map:
            result['analysis'] = analysis_map[num]
        results.append(result)
    
    report = {
        "invention": invention,
        "patents_found": len(patents),
        "patents_analyzed": len(analysis),
        "blocking": len([a for a in analysis if a.get('classification') == 'blocking']),
        "relevant": len([a for a in analysis if a.get('classification') == 'relevant']),
        "related": len([a for a in analysis if a.get('classification') == 'related']),
        "patents": results
    }
    
    print(f"  Summary:")
    print(f"    Patents found: {report['patents_found']}")
    print(f"    Blocking: {report['blocking']}")
    print(f"    Relevant: {report['relevant']}")
    print(f"    Related: {report['related']}")
    
    return report


# ============================================================
# MAIN PIPELINE
# ============================================================

def run_pipeline(bucket, pdf_key):
    """Run complete pipeline"""
    print("\n" + "#"*60)
    print("PATENT PRIOR ART SEARCH PIPELINE")
    print("#"*60)
    print(f"Input: s3://{bucket}/{pdf_key}")
    print(f"Models: Sonnet (agent), Opus (analysis)")
    
    # Extract text
    text = extract_text_from_s3(bucket, pdf_key)
    if not text:
        return {"error": "Textract failed"}
    
    # Stage 1: Extract invention (ReAct agent)
    inventions = stage_1_extract_invention(text)
    if not inventions:
        return {"error": "No inventions found"}
    
    invention = list(inventions.values())[0]
    
    # Stage 2: Generate queries
    queries = stage_2_generate_queries(invention)
    
    # Stage 3: Search patents
    patents = stage_3_search_patents(queries)
    
    # Stage 4: Fetch details
    detailed = stage_4_fetch_details(patents)
    
    # Stage 5: Analyze
    analysis = stage_5_analyze_patents(invention, detailed)
    
    # Stage 6: Report
    report = stage_6_generate_report(invention, detailed, analysis)
    
    # Save to S3
    output_key = pdf_key.replace('input/', 'results/').replace('.pdf', '_report.json')
    s3.put_object(
        Bucket=bucket,
        Key=output_key,
        Body=json.dumps(report, indent=2),
        ContentType='application/json'
    )
    print(f"\nReport saved: s3://{bucket}/{output_key}")
    
    return report


if __name__ == "__main__":
    import sys
    
    if len(sys.argv) < 2:
        print("Available PDFs in S3:")
        response = s3.list_objects_v2(Bucket=BUCKET, Prefix='input/')
        for obj in response.get('Contents', []):
            print(f"  {obj['Key']}")
        print(f"\nUsage: python3 full_pipeline.py <pdf_key>")
    else:
        pdf_key = sys.argv[1]
        report = run_pipeline(BUCKET, pdf_key)
        print("\n" + "="*60)
        print("PIPELINE COMPLETE")
        print("="*60)
