# Vertex / Gemini embedding limits

Researched 2026-11-20. "GUESS" = no official source.

## Vertex AI quotas (per project)

| Model | Path | RPM | Input TPM | Scope |
|---|---|---|---|---|
| gemini-embedding-2 | `:embedContent` | 60,000 | 200,000,000 | global, per base model |
| "gemini-embedding" (001 or family; unclear) | `:embedContent` | 100,000 | 100,000,000 | global, per base model |
| gemini-embedding-001 | `:predict` | 30,000 (`online_prediction_requests`) | not stated | shared by `:predict` models |
| text-embedding-005 / multilingual-002 | `:predict` | not listed (1,500 is the old gecko value, GUESS) | not listed | regional |

Quota metrics: `aiplatform.googleapis.com/global_embed_content_requests_per_minute_per_base_model` and `..._input_tokens_per_minute_per_base_model`.

- **DSQ / fixed quota:** The gemini-embedding-2 model page says "Fixed quota: Not supported" and "Standard PayGo: Supported". The DSQ page lists no embedding models. Forum users report contention 429s at under 5% of quota.
- **Provisioned Throughput:** Not supported for gemini-embedding-2. No embedding model is on the PT list. For models that support PT, use above the purchased amount spills over to PayGo. With the dedicated-only header, the request gets a 429 instead.
- **Express mode:** It supports only Gemini generative models (10 RPM). It does not support embeddings. The free trial ($300 credit) uses the normal PayGo path. No separate embedding quota is documented.
- **Google guidance on 429s:** Use the `global` endpoint, truncated exponential backoff and a slow ramp-up. One-second spikes are throttled even inside the per-minute quota.

## Gemini Developer API (API key, per project)

| Tier | Requirement | RPM | TPM | RPD | Batch enqueued tokens |
|---|---|---|---|---|---|
| Free | none | 100* | 30,000* | 1,000* | no batch |
| Tier 1 | billing linked | 3,000* | 1,000,000* | unlimited | 500,000 |
| Tier 2 | $100 spend + 3 days | 5,000* | 5M (GUESS) | unlimited | 5,000,000 |
| Tier 3 | $1,000 spend + 30 days | 20,000* | 20,000,000* | unlimited | 10,000,000 |

\* Values that users report from the AI Studio dashboard. The official page now shows these limits only in AI Studio. RPD resets at midnight Pacific. Batch is 50% price.

## Limits for each request

| Model | Max tokens per input | Inputs per request | Dimensions |
|---|---|---|---|
| gemini-embedding-2 | 8,192 (all modalities together) | 1 on Vertex (the SDK raises an error for more) | 128-3072, default 3072. Recommended: 768/1536/3072. The model normalizes automatically. |
| gemini-embedding-001 | 2,048 | Vertex docs conflict: 250 or "single input text" | 128-3072, default 3072. Normalize it yourself if dimensions are below 3072. |
| text-embedding-005, multilingual-002 | 2,048 | 250, and 20,000 tokens total (400 error above that) | up to 768 |

`autoTruncate` defaults to `true`, and the model silently truncates excess input. With `false`, an input that is too long gives a 400 error. gemini-embedding-2 does not support `task_type`. Put the task in the text as a prefix.

## Wire formats (Vertex v1)

SDK check (google-genai 2.18.1, `models.py`). `t_is_vertex_embed_content_model()` is true for any model name that contains "gemini", except `gemini-embedding-001`. Those models use `:embedContent` with a single `content`. `gemini-embedding-001` and `text-embedding-*` use `:predict`.

**embedContent** `POST https://aiplatform.googleapis.com/v1/projects/P/locations/global/publishers/google/models/gemini-embedding-2:embedContent`

```json
{"content": {"role": "user", "parts": [{"text": "..."}]},
 "embedContentConfig": {"outputDimensionality": 768, "autoTruncate": true, "title": "...", "taskType": "RETRIEVAL_DOCUMENT"}}
```
```json
{"embedding": {"values": [0.01, -0.02]},
 "usageMetadata": {"promptTokenCount": 325, "totalTokenCount": 325,
                   "promptTokensDetails": [{"modality": "TEXT", "tokenCount": 325}]},
 "truncated": false}
```
The SDK (`_EmbedContentResponse_from_vertex`) maps this response to `embeddings[0].values`. It stores `promptTokenCount` in `statistics.token_count` and `truncated` in `statistics.truncated`. Top-level `taskType`/`autoTruncate`/etc. are deprecated.

