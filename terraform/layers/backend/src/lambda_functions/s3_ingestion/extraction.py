import io

import pdfplumber
from docx import Document


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
