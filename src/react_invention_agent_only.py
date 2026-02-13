# src/react_invention_agent_only.py
import json
import re
from datetime import datetime
import os

class ReactInventionAgentOnly:
    """
    True ReAct loop:
      LLM -> Action(tool) -> Observation -> ... -> Final(JSON)
    No validate/refine here; this is the ReAct-style extraction itself.
    """

    def __init__(
        self,
        bedrock_client,
        model_id,
        max_turns=6,
        log_dir="logs",
        confidence_threshold=0.85,
    ):
        self.bedrock = bedrock_client
        self.model_id = model_id
        self.max_turns = max_turns
        self.log_dir = log_dir
        self.confidence_threshold = confidence_threshold
        self.logs = []

    # ----------------------------
    # Bedrock call (Anthropic)
    # ----------------------------
    def _call_llm(self, prompt, max_tokens=1500, temperature=0.2):
        body = {
            "anthropic_version": "bedrock-2023-05-31",
            "max_tokens": max_tokens,
            "temperature": temperature,
            "messages": [{"role": "user", "content": prompt}],
        }
        resp = self.bedrock.invoke_model(
            modelId=self.model_id,
            contentType="application/json",
            accept="application/json",
            body=json.dumps(body),
        )
        out = json.loads(resp["body"].read())
        return out["content"][0]["text"]

    def _log(self, typ, content):
        self.logs.append(
            {"ts": datetime.now().isoformat(), "type": typ, "content": content}
        )

    def save_logs(self, filename=None):
        os.makedirs(self.log_dir, exist_ok=True)
        if not filename:
            filename = f"react_stage1_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
        path = os.path.join(self.log_dir, filename)
        with open(path, "w") as f:
            json.dump(self.logs, f, indent=2)
        return path

    # ----------------------------
    # Tools (Actions)
    # ----------------------------
    @staticmethod
    def _retrieve_passages(document_text, query, k=5, window=450):
        """
        Local tool: returns top-k snippets matching query terms.
        Very robust + cheap. This makes your loop "true ReAct" (tool + observation).
        """
        if not document_text:
            return []

        q = (query or "").lower().strip()
        if not q:
            return []

        # Tokenize query (simple)
        terms = [t for t in re.split(r"\W+", q) if len(t) >= 3]
        if not terms:
            return []

        # Split doc into lines for matching
        lines = document_text.splitlines()
        scored = []

        for i, line in enumerate(lines):
            low = line.lower()
            score = sum(low.count(t) for t in terms)
            if score > 0:
                scored.append((score, i))

        scored.sort(reverse=True)
        top = scored[: max(k * 3, k)]  # gather a bit more then merge windows

        # Build windowed snippets (merge nearby)
        snippets = []
        used = set()
        for score, idx in top:
            if idx in used:
                continue
            # join nearby lines into one snippet
            start = max(0, idx - 2)
            end = min(len(lines), idx + 3)
            snippet = "\n".join(lines[start:end]).strip()
            if not snippet:
                continue
            used.update(range(start, end))
            snippets.append(
                {
                    "line_range": [start, end - 1],
                    "score": score,
                    "text": snippet[:window],
                }
            )
            if len(snippets) >= k:
                break

        return snippets

    # ----------------------------
    # ReAct parsing
    # ----------------------------
    @staticmethod
    def _parse_action_block(text):
        """
        Expected model output (STRICT):
          Action: tool_name
          Action Input: {"key":"value"}
        OR:
          Final: {...json...}

        Returns: ("final", obj) or ("action", (tool, args_dict)) or ("bad", None)
        """
        t = (text or "").strip()

        # Final:
        if t.startswith("Final:"):
            payload = t[len("Final:") :].strip()
            try:
                return ("final", json.loads(payload))
            except Exception:
                # fallback: try to extract JSON object with regex
                m = re.search(r"\{.*\}", payload, re.DOTALL)
                if m:
                    return ("final", json.loads(m.group()))
                return ("bad", None)

        # Action:
        m_tool = re.search(r"^Action:\s*([a-zA-Z0-9_]+)\s*$", t, re.MULTILINE)
        m_in = re.search(r"^Action Input:\s*(\{.*\})\s*$", t, re.MULTILINE | re.DOTALL)

        if not m_tool or not m_in:
            return ("bad", None)

        tool = m_tool.group(1).strip()
        raw = m_in.group(1).strip()
        try:
            args = json.loads(raw)
        except Exception:
            return ("bad", None)

        return ("action", (tool, args))

    # ----------------------------
    # Main run
    # ----------------------------
    def run(self, document_text):
        """
        True ReAct loop:
          - LLM decides it needs snippets -> calls retrieve_passages
          - You feed observation -> LLM produces Final JSON
        """
        self.logs = []
        self._log("start", {"doc_len": len(document_text)})

        tools_spec = """
You are an invention extraction agent.

You MUST follow this output format ONLY:
- To use a tool:
  Action: retrieve_passages
  Action Input: {"query": "...", "k": 5}

- To finish:
  Final: { ...valid JSON... }

Do NOT output any other text. No markdown. No explanations.

Tool available:
1) retrieve_passages(query:str, k:int=5)
   - Returns relevant snippets from the document as a list of objects with line_range, score, text.

Goal:
Extract invention details as strict JSON with fields:
{
  "invention_name": "...",
  "technical_description": "...",
  "problem_statement": "...",
  "solution_approach": "...",
  "key_technical_features": ["...", "...", "...", "...", "..."],
  "domain_classification": "...",
  "statutory_category": "Process|Machine|Manufacture|Composition of Matter",
  "inventor_keywords": ["...", "...", "..."],
  "confidence": 0.0 to 1.0,
  "evidence": [
     {"line_range":[a,b], "text":"..."},
     ...
  ]
}

Rules:
- confidence must be a number 0..1.
- evidence must include at least 2 snippets that support the extracted invention.
- If invention is unclear, set confidence < 0.6 and still fill best-effort fields.
"""

        # Conversation scratchpad we maintain
        convo = f"{tools_spec}\n\nDOCUMENT (raw):\n{document_text[:12000]}\n"

        # We encourage the agent to fetch evidence first
        convo += """
Action: retrieve_passages
Action Input: {"query":"invention contribution method framework system approach pipeline architecture results", "k": 6}
"""

        for turn in range(1, self.max_turns + 1):
            self._log("turn_start", {"turn": turn})

            out = self._call_llm(convo, max_tokens=1800, temperature=0.2)
            self._log("llm_output", {"turn": turn, "text": out[:2000]})

            kind, payload = self._parse_action_block(out)

            if kind == "final":
                final = payload
                # Simple guard: if confidence missing, set low
                if isinstance(final, dict) and "confidence" not in final:
                    final["confidence"] = 0.5
                self._log("final", final)
                return {"success": True, "invention": final, "turns": turn}

            if kind == "action":
                tool, args = payload
                if tool != "retrieve_passages":
                    obs = {"error": f"Unknown tool: {tool}"}
                else:
                    query = args.get("query", "")
                    k = int(args.get("k", 5))
                    snippets = self._retrieve_passages(document_text, query=query, k=k)
                    obs = {"tool": tool, "query": query, "snippets": snippets}

                self._log("observation", obs)

                # Append observation and ask model to either call again or produce Final
                convo += f"\nObservation: {json.dumps(obs) }\n"
                convo += "\n(Use the observation to continue.)\n"
                continue

            # If bad format, force the model back to the spec
            convo += """
Observation: {"error":"Bad format. Use ONLY Action/Action Input or Final with JSON."}
"""
            continue

        return {"success": False, "error": "max_turns_reached", "logs": self.logs}
