# File: onyx/connectors/github_code/embedding.py

import math
from typing import List, Tuple, Optional

try:
    from tree_sitter import Language, Parser
    # Load or build language parsers for JS, TS, Ruby, C#
    # Assuming we have pre-built Tree-sitter languages .so for simplicity:
    LANGUAGES = {}
    try:
        LANGUAGES["javascript"] = Language("/usr/local/lib/my-languages.so", "javascript")
        LANGUAGES["typescript"] = Language("/usr/local/lib/my-languages.so", "typescript")
        LANGUAGES["ruby"] = Language("/usr/local/lib/my-languages.so", "ruby")
        LANGUAGES["csharp"] = Language("/usr/local/lib/my-languages.so", "c_sharp")
    except Exception:
        # If loading fails, we'll not use AST parsing
        LANGUAGES = {}
except ImportError:
    LANGUAGES = {}

import numpy as np

# Optional: import transformers or API clients
from transformers import AutoTokenizer, AutoModel
import torch
import openai
import cohere

class CodeEmbeddingPipeline:
    """Pipeline for chunking code and generating embeddings."""
    def __init__(self, model_name: str = "codebert",
                 openai_model: str = "text-embedding-ada-002",
                 cohere_model: str = "embed-english-v2.0",
                 chunk_size: int = 256, chunk_overlap: int = 50):
        self.model_name = model_name.lower()
        self.chunk_size = chunk_size
        self.chunk_overlap = chunk_overlap
        self.tokenizer = None
        self.model = None
        self.cohere_client = None

        # Setup embedding model based on selection
        if self.model_name in ("codebert", "unixcoder"):
            model_path = "microsoft/codebert-base" if self.model_name == "codebert" else "microsoft/unixcoder-base"
            self.tokenizer = AutoTokenizer.from_pretrained(model_path)
            self.model = AutoModel.from_pretrained(model_path)
            self.model.eval()
        elif self.model_name == "openai":
            # OpenAI API (ensure API key is set in environment or elsewhere)
            openai.api_key = os.getenv("OPENAI_API_KEY")
            self.openai_model = openai_model
        elif self.model_name == "cohere":
            self.cohere_client = cohere.Client(os.getenv("COHERE_API_KEY"))
            self.cohere_model = cohere_model
        else:
            # Default to codebert if unknown model_name
            self.tokenizer = AutoTokenizer.from_pretrained("microsoft/codebert-base")
            self.model = AutoModel.from_pretrained("microsoft/codebert-base")
            self.model.eval()

    def chunk_and_embed(self, code: str, language: Optional[str] = None) -> Tuple[List[str], List[List[float]]]:
        """Split code into chunks (AST-based if possible) and return chunks with their embedding vectors."""
        # Choose chunking strategy
        chunks: List[str] = []
        if language and language in LANGUAGES:
            try:
                chunks = self._ast_chunk(code, language)
            except Exception as e:
                # Fallback to sliding window if AST parse fails
                chunks = []
        if not chunks:
            chunks = self._slide_chunk(code)
        # Embed each chunk
        embeddings: List[List[float]] = self._embed_chunks(chunks)
        return chunks, embeddings

    def _ast_chunk(self, code: str, language: str) -> List[str]:
        """Use tree-sitter to chunk code by AST nodes (e.g., functions, classes)."""
        parser = Parser()
        parser.set_language(LANGUAGES[language])
        tree = parser.parse(code.encode("utf-8"))
        root = tree.root_node

        # Define AST node types to chunk at (terminal nodes of interest)
        # e.g., top-level function or class definitions in the AST grammar
        terminal_types = {"function_declaration", "method_definition", "class_declaration", "function_definition"}
        chunks: List[str] = []

        # Use a BFS or DFS to collect subtrees that are terminal (contain one function/class)
        stack = [root]
        while stack:
            node = stack.pop()
            if node.type in terminal_types:
                # Extract source code for this AST node
                start, end = node.start_byte, node.end_byte
                snippet = code[start:end]
                # Only take non-empty unique snippets
                snippet = snippet.strip()
                if snippet:
                    chunks.append(snippet)
            else:
                for child in node.children:
                    if not child.is_named:
                        continue  # skip unnamed tokens (punctuation, etc.)
                    # If child is large, we might consider splitting further inside
                    stack.append(child)
        # If no chunks found (e.g., code outside any function), return full code as one chunk (to avoid losing content)
        if not chunks:
            return [code]
        # Special handling: if code outside functions exists (e.g., top-level code), we could append it as separate chunk.
        # (Not implemented here for brevity)
        return chunks

    def _slide_chunk(self, text: str) -> List[str]:
        """Split text into overlapping chunks using a sliding window."""
        tokens = text.split()  # simple whitespace tokenization for chunking
        if len(tokens) <= self.chunk_size:
            # small file, one chunk
            return [text]
        chunks: List[str] = []
        step = self.chunk_size - self.chunk_overlap
        for i in range(0, len(tokens), step):
            window = tokens[i:i + self.chunk_size]
            if not window:
                break
            chunk_text = " ".join(window)
            chunks.append(chunk_text)
            if i + self.chunk_size >= len(tokens):
                break
        return chunks

    def _embed_chunks(self, chunks: List[str]) -> List[List[float]]:
        """Generate embedding vector for each chunk using the configured model."""
        vectors: List[List[float]] = []
        if not chunks:
            return vectors

        if self.model is not None and self.tokenizer is not None:
            # Local model (CodeBERT/UniXcoder): embed in batches
            batch_size = 16
            with torch.no_grad():
                for i in range(0, len(chunks), batch_size):
                    batch = chunks[i:i+batch_size]
                    inputs = self.tokenizer(batch, return_tensors="pt", padding=True, truncation=True)
                    outputs = self.model(**inputs)
                    # Use CLS token (at index 0) representation as embedding (CodeBERT uses RoBERTa, first token is <s>)
                    # outputs.last_hidden_state shape: [batch, seq_len, hidden_dim]
                    hidden_states = outputs.last_hidden_state
                    cls_embeddings = hidden_states[:, 0, :].cpu().numpy()
                    for vec in cls_embeddings:
                        # Normalize vector
                        norm_vec = vec / (np.linalg.norm(vec) + 1e-9)
                        vectors.append(norm_vec.tolist())
        elif self.model_name == "openai":
            # Use OpenAI embedding API (chunk into max 2048 tokens as needed)
            try:
                # The OpenAI API can accept up to 2048 tokens per input for ada-002
                # We send all chunks in one request if possible (OpenAI API allows batching up to 2048 tokens total input length)
                response = openai.Embedding.create(input=chunks, model=self.openai_model)
                for item in response["data"]:
                    vec = item["embedding"]
                    # Optionally normalize
                    norm_vec = np.array(vec) / (np.linalg.norm(vec) + 1e-9)
                    vectors.append(norm_vec.tolist())
            except Exception as e:
                print(f"[ERROR] OpenAI embedding failed: {e}")
                # In case of failure, fall back to empty or try smaller batches (omitted for brevity)
        elif self.model_name == "cohere" and self.cohere_client:
            try:
                resp = self.cohere_client.embed(texts=chunks, model=self.cohere_model)
                for vec in resp.embeddings:
                    # Normalize vector
                    vec = np.array(vec)
                    norm_vec = vec / (np.linalg.norm(vec) + 1e-9)
                    vectors.append(norm_vec.tolist())
            except Exception as e:
                print(f"[ERROR] Cohere embedding failed: {e}")
        else:
            # If no model configured (should not happen given defaults), return empty vectors
            vectors = [[] for _ in chunks]
        return vectors
