This directory contains code that was useful and may become useful again in the future.

We stopped using rerankers because the state of the art rerankers are not significantly better than the biencoders and much worse than LLMs which are also capable of acting on a small set of documents for filtering, reranking, etc.

We stopped using the internal query classifier as that's now offloaded to the LLM which does query expansion so we know ahead of time if it's a keyword or semantic query.
