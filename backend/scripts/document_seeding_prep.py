"""
How to update seeded docs:
Go to the documentation repo and select the docs you want.
Have an AI assistant convert it to the same format as initial_docs_cohere.json (easier than manual or writing a script)
Verify the titles, content, and urls.
Run this script.
Update the load_docs.py if relevant.
"""

import json
from pathlib import Path

from pydantic import BaseModel
from sentence_transformers import SentenceTransformer  # type: ignore


class SeedPresaveDocument(BaseModel):
    url: str
    title: str
    content: str
    title_embedding: list[float]
    content_embedding: list[float]
    chunk_ind: int = 0


# Initialize embedding model (keep default used by the app)
model = SentenceTransformer("nomic-ai/nomic-embed-text-v1", trust_remote_code=True)
_ = model.tokenizer  # kept for parity; unused but ensures tokenizer loads

base_path = Path("./backend/onyx/seeding")
input_path = base_path / "initial_docs_cohere.json"
output_path = base_path / "initial_docs.json"

raw_docs: list[dict] = json.loads(input_path.read_text())

documents: list[SeedPresaveDocument] = []
for d in raw_docs:
    title = (d.get("title") or "").strip()
    content = d.get("content") or ""
    url = d.get("url") or ""
    chunk_ind = int(d.get("chunk_ind", 0))

    title_emb = list(model.encode(f"search_document: {title}"))
    content_emb = list(model.encode(f"search_document: {title}\n{content}"))

    documents.append(
        SeedPresaveDocument(
            url=url,
            title=title,
            content=content,
            title_embedding=title_emb,
            content_embedding=content_emb,
            chunk_ind=chunk_ind,
        )
    )

output_path.write_text(json.dumps([d.model_dump() for d in documents], indent=4))
