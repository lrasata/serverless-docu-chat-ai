import json
import os
import time
import boto3
from botocore.config import Config
import psycopg2
from pgvector.psycopg2 import register_vector

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
MIN_RELEVANCE_SCORE=float(os.environ.get("MIN_RELEVANCE_SCORE", "0.6"))

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

def search_similar_chunks(question_embedding, user_id, document_id=None, max_results=MAX_RESULTS):
    try:
        conn = get_db_connection()
        with conn.cursor() as cur:
            # The <=> operator is pgvector's cosine distance. ORDER BY embedding <=> vector → sorts by closest first (lowest distance)
            if document_id:
                cur.execute(
                    """
                    SELECT document_id, chunk_id, content,
                           1 - (embedding <=> %s::vector) AS score
                    FROM document_chunks
                    WHERE document_id = %s
                    ORDER BY embedding <=> %s::vector
                    LIMIT %s;
                    """,
                    (question_embedding, document_id, question_embedding, max_results)
                )
            else:
                cur.execute(
                    """
                    SELECT document_id, chunk_id, content,
                           1 - (embedding <=> %s::vector) AS score
                    FROM document_chunks
                    WHERE document_id LIKE %s
                    ORDER BY embedding <=> %s::vector
                    LIMIT %s;
                    """,
                    (question_embedding, f"uploads/users/{user_id}/%", question_embedding, max_results)
                )
            rows = cur.fetchall()

        return [
            {"document_id": r[0], "chunk_id": r[1], "text": r[2], "score": float(r[3])}
            for r in rows
        ]
    except Exception as e:
        print(f"Error searching pgvector: {str(e)}")
        raise

def generate_answer_with_bedrock(question, context_chunks, model_id=BEDROCK_MODEL_INFERENCE_PROFILE_ARN):
    try:
        context = "\n\n".join([f"[Chunk {i+1}]\n{chunk['text']}" for i, chunk in enumerate(context_chunks)])
        converse_kwargs = {
            "modelId": model_id,
            "system": [{"text": (
                "You are a helpful AI assistant that answers questions based on the provided document context. "
                "Only use information from the context below to answer the question. "
                "If the answer cannot be found in the context, say so."
            )}],
            "messages": [{"role": "user", "content": [{"text": f"Context:\n{context}\n\nQuestion: {question}"}]}],
            "inferenceConfig": {
                "maxTokens": MAX_TOKENS,
                "temperature": TEMPERATURE,
            },
        }
        if BEDROCK_GUARDRAIL_ID:
            converse_kwargs["guardrailConfig"] = {
                "guardrailIdentifier": BEDROCK_GUARDRAIL_ID,
                "guardrailVersion": BEDROCK_GUARDRAIL_VERSION,
            }

        t0 = time.monotonic()
        response = bedrock_runtime.converse(**converse_kwargs)
        _emit_bedrock_metric("LLMLatency", (time.monotonic() - t0) * 1000)
        return response["output"]["message"]["content"][0]["text"]
    except Exception as e:
        print(f"Error calling Bedrock: {str(e)}")
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
        chunks = search_similar_chunks(question_embedding, user_id, document_id)
        relevant_chunks = [c for c in chunks if c["score"] >= MIN_RELEVANCE_SCORE]
        print(f"Chunks retrieved: {len(chunks)}, above threshold ({MIN_RELEVANCE_SCORE}): {len(relevant_chunks)}")

        if not relevant_chunks:
            return {
                "statusCode": 200,
                "headers": {"Content-Type": "application/json"},
                "body": json.dumps({
                    "answer": "I couldn't find any relevant information in the uploaded documents to answer your question.",
                    "sources": []
                })
            }

        print(f"Found {len(relevant_chunks)} relevant chunks")
        answer = generate_answer_with_bedrock(question, relevant_chunks)

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