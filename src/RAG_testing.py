import faiss, json 
import numpy as np
from summarization import embed_text_titan




with open("src/storage/sections_with_summary_and_embedding.json", "r") as f:
    chunk_embed = json.load(f)


vecs = np.array([c["embedding"] for c in chunk_embed], dtype=np.float32)
dim = vecs.shape[1]
index = faiss.IndexFlatIP(dim)
index.add(vecs)

id_map = [{"section_id": c["section_id"]} for c in chunk_embed]

faiss.write_index(index, "src/storage/index.faiss")
with open("src/storage/id_map.json", "w") as f:
    json.dump(id_map, f)

# --- Query & Retrieve ---


query = "What is the main contribution and novelty?"

query_vec = np.array([embed_text_titan(query)], dtype=np.float32)

k = 3  # top-k results
scores, indices = index.search(query_vec, k)

print(f"\nQuery: {query}\n")
for rank, (score, idx) in enumerate(zip(scores[0], indices[0]), 1):
    chunk = chunk_embed[idx]
    print(f"  #{rank} (score: {score:.4f}) [{chunk['section_id']}] {chunk.get('title', '')}")
    print(f"    {chunk.get('summary', chunk.get('text', ''))[:200]}...")
    print()

query = "What problem does this work solve and how?"

query_vec = np.array([embed_text_titan(query)], dtype=np.float32)

k = 3  # top-k results
scores, indices = index.search(query_vec, k)

print(f"\nQuery: {query}\n")
for rank, (score, idx) in enumerate(zip(scores[0], indices[0]), 1):
    chunk = chunk_embed[idx]
    print(f"  #{rank} (score: {score:.4f}) [{chunk['section_id']}] {chunk.get('title', '')}")
    print(f"    {chunk.get('summary', chunk.get('text', ''))[:200]}...")
    print()

