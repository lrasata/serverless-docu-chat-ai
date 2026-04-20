# Design Reference

This document contains the technical detail behind the design decisions summarized in [README.md](README.md). It is intended as a reference.

---

## Table of Contents

1. [Hybrid Search & RRF](#hybrid-search--rrf)
2. [Chunking Strategy — Rationale Per Format](#chunking-strategy--rationale-per-format)
3. [Agentic Loop — Implementation Detail](#agentic-loop--implementation-detail)
4. [Bedrock Configuration](#bedrock-configuration)
5. [Monitoring & Alarms](#monitoring--alarms)
6. [Scalability Limits](#scalability-limits)

---

## Hybrid Search & RRF

### Why two retrievers?

Each retriever has a fundamentally different failure mode. Running both and merging results is cheaper than trying to fix either retriever's weakness in isolation.

| Retriever                           | Mechanism                                                                                | Strong at                                                      | Weak at                                               |
|-------------------------------------|------------------------------------------------------------------------------------------|----------------------------------------------------------------|-------------------------------------------------------|
| **Semantic** (pgvector)             | Embeds the question into a vector; finds chunks with close vectors via cosine similarity | Conceptual questions, paraphrasing, synonyms                   | Exact terms, codes, IDs, version numbers              |
| **Lexical** (BM25 / PostgreSQL FTS) | Finds chunks containing the actual words from the question; ranks by term frequency      | Exact keyword matches — `EMP-1042`, `Clause 4.2.1`, `RFC 7519` | Synonyms — `"holiday"` will not find `"annual leave"` |

> Full-Text Search (FTS): PostgreSQL's built-in keyword search engine. It tokenizes text, stems words (e.g. "running" → "run"), and matches documents by exact or stemmed terms. It's the lexical side of your hybrid search, complementing pgvector's semantic side.

### Reciprocal Rank Fusion (RRF)

The two retrievers produce scores in completely different ranges (cosine similarity 0–1 vs. BM25 term-frequency scores). Averaging or weighting raw scores is unreliable.

RRF discards raw scores entirely and works on **rank position only**. Each chunk receives a score of `1 / (k + rank)` from each retriever, and the two scores are summed:

```
rrf_score = 1 / (60 + semantic_rank) + 1 / (60 + lexical_rank)
```

A chunk appearing in both ranked lists receives contributions from both. A chunk appearing in only one list receives half the score. The constant `k = 60` (from the original RRF paper) dampens the gap between adjacent ranks — rank 1 and rank 2 are close in score, preventing a single dominant result from burying everything else. This value requires no per-domain tuning.

**Example with `max_results = 5`:**

| Chunk                        | Semantic rank | Lexical rank | RRF score               |
|------------------------------|---------------|--------------|-------------------------|
| A — "Clause 4.2.1 states..." | #4            | #1           | 1/64 + 1/61 = **0.032** |
| B — thematically related     | #1            | not found    | 1/61 + 0 = 0.016        |
| C — contains the keyword     | not found     | #2           | 0 + 1/62 = 0.016        |

Chunk A wins because both retrievers agree it is relevant. Neither retriever alone would have surfaced it at the top.

### Threshold handling

`MIN_RELEVANCE_SCORE` (cosine similarity, default `0.4`) is applied as a `WHERE` pre-filter **semantic retrieval step**. This preserves the quality gate for vector search: completely unrelated chunks never enter the semantic ranked list. Lexical results are not pre-filtered meaning a chunk matching exact keywords is always worth surfacing regardless of its vector similarity score.

There is no post-fusion relevance threshold (RRF scores are on a different scale). If both retrievers return nothing (no vector match above threshold and no keyword match) the result set is empty and the LLM is called without context. The system prompt instructs it to say so rather than hallucinate.

### Design notes

| Trade-off                              | Detail                                                                                                                                                                                                                                                                                                                       |
|----------------------------------------|------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| **Language**                           | `to_tsvector('english', ...)` uses English stemming and stop words. Documents in other languages get degraded lexical retrieval. Fixable by adding a `language` column and parameterising the dictionary.                                                                                                                    |
| **RRF constant `k = 60`**              | Higher values reduce the score difference between ranks (flatter ranking). Lower values give more weight to top-ranked results. 60 is the standard default and works well across most retrieval tasks without tuning.                                                                                                        |

---

## Chunking Strategy — Rationale Per Format

The choice of chunking strategy directly determines retrieval quality. Poor chunking sends truncated or irrelevant context to the LLM regardless of model quality.

### `.txt` — Fixed-size with overlap

Plain text has no exploitable structure. Fixed-size chunks of ~200 words with 20% overlap (40 words) are used. The overlap ensures that a sentence split across a chunk boundary does not lose its context entirely.

### `.md` — Header-based hierarchical

Markdown heading sections (`#` through `####`) are each treated as one chunk. This preserves the natural atomic unit of a Markdown document — a Q&A entry, a step in a guide, a single topic. Splitting mid-section loses the relationship between a heading and its content. If a section exceeds 800 words it falls back to fixed-size (200-word) sub-chunks. If the file has no headings at all, the full text is treated as preamble and falls back to fixed-size chunking.

### `.pdf` — Section-aware with fallback

A regex detects numbered or named headings in the extracted text. Each detected section becomes one chunk, preserving policy clause or rule integrity — splitting a numbered clause mid-sentence produces incorrect answers. If a section exceeds 600 words or no headings are detected, it falls back to fixed-size (300 words, 60-word overlap).

**Silent failure modes for PDFs:**

- **Scanned PDFs** — pdfplumber extracts no text; the entire document silently produces zero chunks or falls back to fixed-size on garbled OCR output
- **Multi-column layouts** — pdfplumber reads left-to-right across the page, merging content from adjacent columns and breaking section boundaries
- **Image-based headings** — headings rendered as images are invisible to the text extractor; the section regex sees no structure

All three cases are logged to CloudWatch (`PDF: no sections detected, falling back to fixed-size chunking`) so the fallback rate is measurable in production.

### `.docx` — Fixed-size with overlap

Used as the general fallback for richly formatted documents where structure extraction is not yet implemented. ~500 words with 50-word overlap.

---

## Agentic Loop — Implementation Detail

### Tool definition structure

Every `converse` call includes a `toolConfig` with a list of tool definitions. Each tool has three fields the LLM reads to decide when and how to use it:

| Field         | Purpose                                                                                                |
|---------------|--------------------------------------------------------------------------------------------------------|
| `name`        | Identifier used in the `toolUse` response block                                                        |
| `description` | The primary signal — the LLM reads this to decide whether the tool is relevant to the current question |
| `inputSchema` | JSON schema defining required arguments — the LLM must conform to this when calling the tool           |

`toolChoice: auto` means the LLM decides freely whether to call a tool or answer directly. No routing logic exists on the application side.

### Tool implementation notes

Tools are defined in `tools.py` and registered via `TOOL_CONFIG` on every `converse` call. All tools take no input arguments — the LLM calls them by name and `execute_tool()` dispatches to the correct function. Swapping a mock for a real API only requires changing the function body; the loop, dispatcher, and tool definitions are unchanged.

### Multi-tool chaining example

**Question:** *"How many days until my next salary review, and do I have enough vacation left to take two weeks off before then?"*

```
Iteration 1 — converse()
  LLM decides it needs live data to answer
  → stopReason: "tool_use"
  → calls get_current_date()       returns { "today": "2025-04-18" }
  → calls get_my_payroll_info()    returns { "next_review_date": "2025-09-01", ... }
  → calls get_my_entitlements()    returns { "vacation_days_remaining": 14, ... }

Iteration 2 — converse(+ tool results)
  LLM now has all data needed
  → stopReason: "end_turn"
  → "Your next review is on 2025-09-01, which is 136 days away.
     You have 14 vacation days remaining — enough for two weeks off before then."
```

Three tool calls resolved in two loop iterations. The LLM performed the date arithmetic itself; the application only executed the tools and passed results back.

### Conversation history

The frontend maintains a rolling window of the last 10 messages (5 user/assistant turns) in React state and sends it with every request:

```
POST /api/chat
{
  "question": "How many days do I have left?",
  "history": [
    { "role": "user",      "content": "What is my salary band?" },
    { "role": "assistant", "content": "Your salary band is L4." }
  ]
}
```

The Lambda builds a new `messages` array with history turns first, followed by the current question. The window size is controlled by `HISTORY_WINDOW = 10` — older turns are silently dropped, keeping token usage predictable without any application-side truncation logic.

---

## Bedrock Configuration

All LLM and embedding settings are controlled via Terraform variables. Switching the active LLM is a variable change, not a code change — the Bedrock Converse API provides a unified interface across all models.

| Variable                              | Purpose                                                                                                                                                                 | Default                                 |
|---------------------------------------|-------------------------------------------------------------------------------------------------------------------------------------------------------------------------|-----------------------------------------|
| `embedding_model`                     | Bedrock model ID used to embed document chunks and questions. Must stay consistent for the lifetime of the vector store — changing it requires full re-ingestion.       | `amazon.titan-embed-image-v1`           |
| `bedrock_model_inference_profile_arn` | ARN of the Bedrock inference profile the Lambda calls at runtime. A cross-region profile routes across regions for availability. Changing this switches the active LLM. | —                                       |
| `bedrock_foundation_model_arns`       | Foundation model ARNs granted `bedrock:InvokeModel` in IAM. Needed because cross-region inference profiles route internally to underlying models.                       | `arn:aws:bedrock:*::foundation-model/*` |
| `llm_temperature`                     | Response randomness. `0.0` = deterministic, `1.0` = creative.                                                                                                           | `0.7`                                   |
| `llm_max_tokens`                      | Maximum tokens in the LLM response. Caps answer length and Bedrock cost.                                                                                                | `2000`                                  |
| `min_relevance_score`                 | Minimum cosine similarity score a chunk must reach to be included in the semantic retrieval step. Chunks below this threshold are discarded before the LLM call.        | `0.4`                                   |

### Why the LLM always responds even when no chunks pass the threshold

pgvector always returns results — it finds the *least dissimilar* vectors, not necessarily relevant ones. Without a threshold, low-quality chunks (e.g. a score of 0.2 on the query `"hello"`) would be silently passed to the LLM as if they were meaningful context, degrading answer quality and leaking unrelated document content.

When no chunks reach `min_relevance_score`, the LLM is still called but with an empty context. This lets it handle greetings, small talk, and out-of-scope questions naturally rather than returning a hard-coded error. Source citations are only shown when at least one chunk passes the threshold.

### Bedrock throttling risk on large documents

Bedrock enforces two limits on the Titan Embed model: tokens per minute (TPM) and requests per minute (RPM). A large document (e.g., a 100-page PDF producing hundreds of chunks) fires embedding calls in a tight loop and can exhaust both quotas quickly, especially outside `us-*` regions where default quotas are lower.

`create_embedding` retries up to three times on `ThrottlingException`, `ServiceUnavailableException`, and `ModelTimeoutException` using exponential backoff with jitter (`2^attempt + random(0–1s)`, capped at 30s). After all retries are exhausted the exception propagates, the Lambda retries the full invocation, and the event is routed to the DLQ if it still fails.

---

## Monitoring & Alarms

### API Gateway

| Metric      | Alarm threshold | Notes                                                       |
|-------------|-----------------|-------------------------------------------------------------|
| Latency p99 | > 10s           | RAG queries are slow — embedding + vector search + LLM call |
| 5XXError    | > 5 per minute  | Internal server failures                                    |
| 4XXError    | > 5 per minute  | Auth failures or malformed requests                         |

### RDS

| Metric              | Alarm threshold                             | Notes                                               |
|---------------------|---------------------------------------------|-----------------------------------------------------|
| DatabaseConnections | > 90                                        | ~80% of `max_connections` ≈ 112 for `db.t4g.micro`  |
| FreeStorageSpace    | < 2 GB                                      | Vector embeddings grow with every ingested document |
| CPUUtilization      | > 80% over two consecutive 5-minute periods | pgvector ANN searches are CPU-bound                 |

### Lambda (`s3_ingestion`, `query_document`)

| Metric                    | Alarm threshold | Notes                                     |
|---------------------------|-----------------|-------------------------------------------|
| Errors                    | > 5 per minute  | Per function                              |
| EmbeddingLatency (custom) | p99 > 3s        | Emitted to `DocuChatAI/Bedrock` namespace |
| LLMLatency (custom)       | p99 > 30s       | `query_document` only                     |

### Ingestion pipeline

| Metric    | Alarm threshold | Notes                                                                   |
|-----------|-----------------|-------------------------------------------------------------------------|
| DLQ depth | > 0             | Any message in the DLQ indicates a processing failure after all retries |

Custom metrics are emitted directly from Lambda code using `cloudwatch:PutMetricData`. Alarms use `treat_missing_data = notBreaching` so they stay green when the function is idle.

---

## Scalability Limits

The current architecture works well for demos and small-scale usage (PDFs up to ~20–30 pages, occasional uploads).

| Limit                                     | Detail                                                                                                                | Next step                                                                                    |
|-------------------------------------------|-----------------------------------------------------------------------------------------------------------------------|----------------------------------------------------------------------------------------------|
| **Lambda timeout on large documents**     | A 100-page PDF produces hundreds of chunks; embedding each one sequentially can exhaust the Lambda 15-minute timeout  | Queue-driven ingestion: SQS + workers or Step Functions for reliable, high-volume processing |
| **Bedrock TPM/RPM on concurrent uploads** | Multiple large uploads firing simultaneously exhaust Bedrock throttling quotas                                        | Throttle concurrency at the SQS consumer level; raise soft limits via AWS Support            |
| **RDS connection exhaustion**             | Each Lambda invocation opens a DB connection; high concurrency exhausts `max_connections` on `db.t4g.micro`           | RDS Proxy to pool connections; scale up instance class                                       |
| **pgvector search at scale**              | pgvector does not scale horizontally; at high vector volume query latency degrades                                    | Migrate to OpenSearch Serverless or Aurora PostgreSQL with pgvector                          |
| **No job tracking**                       | Ingestion retries are best-effort via DLQ; there is no visibility into whether a specific document was fully ingested | Add a `processing_status` field to the DynamoDB document metadata table                      |
