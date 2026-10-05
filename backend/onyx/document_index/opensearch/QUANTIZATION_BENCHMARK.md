# Onyx OpenSearch quantization benchmark

**October 1, 2026 · EnterpriseRAG-Bench · 500 questions**

## Findings

Quantization substantially shrank the **vector search files**, but produced modest reductions in observed container RAM. Hybrid retrieval lost about **1 percentage point of recall** and showed no speed improvement.

**The minimum RAM needed for fast search without disk reads is still unknown.** This benchmark measured consumption with ample RAM. It did not measure file residency or disk reads, or test tighter memory limits.

## Accuracy and speed

| Quantization | Hybrid recall@10 | Hybrid recall@50 | Semantic recall@10 | Semantic recall@50 |
|---|---:|---:|---:|---:|
| None (float32) | **68.45%** | **79.28%** | **50.29%** | **60.65%** |
| 7-bit | 66.90% | 78.29% | 48.80% | 59.24% |
| 1-bit | 67.40% | 78.23% | 48.80% | 58.50% |

| Quantization | Hybrid median | Hybrid p95 | Hybrid queries/sec¹ |
|---|---:|---:|---:|
| None (float32) | **170 ms** | **269 ms** | **21.40** |
| 7-bit | 178 ms | 279 ms | 20.71 |
| 1-bit | 178 ms | 290 ms | 20.75 |

¹ Throughput uses four concurrent requests. Median and p95 use serial native retrieval timings. Query embedding network time is excluded.

Hybrid recall@50 fell **0.99 points at 7-bit** and **1.05 points at 1-bit**. Both paired 95% confidence intervals include zero; a clear hybrid accuracy difference is not established.

## Resources and savings

| Quantization | Avg. hybrid RAM² | Avg. hybrid CPU³ | Total index disk | Vector search files⁴ |
|---|---:|---:|---:|---:|
| None | 7.31 GiB | 0.96 cores | **8.28 GiB** | 4.63 GiB |
| 7-bit | **6.07 GiB** | 0.98 cores | 9.39 GiB | 1.24 GiB |
| 1-bit | 6.42 GiB | **0.94 cores** | 8.49 GiB | **0.34 GiB** |

² OpenSearch container memory, including Linux file cache. ³ Serial hybrid workload; excludes the Onyx API process.

⁴ Includes compound-file contents, both vector fields, graphs, and metadata. Quantized totals exclude retained floats. These are file sizes, **not resident RAM**.

- **Observed hybrid RAM:** 7-bit used 1.24 GiB less (17%); 1-bit used 0.88 GiB less (12%).
- **Vector search file footprint:** 7-bit was 73% smaller; 1-bit was 93% smaller.
- **Total disk:** quantization increased storage. Each quantized index retains approximately **4.50 GiB of float-vector data** alongside its compressed representation.

Lucene retains original vectors for full-precision rescoring. Onyx enables that rescoring. The fixed JVM heap, text search, and cached original-vector pages limit the observed RAM reduction. Linux can retain file pages when memory is available; consumption therefore does not establish required capacity. See [OpenSearch’s quantization documentation](https://docs.opensearch.org/3.6/vector-search/optimizing-storage/lucene-scalar-quantization/).

## What this means

**Unquantized retrieval had the highest hybrid recall and throughput in this run.** The 1-bit representation is much smaller than 7-bit; its higher observed hybrid RAM does not mean it requires more RAM.

For a defensible RAM requirement, measure resident pages by file type after warming all questions. Check disk-read bytes and latency on repeated searches, then confirm under a matching memory limit with headroom. **These checks have not yet been run.**

## Test conditions and retained data

- **Corpus:** 511,958 unique documents; 1,572,105 chunks. All 722 gold documents were present in every index.
- **Evaluation:** all 500 questions, semantic and hybrid search. Recall averages use the 470 questions with gold document IDs. Recall@10 and recall@50 score gold-document coverage in the first 10 and 50 retrieved chunks. Recall@10 reuses the saved top-50 rankings; no searches were rerun.
- **Repetitions:** three timing passes; first-pass accuracy. Official recall scoring agreed. No reranking, answer generation, or LLM judging.
- **Isolation:** one deployment at a time; six CPUs, 12-GiB memory limit, fixed 2-GiB JVM heap, 10 segments per index.
- **Embeddings:** Cohere `embed-english-light-v3.0`, 384 dimensions. Identical saved records and query vectors were reused across all levels.
- **Software:** Onyx main `d1f33f62e724b1c19a4bb3388883165e2e1ff64c`; OpenSearch 3.6.0; [EnterpriseRAG-Bench](https://github.com/onyx-dot-app/EnterpriseRAG-Bench) commit `d36685e273713975ee20299bbf1ab64165575b3c`.

The corpus, indices, volumes, embeddings, and detailed measurements remain saved locally for retesting.
