import boto3
from botocore.config import Config
import json
import asyncio
from typing import List, Dict, Any, Optional


bedrock = boto3.client(
    service_name="bedrock-runtime",
    region_name="us-east-2",
    config= Config(max_pool_connections=10)
)

def summarize_text_haiku(text: str) -> str:
    prompt = f"""
Summarize the following scientific text in 2–3 concise sentences.
Focus on contribution, method, and results.

Text:
{text}

Return ONLY the summary text.
"""

    body = {
        "anthropic_version": "bedrock-2023-05-31",
        "max_tokens": 500,
        "temperature": 0.2,
        "messages": [
            {
                "role": "user",
                "content": prompt
            }
        ]
    }

    response = bedrock.invoke_model(
        modelId="us.anthropic.claude-haiku-4-5-20251001-v1:0",
        body=json.dumps(body),
        contentType="application/json",
        accept="application/json"
    )

    result = json.loads(response["body"].read())
    return result["content"][0]["text"].strip()


def embed_text_titan(text: str) -> list[float]:
    body = {
        "inputText": text
        # Optional knobs (only if you know you want them):
        # "normalize": True,
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