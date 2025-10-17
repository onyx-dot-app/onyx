---
name: python-rag-vector-db
description: Best practices for RAG implementation, vector embeddings, and Vespa database operations in the Onyx platform. Use when working on document indexing, semantic search, chunking strategies, or vector database queries.
---

# Python RAG & Vector Database Skill for Onyx

## Overview

This skill covers the core RAG (Retrieval-Augmented Generation) implementation patterns used in Onyx, including vector embedding workflows, Vespa database operations, hybrid search, and document processing. Onyx uses sentence-transformers for embeddings and Vespa as the vector database.

## Architecture Context

**Onyx RAG Stack:**
- **Embedding Models**: sentence-transformers (configurable models)
- **Vector Database**: Vespa (hybrid search capable)
- **Document Processing**: Background service handles indexing
- **Search Strategy**: Hybrid search (keyword + semantic)
- **Storage**: PostgreSQL for metadata, Vespa for vectors and search

**Key Files in Onyx:**
- `backend/onyx/search/` - Search implementations
- `backend/onyx/indexing/` - Document indexing logic
- `backend/onyx/chunking/` - Document chunking strategies
- `backend/onyx/document_index/` - Vespa interface
- `backend/onyx/background/` - Background indexing tasks

## Vector Embedding Best Practices

### Model Selection and Configuration

```python
# Onyx pattern for embedding model initialization
from sentence_transformers import SentenceTransformer
from onyx.configs.model_configs import DOCUMENT_ENCODER_MODEL

def get_embedding_model() -> SentenceTransformer:
    """
    Load the configured embedding model.
    Onyx supports multiple embedding models via configuration.
    """
    model = SentenceTransformer(
        DOCUMENT_ENCODER_MODEL,
        device="cuda" if torch.cuda.is_available() else "cpu"
    )
    # Set to evaluation mode for inference
    model.eval()
    return model
```

### Batch Embedding for Performance

```python
# Efficient batch processing for large-scale indexing
def embed_chunks_batch(
    chunks: list[str],
    model: SentenceTransformer,
    batch_size: int = 32
) -> list[list[float]]:
    """
    Embed text chunks in batches for optimal performance.
    
    Key considerations:
    - Batch size affects memory usage and throughput
    - Use show_progress_bar for long-running operations
    - Normalize embeddings for cosine similarity
    """
    embeddings = model.encode(
        chunks,
        batch_size=batch_size,
        show_progress_bar=True,
        convert_to_numpy=True,
        normalize_embeddings=True  # For cosine similarity
    )
    return embeddings.tolist()
```

### Embedding Caching Strategy

```python
# Onyx caches embeddings to avoid recomputation
from functools import lru_cache
import hashlib

def get_chunk_hash(text: str) -> str:
    """Generate stable hash for chunk content."""
    return hashlib.sha256(text.encode()).hexdigest()

def embed_with_cache(
    chunk: str,
    model: SentenceTransformer,
    cache: dict[str, list[float]]
) -> list[float]:
    """
    Embed chunk with caching to avoid redundant computation.
    Useful for documents that haven't changed.
    """
    chunk_hash = get_chunk_hash(chunk)
    
    if chunk_hash in cache:
        return cache[chunk_hash]
    
    embedding = model.encode(chunk, normalize_embeddings=True)
    cache[chunk_hash] = embedding.tolist()
    return cache[chunk_hash]
```

## Document Chunking Strategies

### Onyx Chunking Approach

