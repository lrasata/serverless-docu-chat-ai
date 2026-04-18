import json
import os
import time
import boto3
from botocore.config import Config
import psycopg2
from pgvector.psycopg2 import register_vector
from tools import TOOL_CONFIG, execute_tool

# ---------- Environment variables ----------
REGION = os.environ["REGION"]
RDS_SECRET_ARN = os.environ["RDS_SECRET_ARN"]
DOCUMENTS_TABLE = os.environ["DOCUMENTS_TABLE"]
BEDROCK_MODEL_INFERENCE_PROFILE_ARN = os.environ["BEDROCK_MODEL_INFERENCE_PROFILE_ARN"]
MAX_RESULTS = int(os.environ.get("MAX_SEARCH_RESULTS", "5"))
BEDROCK_GUARDRAIL_ID = os.environ["BEDROCK_GUARDRAIL_ID"]
BEDROCK_GUARDRAIL_VERSION = os.environ.get("BEDROCK_GUARDRAIL_VERSION", "1")
TEMPERATURE=float(os.environ.get("TEMPERATURE", "0.7"))
MAX_TOKENS=int(os.environ.get("LLM_MAX_TOKENS", "2000"))
EMBEDDING_MODEL=os.environ.get("EMBEDDING_MODEL", "amazon.titan-embed-image-v1")
MIN_RELEVANCE_SCORE=float(os.environ.get("MIN_RELEVANCE_SCORE", "0.4"))

# ---------- AWS clients ----------
bedrock_runtime = boto3.client("bedrock-runtime", region_name=REGION)
dynamodb = boto3.client("dynamodb", region_name=REGION)
secretsmanager = boto3.client("secretsmanager")
cloudwatch = boto3.client("cloudwatch", config=Config(connect_timeout=2, read_timeout=2, retries={"max_attempts": 0}))

FUNCTION_NAME = os.environ.get("AWS_LAMBDA_FUNCTION_NAME", "query-document")

def _emit_bedrock_metric(metric_name, value_ms):
    try:
        cloudwatch.put_metric_data(
            Namespace="DocuChatAI/Bedrock",
            MetricData=[{
                "MetricName": metric_name,
                "Dimensions": [{"Name": "FunctionName", "Value": FUNCTION_NAME}],
                "Value": value_ms,
                "Unit": "Milliseconds",
            }]
        )
    except Exception as e:
        print(f"Failed to emit metric {metric_name}: {e}")

# ---------- Connection cache ----------
_db_conn = None

def get_db_credentials():
    response = secretsmanager.get_secret_value(SecretId=RDS_SECRET_ARN)
    return json.loads(response["SecretString"])

def get_db_connection():
    global _db_conn
    try:
        if _db_conn is not None:
            _db_conn.cursor().execute("SELECT 1")
            return _db_conn
    except Exception:
        _db_conn = None

    creds = get_db_credentials()
    _db_conn = psycopg2.connect(
        host=creds["host"],
        port=creds["port"],
        dbname=creds["dbname"],
        user=creds["username"],
        password=creds["password"],
        connect_timeout=5,
        sslmode="require",
    )
    _db_conn.autocommit = True
    register_vector(_db_conn)
    return _db_conn

# ---------- Helper functions ----------
def create_embedding(text):
    try:
        t0 = time.monotonic()
        response = bedrock_runtime.invoke_model(
            modelId=EMBEDDING_MODEL,
            contentType="application/json",
            accept="application/json",
            body=json.dumps({"inputText": text})
        )
        body = json.loads(response["body"].read())
        _emit_bedrock_metric("EmbeddingLatency", (time.monotonic() - t0) * 1000)
        return body["embedding"]
    except Exception as e:
        print(f"Error creating embedding: {str(e)}")
        raise

RRF_K = 60  # RRF constant: higher value = smaller score gap between adjacent ranks.
            # 60 is the standard default from the original RRF paper.

