import json
import os
import io
import re
import time
import random
import boto3
from botocore.config import Config
from botocore.exceptions import ClientError
import psycopg2
import pdfplumber
from docx import Document
from pgvector.psycopg2 import register_vector

# ---------- AWS clients ----------
s3 = boto3.client("s3")
bedrock = boto3.client("bedrock-runtime")
secretsmanager = boto3.client("secretsmanager")
dynamodb = boto3.client("dynamodb")
cloudwatch = boto3.client("cloudwatch", config=Config(connect_timeout=2, read_timeout=2, retries={"max_attempts": 0}))

FUNCTION_NAME = os.environ.get("AWS_LAMBDA_FUNCTION_NAME", "s3-ingestion")
EMBEDDING_MODEL = os.environ.get("EMBEDDING_MODEL", "amazon.titan-embed-image-v1")
EMBEDDING_DIMENSIONS = int(os.environ.get("EMBEDDING_DIMENSIONS", "1024"))
REGION = os.environ["REGION"]
RDS_SECRET_ARN = os.environ["RDS_SECRET_ARN"]
DOCUMENTS_TABLE = os.environ["DOCUMENTS_TABLE"]

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

# ---------- Connection cache (survives warm invocations) ----------
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
    with _db_conn.cursor() as cur:
        cur.execute("CREATE EXTENSION IF NOT EXISTS vector;")
    _db_conn.autocommit = False
    register_vector(_db_conn)
    return _db_conn

def ensure_table():
    conn = get_db_connection()
    with conn.cursor() as cur:
        # EMBEDDING_DIMENSIONS must match the output size of EMBEDDING_MODEL.
        # Changing this after the table is created requires dropping and recreating the table
        # and re-ingesting all documents — vector(N) columns cannot be altered in place.
        cur.execute(f"""
            CREATE TABLE IF NOT EXISTS document_chunks (
                id          BIGSERIAL PRIMARY KEY,
                document_id TEXT         NOT NULL,
                chunk_id    TEXT         NOT NULL UNIQUE,
                content     TEXT         NOT NULL,
                embedding   vector({EMBEDDING_DIMENSIONS}) NOT NULL
            );
        """)
        cur.execute("""
            CREATE INDEX IF NOT EXISTS document_chunks_embedding_idx
            ON document_chunks
            USING ivfflat (embedding vector_cosine_ops)
            WITH (lists = 100);
        """)
        cur.execute("""
            CREATE INDEX IF NOT EXISTS document_chunks_document_id_idx
            ON document_chunks (document_id);
        """)
    conn.commit()
    print("Table and indexes ensured")

# ---------- Text extraction helpers ----------
def extract_pdf(file_bytes):
    text = ""
    with pdfplumber.open(io.BytesIO(file_bytes)) as pdf:
        for page in pdf.pages:
            page_text = page.extract_text()
            if page_text:
                text += page_text + "\n"
    return text

def extract_docx(file_bytes):
    doc = Document(io.BytesIO(file_bytes))
    return "\n".join(p.text for p in doc.paragraphs)

def extract_text(file_bytes, file_key):
    if file_key.endswith(".pdf"):
        return extract_pdf(file_bytes)
    elif file_key.endswith((".txt", ".md")):
        return file_bytes.decode("utf-8")
    elif file_key.endswith(".docx"):
        return extract_docx(file_bytes)
    else:
        raise ValueError("Unsupported file type")

def chunk_fixed_size(text, chunk_size=500, overlap=50):
    words = text.split()
    chunks = []
    start = 0
    while start < len(words):
        end = start + chunk_size
        chunk = " ".join(words[start:end])
        if len(chunk.strip()) > 200:
            chunks.append(chunk)
        start = end - overlap
    return chunks

def chunk_md_by_header(text, max_section_words=800):
    # Split on any ATX heading (# through ####). The heading line is kept at the
    # start of each section so the LLM sees the topic when the chunk is retrieved.
    sections = re.split(r'(?m)^(#{1,4}\s+.+)$', text)

    # re.split with a capturing group interleaves headings and bodies:
    # [preamble, heading1, body1, heading2, body2, ...]
    # Zip them back into (heading, body) pairs; treat any preamble as a headerless section.
    chunks = []
    preamble = sections[0].strip()
    if preamble:
        chunks.extend(chunk_fixed_size(preamble, chunk_size=200, overlap=40))

    pairs = zip(sections[1::2], sections[2::2])
    for heading, body in pairs:
        section = f"{heading.strip()}\n{body.strip()}"
        if len(section.split()) <= max_section_words:
            if len(section.strip()) > 200:
                chunks.append(section)
        else:
            # Section too large — split with overlap so heading context isn't lost
            chunks.extend(chunk_fixed_size(section, chunk_size=200, overlap=40))

    return chunks