```python
from onyx.configs.app_configs import CHUNK_SIZE, CHUNK_OVERLAP

def chunk_document(
    text: str,
    chunk_size: int = CHUNK_SIZE,
    chunk_overlap: int = CHUNK_OVERLAP,
    preserve_sentences: bool = True
) -> list[str]:
    """
    Chunk document text for embedding and retrieval.

    Onyx chunking principles:
    1. Preserve semantic boundaries (sentences, paragraphs)
    2. Maintain context with overlap
    3. Handle edge cases (short docs, code blocks)
    4. Optimize for retrieval quality over quantity

    Default: 512 tokens with 128 token overlap
    """
    if preserve_sentences:
        # Use spaCy or NLTK for sentence boundary detection
        chunks = chunk_by_sentences(text, chunk_size, chunk_overlap)
    else:
        # Simple token-based chunking
        chunks = chunk_by_tokens(text, chunk_size, chunk_overlap)

    return chunks

def chunk_by_sentences(
    text: str,
    target_size: int,
    overlap: int
) -> list[str]:
    """
    Chunk text while preserving sentence boundaries.
    Better for semantic coherence.
    """
    import spacy
    
    nlp = spacy.load("en_core_web_sm")
    doc = nlp(text)
    sentences = [sent.text for sent in doc.sents]
    
    chunks = []
    current_chunk = []
    current_size = 0
    
    for sentence in sentences:
        sentence_tokens = len(sentence.split())
        
        if current_size + sentence_tokens > target_size and current_chunk:
            # Save current chunk
            chunks.append(" ".join(current_chunk))
            
            # Start new chunk with overlap
            overlap_sentences = get_overlap_sentences(
                current_chunk, overlap
            )
            current_chunk = overlap_sentences
            current_size = sum(len(s.split()) for s in current_chunk)
        
        current_chunk.append(sentence)
        current_size += sentence_tokens
    
    if current_chunk:
        chunks.append(" ".join(current_chunk))
    
    return chunks
```

### Specialized Chunking for Code

```python
def chunk_code_document(
    code: str,
    language: str,
    chunk_size: int = 512
) -> list[dict]:
    """
    Chunk code while preserving logical structure.
    
    Strategy for code:
    1. Keep functions/classes together when possible
    2. Preserve imports and context
    3. Add metadata about code structure
    """
    from tree_sitter import Language, Parser
    
    chunks = []
    
    # Parse code into AST
    parser = get_parser_for_language(language)
    tree = parser.parse(bytes(code, "utf8"))
    
    # Extract logical units (functions, classes)
    for node in extract_code_blocks(tree.root_node):
        chunk_text = code[node.start_byte:node.end_byte]
        
        # Add context (imports, class definition)
        context = extract_context(code, node)
        
        chunks.append({
            "text": chunk_text,
            "context": context,
            "type": node.type,
            "start_line": node.start_point[0],
            "end_line": node.end_point[0]
        })
    
    return chunks
```

## Vespa Database Operations

### Document Schema Design

```python
# Onyx Vespa schema pattern
VESPA_DOCUMENT_SCHEMA = """
schema document {
    document document {
        field doc_id type string {
            indexing: summary | attribute
            match: exact
        }
        
        field chunk_id type int {
            indexing: summary | attribute
        }
        
        field content type string {
            indexing: summary | index
            match: text
            index: enable-bm25
        }
        
        field title type string {
            indexing: summary | index
            match: text
        }
        
        field embedding type tensor<float>(x[384]) {
            indexing: summary | attribute | index
            attribute {
                distance-metric: angular
            }
            index {
                hnsw {
                    max-links-per-node: 16
                    neighbors-to-explore-at-insert: 200
                }
            }
        }
        
        field source_type type string {
            indexing: summary | attribute
        }
        
        field access_control type array<string> {
            indexing: summary | attribute
        }
        
        field created_at type long {
            indexing: summary | attribute
        }
    }
    
    fieldset default {
        fields: content, title
    }
    
    rank-profile hybrid {
        first-phase {
            expression: 0.7 * bm25(content) + 0.3 * closeness(field, embedding)
        }
    }
}
"""
```

### Indexing Documents to Vespa

```python
from vespa.application import Vespa

def index_document_to_vespa(
    vespa_app: Vespa,
    doc_id: str,
    chunks: list[dict],
    embeddings: list[list[float]],
    metadata: dict
) -> list[str]:
    """
    Index document chunks to Vespa with embeddings.
    
    Onyx pattern:
    1. Each chunk becomes a separate Vespa document
    2. Preserve document-level metadata
    3. Handle access control at index time
    4. Batch operations for performance
    """
    indexed_ids = []
    
    for i, (chunk, embedding) in enumerate(zip(chunks, embeddings)):
        vespa_doc_id = f"{doc_id}_{i}"
        
        vespa_document = {
            "fields": {
                "doc_id": doc_id,
                "chunk_id": i,
                "content": chunk["text"],
                "title": metadata.get("title", ""),
                "embedding": {"values": embedding},
                "source_type": metadata.get("source_type", ""),
                "access_control": metadata.get("access_control", []),
                "created_at": metadata.get("created_at", 0)
            }
        }
        
        response = vespa_app.feed_data_point(
            schema="document",
            data_id=vespa_doc_id,
            fields=vespa_document["fields"]
        )
        
        if response.status_code == 200:
            indexed_ids.append(vespa_doc_id)
    
    return indexed_ids
```