**predict** (`gemini-embedding-001`, `text-embedding-005`)
```json
{"instances": [{"content": "TEXT", "task_type": "RETRIEVAL_DOCUMENT", "title": "..."}],
 "parameters": {"autoTruncate": true, "outputDimensionality": 768}}
```
```json
{"predictions": [{"embeddings": {"statistics": {"truncated": false, "token_count": 6}, "values": [0.01]}}],
 "metadata": {"billableCharacterCount": 12}}
```

**429 (Vertex PayGo).** The message text is documented. The body shape is the standard google.rpc shape, and we did not see it in Vertex docs:
```json
{"error": {"code": 429,
  "message": "Resource exhausted. Please try again later. Please refer to https://cloud.google.com/vertex-ai/generative-ai/docs/error-code-429 for more details.",
  "status": "RESOURCE_EXHAUSTED"}}
```
A hard quota hit gives this message: `"Quota exceeded for aiplatform.googleapis.com/global_embed_content_requests_per_minute_per_base_model with base model: gemini-embedding-2. Please submit a quota increase request. ..."`. A PT dedicated overage gives `"Too many requests. Exceeded the Provisioned Throughput."`. Vertex usually sends no `Retry-After` header and no `RetryInfo` detail. No source shows one.

**429 (Gemini API).** Forum posts show a `details` list. It contains `google.rpc.QuotaFailure` (`quotaMetric` such as `generativelanguage.googleapis.com/embed_content_paid_tier_requests`, `quotaId` such as `EmbedContentPerMinutePerProjectPerUserPerModel-PaidTier`) and `google.rpc.Help`. Our sources did not confirm `google.rpc.RetryInfo` (`retryDelay`) for embeddings.

**Other transient errors** (standard google.rpc bodies):
- `{"error":{"code":503,"message":"The service is currently unavailable.","status":"UNAVAILABLE"}}`
- `{"error":{"code":500,"message":"Internal error encountered.","status":"INTERNAL"}}`
- `504 DEADLINE_EXCEEDED`

**SDK retries.** The default is no retries: `retry_options=None` means 1 attempt. If you set `HttpRetryOptions`, the SDK retries 408/429/500/502/503/504 up to 5 attempts. The backoff is exponential with jitter, starts at 1 s, and stops at 60 s. The SDK does not read `Retry-After`.

## Latency

Google publishes no latency figures for embeddings. Our measurement: 0.30-0.33 s for each ~325-token call (from a laptop outside GCP). Profiles use 270 ms + 130 ms per 1k tokens, lognormal sigma 0.2. Inside GCP it is probably lower (GUESS). At 0.31 s and 1 input per request, a 60,000 RPM ceiling needs about 310 requests in flight.

## Sources

- https://docs.cloud.google.com/vertex-ai/generative-ai/docs/quotas
- https://docs.cloud.google.com/vertex-ai/generative-ai/docs/models/gemini/embedding-2
- https://docs.cloud.google.com/vertex-ai/generative-ai/docs/embeddings/get-text-embeddings
- https://docs.cloud.google.com/vertex-ai/generative-ai/docs/reference/rest/v1/projects.locations.publishers.models/embedContent
- https://docs.cloud.google.com/vertex-ai/generative-ai/docs/error-code-429
- https://docs.cloud.google.com/vertex-ai/generative-ai/docs/dynamic-shared-quota
- https://docs.cloud.google.com/vertex-ai/generative-ai/docs/provisioned-throughput/supported-models
- https://docs.cloud.google.com/vertex-ai/generative-ai/docs/start/express-mode/overview
- https://ai.google.dev/gemini-api/docs/rate-limits, https://ai.google.dev/gemini-api/docs/embeddings
- Forum reports (user-reported limits and 429 bodies): the URLs are in `profiles.json` `sources`.