def search_similar_chunks(question_embedding, question_text, user_id, document_id=None, max_results=MAX_RESULTS):
    """Hybrid search: combines semantic (pgvector cosine) and lexical (BM25/FTS) retrieval
    via Reciprocal Rank Fusion. Each retriever produces a ranked list; each chunk gets
    1/(RRF_K + rank) from each list; scores are summed. Chunks appearing in both lists
    are naturally promoted. Neither scorer's raw scale affects the other.

    Semantic pre-filter: only chunks with cosine similarity >= MIN_RELEVANCE_SCORE enter
    the semantic CTE, preserving the same quality gate as before. Lexical results are not
    pre-filtered — a chunk matching exact keywords is always relevant regardless of its
    vector similarity.
    """
    try:
        conn = get_db_connection()
        scope = "document_id = %s" if document_id else "document_id LIKE %s"
        scope_val = document_id if document_id else f"uploads/users/{user_id}/%"

        with conn.cursor() as cur:
            cur.execute(
                f"""
                WITH semantic AS (
                    -- Vector similarity search. Filters by MIN_RELEVANCE_SCORE so only
                    -- meaningfully similar chunks enter the fusion step.
                    SELECT chunk_id,
                           ROW_NUMBER() OVER (ORDER BY embedding <=> %s::vector) AS sem_rank
                    FROM document_chunks
                    WHERE {scope}
                      AND 1 - (embedding <=> %s::vector) >= %s
                    LIMIT %s
                ),
                lexical AS (
                    -- Full-text search using PostgreSQL's built-in BM25-style ranking
                    -- (ts_rank_cd). The fts column is a pre-computed tsvector generated
                    -- from content — no ingestion change needed.
                    SELECT chunk_id,
                           ROW_NUMBER() OVER (ORDER BY ts_rank_cd(fts, query) DESC) AS lex_rank
                    FROM document_chunks,
                         plainto_tsquery('english', %s) AS query
                    WHERE {scope}
                      AND fts @@ query
                    LIMIT %s
                ),
                fused AS (
                    -- Reciprocal Rank Fusion: score = 1/(k+rank_semantic) + 1/(k+rank_lexical).
                    -- FULL OUTER JOIN ensures chunks from either retriever are included.
                    -- COALESCE(..., 0) gives 0 for the missing retriever leg.
                    SELECT
                        COALESCE(s.chunk_id, l.chunk_id) AS chunk_id,
                        COALESCE(1.0 / (%s + s.sem_rank), 0) +
                        COALESCE(1.0 / (%s + l.lex_rank), 0) AS rrf_score
                    FROM semantic s
                    FULL OUTER JOIN lexical l USING (chunk_id)
                )
                SELECT dc.document_id, dc.chunk_id, dc.content, f.rrf_score
                FROM fused f
                JOIN document_chunks dc USING (chunk_id)
                ORDER BY f.rrf_score DESC
                LIMIT %s;
                """,
                (
                    question_embedding, scope_val, question_embedding, MIN_RELEVANCE_SCORE, max_results,
                    question_text, scope_val, max_results,
                    RRF_K, RRF_K,
                    max_results,
                )
            )
            rows = cur.fetchall()

        sem_count = sum(1 for r in rows if r[3] > 1.0 / (RRF_K + max_results))
        print(f"Hybrid search returned {len(rows)} chunks (est. semantic contributions: {sem_count})")
        return [
            {"document_id": r[0], "chunk_id": r[1], "text": r[2], "score": float(r[3])}
            for r in rows
        ]
    except Exception as e:
        print(f"Error in hybrid search: {str(e)}")
        raise

MAX_TOOL_ITERATIONS = 5