### Hybrid Search Implementation

```python
def hybrid_search(
    vespa_app: Vespa,
    query: str,
    query_embedding: list[float],
    user_groups: list[str],
    limit: int = 10,
    keyword_weight: float = 0.7,
    semantic_weight: float = 0.3
) -> list[dict]:
    """
    Perform hybrid search combining BM25 and semantic search.
    
    Onyx hybrid search strategy:
    1. BM25 for keyword matching (good for exact terms)
    2. Vector similarity for semantic matching
    3. Access control filtering
    4. Configurable weighting
    """
    # Build Vespa YQL query
    yql = f"""
        SELECT doc_id, chunk_id, content, title
        FROM document
        WHERE (
            {{targetHits: {limit}}}nearestNeighbor(embedding, query_embedding)
            OR userQuery()
        )
        AND (
            {" OR ".join(f'access_control contains "{group}"' for group in user_groups)}
        )
        LIMIT {limit}
    """
    
    query_params = {
        "yql": yql,
        "query": query,
        "ranking": "hybrid",
        "input.query(query_embedding)": query_embedding,
        "ranking.profile": "hybrid"
    }
    
    response = vespa_app.query(body=query_params)
    
    # Parse and return results
    results = []
    for hit in response.hits:
        results.append({
            "doc_id": hit["fields"]["doc_id"],
            "chunk_id": hit["fields"]["chunk_id"],
            "content": hit["fields"]["content"],
            "title": hit["fields"]["title"],
            "score": hit["relevance"]
        })
    
    return results
```

### Query Rewriting and Expansion

```python
def expand_query(
    query: str,
    model: SentenceTransformer,
    enable_multilingual: bool = True
) -> list[str]:
    """
    Expand query for better recall.
    
    Onyx query expansion techniques:
    1. Synonym expansion
    2. Multilingual translation (if enabled)
    3. Query decomposition for complex queries
    """
    expanded_queries = [query]
    
    if enable_multilingual:
        # Translate query to configured languages
        from onyx.configs.app_configs import MULTILINGUAL_QUERY_EXPANSION
        languages = MULTILINGUAL_QUERY_EXPANSION.split(",")
        
        for lang in languages:
            if lang.lower() != "english":
                translated = translate_query(query, target_lang=lang)
                expanded_queries.append(translated)
    
    return expanded_queries
```

## Reranking and Postprocessing

### Cross-Encoder Reranking

```python
from sentence_transformers import CrossEncoder

def rerank_results(
    query: str,
    results: list[dict],
    cross_encoder: CrossEncoder,
    top_k: int = 5
) -> list[dict]:
    """
    Rerank results using cross-encoder for better relevance.
    
    Onyx reranking strategy:
    1. Initial retrieval gets top-N candidates (e.g., 20)
    2. Cross-encoder reranks to top-K (e.g., 5)
    3. More accurate but slower than bi-encoder
    """
    if len(results) <= top_k:
        return results
    
    # Prepare pairs for cross-encoder
    pairs = [[query, result["content"]] for result in results]
    
    # Get relevance scores
    scores = cross_encoder.predict(pairs)
    
    # Add scores and sort
    for result, score in zip(results, scores):
        result["rerank_score"] = float(score)
    
    # Sort by rerank score and return top K
    reranked = sorted(
        results,
        key=lambda x: x["rerank_score"],
        reverse=True
    )[:top_k]
    
    return reranked
```

### Deduplication

