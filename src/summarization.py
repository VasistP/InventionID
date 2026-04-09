import boto3
from botocore.config import Config
from botocore.exceptions import ClientError
import json
import asyncio
import time
from typing import List, Dict, Any, Optional


bedrock = boto3.client(
    service_name="bedrock-runtime",
    region_name="us-east-2",
    config= Config(max_pool_connections=10)
)

def summarize_text_haiku(text: str) -> str:
    prompt = f"""Summarize the following text in 5-7 sentences optimized for search retrieval. Your summary must:

1. State facts directly without referencing any paper, author, section, or text.
2. Preserve ALL specific technical terms, method names, algorithm names, model architectures, and domain-specific vocabulary.
3. Include specific quantities, metrics, datasets, and benchmarks mentioned.
4. Name the concrete problem being solved and the concrete approach used.
5. Include key technical features, components, and their relationships.

Bad: "This paper proposes a framework..."
Bad: "The authors introduce..."
Bad: "A method is described for improving performance."
Good: "A hierarchical multi-agent reinforcement learning framework dynamically assigns sub-tasks using attention-based communication between agents. The reward shaping mechanism uses potential-based functions to address sparse reward problems in cooperative navigation."
Good: "Decentralized control with graph neural network message passing enables coordination among 64 autonomous drones. Collision avoidance uses velocity obstacles combined with A* path planning."

If the text is just a list of references/citations, simply respond with: "Reference list of the paper."
If the text is a NeurIPS/conference paper checklist, ethics statement, broader impact statement, reproducibility statement, or submission guidelines, simply respond with: "NONE"

Text:
{text}

Summary:"""

    body = {
        "anthropic_version": "bedrock-2023-05-31",
        "max_tokens": 1000,
        "temperature": 0.1,
        "messages": [
            {
                "role": "user",
                "content": prompt
            }
        ]
    }

    for attempt in range(4):
        try:
            response = bedrock.invoke_model(
                modelId="us.anthropic.claude-haiku-4-5-20251001-v1:0",
                body=json.dumps(body),
                contentType="application/json",
                accept="application/json"
            )
            result = json.loads(response["body"].read())
            return result["content"][0]["text"].strip()
        except ClientError as e:
            if "ServiceUnavailable" in str(e) or "ThrottlingException" in str(e):
                wait = 2 ** attempt
                print(f"  Bedrock throttled (attempt {attempt+1}/4), retrying in {wait}s...")
                time.sleep(wait)
            else:
                raise
    raise RuntimeError("Bedrock summarization failed after 4 retries")


def embed_text_titan(text: str) -> list[float]:
    body = {
        "inputText": text,
        # Optional knobs (only if you know you want them):
        "normalize": True
        # "dimensions": 1024,
    }

    resp = bedrock.invoke_model(
        modelId="amazon.titan-embed-text-v2:0",
        body=json.dumps(body),
        contentType="application/json",
        accept="application/json",
    )

    out = json.loads(resp["body"].read())

    return out["embedding"]


def build_section_summary_items(chunks: list[dict]) -> dict:
    section_items = {}

    for ch in chunks:
        sid = ch["section_id"]
        title = ch.get("title", "")
        summary = (ch.get("summary") or "").strip()

        if not summary:
            continue

        if sid not in section_items:
            section_items[sid] = {
                "section_id": sid,
                "section_title": title,
                "rolling_summary": []
            }

        # prepend bullet
        section_items[sid]["rolling_summary"].append(f"- {summary}")

    return section_items




def summarize_sections(sections: list[dict]) -> list[dict]:
    for section in sections:
        text = section.get("text", "").strip()

        if not text:
            section["summary"] = ""
            continue

        section["summary"] = summarize_text_haiku(text)

    return sections


async def _summarize_one(section: Dict[str, Any], sem: asyncio.Semaphore) -> Dict[str, Any]:
    text = (section.get("text") or "").strip()
    if not text:
        section["summary"] = ""
        return section

    async with sem:
        # run the blocking boto3 call in a thread
        summary = await asyncio.to_thread(summarize_text_haiku, text)

    section["summary"] = summary
    return section

async def summarize_sections_async(
    sections: List[Dict[str, Any]],
    concurrency: int = 5
) -> List[Dict[str, Any]]:
    sem = asyncio.Semaphore(concurrency)
    tasks = [_summarize_one(sec, sem) for sec in sections]
    return await asyncio.gather(*tasks)

def summarize_sections_parallel(
    sections: List[Dict[str, Any]],
    concurrency: int = 5
) -> List[Dict[str, Any]]:
    return asyncio.run(summarize_sections_async(sections, concurrency=concurrency))


async def _embed_one(section: dict, sem: asyncio.Semaphore) -> dict:
    summary = (section.get("summary") or "").strip()
    text = (section.get("text") or "").strip()
    to_embed = summary if summary else text

    if not to_embed:
        section["embedding"] = []
        return section

    async with sem:
        emb = await asyncio.to_thread(embed_text_titan, to_embed)

    section["embedding"] = emb
    return section

def add_embeddings_parallel(sections: list[dict], concurrency: int = 5) -> list[dict]:
    async def run():
        sem = asyncio.Semaphore(concurrency)
        return await asyncio.gather(*[_embed_one(s, sem) for s in sections])
    return asyncio.run(run())