def chunk_document(text, file_key):
    if file_key.endswith(".txt"):
        # Fixed-size with overlap: ~200 words, 20% overlap (40 words)
        return chunk_fixed_size(text, chunk_size=200, overlap=40)
    if file_key.endswith(".md"):
        # Header-based: each heading section is one chunk; oversized sections fall back to fixed-size
        return chunk_md_by_header(text)
    # Default for .pdf, .docx — unchanged until format-specific strategies are added
    return chunk_fixed_size(text)

_BEDROCK_RETRYABLE = {"ThrottlingException", "ServiceUnavailableException", "ModelTimeoutException"}

def create_embedding(text, max_retries=3):
    for attempt in range(max_retries + 1):
        try:
            t0 = time.monotonic()
            response = bedrock.invoke_model(
                modelId=EMBEDDING_MODEL,
                contentType="application/json",
                accept="application/json",
                body=json.dumps({"inputText": text})
            )
            embedding = json.loads(response["body"].read())["embedding"]
            _emit_bedrock_metric("EmbeddingLatency", (time.monotonic() - t0) * 1000)
            return embedding
        except ClientError as e:
            if e.response["Error"]["Code"] in _BEDROCK_RETRYABLE and attempt < max_retries:
                delay = min(2 ** attempt + random.uniform(0, 1), 30)
                print(f"Bedrock throttled, retrying in {delay:.1f}s (attempt {attempt + 1}/{max_retries})")
                time.sleep(delay)
            else:
                raise
    return None


def index_chunk(conn, document_id, chunk_id, chunk_text_content, embedding):
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO document_chunks (document_id, chunk_id, content, embedding)
            VALUES (%s, %s, %s, %s)
            ON CONFLICT (chunk_id) DO UPDATE
              SET content = EXCLUDED.content,
                  embedding = EXCLUDED.embedding;
            """,
            (document_id, chunk_id, chunk_text_content, embedding)
        )

# ---------- Cold-start initialization ----------
ensure_table()

# ---------- Lambda handler ----------
def _mark_document_failed(message, key):
    dynamodb.update_item(
        TableName=DOCUMENTS_TABLE,
        Key={
            "id": {"S": message["partitionKey"]},
            "file_key": {"S": key}
        },
        UpdateExpression="SET #s = :status",
        ExpressionAttributeNames={"#s": "status"},
        ExpressionAttributeValues={":status": {"S": "failed"}}
    )


def handler(event, context):
    sns_record = event["Records"][0]["Sns"]
    message = json.loads(sns_record["Message"])
    print(f"Received SNS message: {json.dumps(message)}")

    bucket = message["bucket"]
    key = message["fileKey"]
    print(f"Processing file: s3://{bucket}/{key}")

    try:
        _process(message, bucket, key)
    except ValueError as e:
        # Permanent failures: unsupported file type, text too short, corrupted file
        print(f"Permanent error processing {key}: {e}")
        _mark_document_failed(message, key)
        return {"statusCode": 400, "body": str(e)}
    except ClientError as e:
        if e.response["Error"]["Code"] == "NoSuchKey":
            print(f"File not found in S3: {key}")
            _mark_document_failed(message, key)
            return {"statusCode": 404, "body": f"File not found: {key}"}
        raise

    return {
        "statusCode": 200,
        "body": json.dumps({"document_id": key})
    }


def _process(message, bucket, key):
    response = s3.get_object(Bucket=bucket, Key=key)
    file_bytes = response["Body"].read()

    text = extract_text(file_bytes, key)
    if not text or len(text.strip()) < 100:
        raise ValueError("Extracted text is empty or too short")

    chunks = chunk_document(text, key)
    print(f"Created {len(chunks)} chunks")

    document_id = key
    conn = get_db_connection()

    try:
        for idx, chunk in enumerate(chunks):
            embedding = create_embedding(chunk)
            chunk_id = f"{document_id}-{idx}"
            index_chunk(conn, document_id, chunk_id, chunk, embedding)

        conn.commit()
    except Exception:
        global _db_conn
        try:
            conn.rollback()
        except Exception:
            pass
        _db_conn = None
        raise
    print("Document ingestion completed successfully")

    dynamodb.update_item(
        TableName=DOCUMENTS_TABLE,
        Key={
            "id": {"S": message["partitionKey"]},
            "file_key": {"S": key}
        },
        UpdateExpression="SET #s = :status",
        ExpressionAttributeNames={"#s": "status"},
        ExpressionAttributeValues={":status": {"S": "indexed"}}
    )