```python
def deduplicate_chunks(
    results: list[dict],
    similarity_threshold: float = 0.95
) -> list[dict]:
    """
    Remove near-duplicate chunks from results.
    
    Common in Onyx when:
    - Same content indexed multiple times
    - Overlapping chunks
    - Similar sections in different documents
    """
    from sklearn.metrics.pairwise import cosine_similarity
    import numpy as np
    
    if len(results) <= 1:
        return results
    
    # Get embeddings for all result contents
    model = get_embedding_model()
    contents = [r["content"] for r in results]
    embeddings = model.encode(contents, normalize_embeddings=True)
    
    # Compute similarity matrix
    similarity_matrix = cosine_similarity(embeddings)
    
    # Keep track of which results to keep
    keep_indices = []
    seen_similar = set()
    
    for i in range(len(results)):
        if i in seen_similar:
            continue
        
        keep_indices.append(i)
        
        # Mark similar results as seen
        for j in range(i + 1, len(results)):
            if similarity_matrix[i][j] > similarity_threshold:
                seen_similar.add(j)
    
    return [results[i] for i in keep_indices]
```

## Performance Optimization

### Batch Processing for Large-Scale Indexing

```python
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Iterator

def batch_index_documents(
    documents: Iterator[dict],
    batch_size: int = 100,
    max_workers: int = 4
) -> dict[str, int]:
    """
    Index documents in parallel batches.
    
    Onyx background indexing pattern:
    1. Process documents in batches
    2. Parallelize embedding and indexing
    3. Handle failures gracefully
    4. Track progress
    """
    stats = {"success": 0, "failed": 0}
    model = get_embedding_model()
    vespa_app = get_vespa_client()
    
    def process_batch(batch: list[dict]) -> tuple[int, int]:
        """Process a single batch of documents."""
        success = 0
        failed = 0
        
        for doc in batch:
            try:
                # Chunk document
                chunks = chunk_document(doc["content"])
                
                # Generate embeddings
                embeddings = embed_chunks_batch(chunks, model)
                
                # Index to Vespa
                index_document_to_vespa(
                    vespa_app,
                    doc["id"],
                    [{"text": c} for c in chunks],
                    embeddings,
                    doc["metadata"]
                )
                success += 1
                
            except Exception as e:
                logger.error(f"Failed to index document {doc['id']}: {e}")
                failed += 1
        
        return success, failed
    
    # Batch and parallelize
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        batch = []
        futures = []
        
        for doc in documents:
            batch.append(doc)
            
            if len(batch) >= batch_size:
                future = executor.submit(process_batch, batch)
                futures.append(future)
                batch = []
        
        # Process remaining
        if batch:
            future = executor.submit(process_batch, batch)
            futures.append(future)
        
        # Collect results
        for future in as_completed(futures):
            success, failed = future.result()
            stats["success"] += success
            stats["failed"] += failed
    
    return stats
```

### Memory Management for Large Documents

```python
def process_large_document_streaming(
    file_path: str,
    chunk_size: int = 1024 * 1024  # 1MB chunks
) -> Iterator[str]:
    """
    Process large documents without loading entire file into memory.
    
    Use for:
    - Large PDFs
    - Long transcripts
    - Big log files
    """
    with open(file_path, 'r', encoding='utf-8') as f:
        buffer = ""
        
        while True:
            chunk = f.read(chunk_size)
            if not chunk:
                break
            
            buffer += chunk
            
            # Process complete sentences/paragraphs
            while '\n\n' in buffer:
                section, buffer = buffer.split('\n\n', 1)
                yield section
        
        # Yield remaining buffer
        if buffer:
            yield buffer
```

## Testing and Validation

### Embedding Quality Tests

```python
def test_embedding_quality():
    """
    Test embedding model produces expected results.
    
    Run this after model updates or configuration changes.
    """
    model = get_embedding_model()
    
    # Test semantic similarity
    similar_texts = [
        "The quick brown fox jumps over the lazy dog",
        "A fast brown fox leaps over a sleepy dog"
    ]
    dissimilar_text = "Python programming language features"
    
    emb1, emb2 = model.encode(similar_texts)
    emb3 = model.encode([dissimilar_text])[0]
    
    # Calculate similarities
    sim_similar = cosine_similarity([emb1], [emb2])[0][0]
    sim_dissimilar = cosine_similarity([emb1], [emb3])[0][0]
    
    assert sim_similar > 0.8, "Similar texts should have high similarity"
    assert sim_dissimilar < 0.5, "Dissimilar texts should have low similarity"
    
    print(f"✓ Embedding quality test passed")
    print(f"  Similar texts: {sim_similar:.3f}")
    print(f"  Dissimilar texts: {sim_dissimilar:.3f}")
```