def run_agentic_loop(question, context_chunks, history=None, model_id=BEDROCK_MODEL_INFERENCE_PROFILE_ARN):
    context = "\n\n".join([f"[Chunk {i+1}]\n{chunk['text']}" for i, chunk in enumerate(context_chunks)])

    # Prepend conversation history so the model can refer back to previous turns
    messages = []
    for turn in (history or []):
        messages.append({"role": turn["role"], "content": [{"text": turn["content"]}]})
    messages.append({"role": "user", "content": [{"text": f"Context:\n{context}\n\nQuestion: {question}"}]})
    converse_kwargs = {
        "modelId": model_id,
        "system": [{"text": (
            "You are a helpful AI assistant. Answer questions using the provided document context "
            "and the tools available to you. Use tools whenever live data (dates, entitlements, "
            "payroll) is needed to give a complete answer. "
            "If the answer cannot be found in the context or via tools, say so."
        )}],
        "toolConfig": TOOL_CONFIG,
        "inferenceConfig": {"maxTokens": MAX_TOKENS, "temperature": TEMPERATURE},
    }
    if BEDROCK_GUARDRAIL_ID:
        converse_kwargs["guardrailConfig"] = {
            "guardrailIdentifier": BEDROCK_GUARDRAIL_ID,
            "guardrailVersion": BEDROCK_GUARDRAIL_VERSION,
        }

    try:
        for iteration in range(MAX_TOOL_ITERATIONS):
            t0 = time.monotonic()
            response = bedrock_runtime.converse(**converse_kwargs, messages=messages)
            _emit_bedrock_metric("LLMLatency", (time.monotonic() - t0) * 1000)

            stop_reason = response["stopReason"]
            assistant_message = response["output"]["message"]
            messages.append(assistant_message)
            print(f"Iteration {iteration + 1}: stopReason={stop_reason}")

            if stop_reason == "end_turn":
                return next(
                    block["text"]
                    for block in assistant_message["content"]
                    if "text" in block
                )

            if stop_reason == "tool_use":
                tool_results = []
                for block in assistant_message["content"]:
                    if "toolUse" not in block:
                        continue
                    tool_use = block["toolUse"]
                    result = execute_tool(tool_use["name"], tool_use.get("input", {}))
                    tool_results.append({
                        "toolResult": {
                            "toolUseId": tool_use["toolUseId"],
                            "content": [{"json": result}],
                        }
                    })
                messages.append({"role": "user", "content": tool_results})

        raise RuntimeError(f"Agentic loop did not terminate after {MAX_TOOL_ITERATIONS} iterations")

    except Exception as e:
        print(f"Error in agentic loop: {str(e)}")
        raise

# ---------- Lambda handler ----------
def handler(event, context):
    try:
        if "body" in event:
            body = json.loads(event["body"]) if isinstance(event["body"], str) else event["body"]
        else:
            body = event

        question = body.get("question", "").strip()
        document_id = body.get("documentId")
        history = body.get("history", [])

        if not question:
            return {
                "statusCode": 400,
                "headers": {"Content-Type": "application/json"},
                "body": json.dumps({"error": "Question is required"})
            }

        user_id = None
        if "requestContext" in event and "authorizer" in event["requestContext"]:
            authorizer = event["requestContext"]["authorizer"]
            claims = authorizer.get("jwt", {}).get("claims") or authorizer.get("claims", {})
            user_id = claims.get("sub")

        print(f"Processing question: {question}, document_id: {document_id}, user_id: {user_id}")

        question_embedding = create_embedding(question)
        # Hybrid search: MIN_RELEVANCE_SCORE is applied inside the semantic CTE as a
        # pre-filter. The returned score is an RRF score (not cosine similarity),
        # so no second threshold filter is applied here — an empty result means both
        # retrievers found nothing, and the LLM is still called without context.
        relevant_chunks = search_similar_chunks(question_embedding, question, user_id, document_id)
        print(f"Hybrid search: {len(relevant_chunks)} chunks passed to LLM")

        if not relevant_chunks:
            print("No chunks retrieved by either retriever — calling LLM without document context")

        answer = run_agentic_loop(question, relevant_chunks, history=history)

        sources = []
        for chunk in relevant_chunks[:3]:
            sources.append({
                "documentId": chunk["document_id"],
                "chunkId": chunk["chunk_id"],
                "relevanceScore": round(chunk["score"], 3),
                "preview": chunk["text"][:200] + "..." if len(chunk["text"]) > 200 else chunk["text"]
            })

        return {
            "statusCode": 200,
            "headers": {"Content-Type": "application/json"},
            "body": json.dumps({"answer": answer, "sources": sources, "question": question})
        }

    except Exception as e:
        print(f"Error in handler: {str(e)}")
        import traceback
        traceback.print_exc()
        return {
            "statusCode": 500,
            "headers": {"Content-Type": "application/json"},
            "body": json.dumps({"error": "Internal server error", "message": str(e)})
        }