### Retrieval Quality Evaluation

```python
def evaluate_retrieval_quality(
    test_queries: list[dict],
    vespa_app: Vespa
) -> dict:
    """
    Evaluate retrieval quality using test set.
    
    test_queries format:
    [
        {
            "query": "How do I reset my password?",
            "relevant_docs": ["doc_123", "doc_456"]
        },
        ...
    ]
    
    Metrics:
    - Precision@K
    - Recall@K
    - MRR (Mean Reciprocal Rank)
    """
    model = get_embedding_model()
    metrics = {
        "precision_at_5": [],
        "recall_at_5": [],
        "mrr": []
    }
    
    for test_case in test_queries:
        query = test_case["query"]
        relevant_docs = set(test_case["relevant_docs"])
        
        # Perform search
        query_emb = model.encode([query])[0]
        results = hybrid_search(vespa_app, query, query_emb.tolist())
        
        retrieved_docs = [r["doc_id"] for r in results[:5]]
        
        # Calculate metrics
        true_positives = len(set(retrieved_docs) & relevant_docs)
        
        precision = true_positives / min(5, len(retrieved_docs))
        recall = true_positives / len(relevant_docs)
        
        # MRR
        mrr = 0
        for i, doc_id in enumerate(retrieved_docs, 1):
            if doc_id in relevant_docs:
                mrr = 1.0 / i
                break
        
        metrics["precision_at_5"].append(precision)
        metrics["recall_at_5"].append(recall)
        metrics["mrr"].append(mrr)
    
    # Average metrics
    return {
        "precision@5": np.mean(metrics["precision_at_5"]),
        "recall@5": np.mean(metrics["recall_at_5"]),
        "mrr": np.mean(metrics["mrr"])
    }
```

## Common Patterns and Anti-Patterns

### ✅ DO: Use Appropriate Chunk Sizes

```python
# Good: Adjust chunk size based on content type
def get_chunk_config(source_type: str) -> dict:
    configs = {
        "code": {"size": 256, "overlap": 50},  # Smaller for code
        "documentation": {"size": 512, "overlap": 128},  # Standard
        "chat": {"size": 128, "overlap": 32},  # Smaller for chat
        "long_form": {"size": 1024, "overlap": 256}  # Larger for articles
    }
    return configs.get(source_type, configs["documentation"])
```

### ❌ DON'T: Ignore Access Control

```python
# Bad: No access control check
def search_without_access_control(query: str):
    return vespa_app.query(query)  # Returns all results!

# Good: Always filter by user permissions
def search_with_access_control(query: str, user_groups: list[str]):
    return hybrid_search(
        vespa_app,
        query,
        query_embedding,
        user_groups=user_groups  # Critical!
    )
```

### ✅ DO: Handle Embedding Model Updates

```python
# Good: Version embeddings for model changes
def index_with_versioning(doc, model_version: str):
    embedding = get_embedding(doc.content)
    vespa_document = {
        "embedding": embedding,
        "embedding_model_version": model_version  # Track version
    }
    # Can reindex selectively when model changes
```

## Troubleshooting Guide

**Issue**: Low retrieval quality
- Check embedding model is appropriate for domain
- Verify chunk size isn't too large or small
- Test with different hybrid search weights
- Add reranking stage
- Evaluate with test queries

**Issue**: Slow indexing
- Increase batch size for embeddings
- Use parallel processing
- Profile to find bottleneck
- Consider caching unchanged documents

**Issue**: High memory usage
- Process documents in streaming fashion
- Clear embedding cache periodically
- Reduce batch size
- Use memory profiler to identify leaks

**Issue**: Vespa connection errors
- Verify Vespa is running and accessible
- Check network connectivity
- Review Vespa logs for errors
- Validate schema deployment

## Additional Resources

- Onyx documentation: https://docs.onyx.app
- Sentence-transformers docs: https://www.sbert.net
- Vespa documentation: https://docs.vespa.ai
- RAG best practices: Research papers on retrieval quality
