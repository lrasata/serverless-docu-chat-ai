import re


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
    # re.split with a capturing group interleaves headings and bodies:
    # [preamble, heading1, body1, heading2, body2, ...]
    sections = re.split(r'(?m)^(#{1,4}\s+.+)$', text)

    chunks = []
    preamble = sections[0].strip()
    if preamble:
        chunks.extend(chunk_fixed_size(preamble, chunk_size=200, overlap=40))

    for heading, body in zip(sections[1::2], sections[2::2]):
        section = f"{heading.strip()}\n{body.strip()}"
        if len(section.split()) <= max_section_words:
            if len(section.strip()) > 200:
                chunks.append(section)
        else:
            # Section too large — split with overlap so heading context isn't lost
            chunks.extend(chunk_fixed_size(section, chunk_size=200, overlap=40))

    return chunks


_PDF_SECTION_RE = re.compile(
    r'(?m)^('
    r'\d+(\.\d+)*[.)]\s+[A-Z].+'           # numbered: 1.  2.1.  3.2)
    r'|(?:Article|Section|Chapter)\s+\w+.+' # Article 5 / Section IV / Chapter One
    r'|[A-Z][A-Z\s]{4,50}'                  # short all-caps lines: SCOPE, DEFINITIONS
    r')$'
)


def chunk_pdf_by_section(text, max_section_words=600):
    matches = list(_PDF_SECTION_RE.finditer(text))

    if not matches:
        print("PDF: no sections detected, falling back to fixed-size chunking")
        return chunk_fixed_size(text)

    print(f"PDF: {len(matches)} sections detected")
    chunks = []

    preamble = text[:matches[0].start()].strip()
    if preamble:
        chunks.extend(chunk_fixed_size(preamble, chunk_size=300, overlap=60))

    for i, match in enumerate(matches):
        section_start = match.start()
        section_end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        section = text[section_start:section_end].strip()
        word_count = len(section.split())

        if word_count > max_section_words:
            print(f"PDF: section {i + 1} oversized ({word_count} words), splitting further")
            chunks.extend(chunk_fixed_size(section, chunk_size=300, overlap=60))
        elif len(section) > 200:
            chunks.append(section)

    return chunks


def chunk_document(text, file_key):
    if file_key.endswith(".txt"):
        return chunk_fixed_size(text, chunk_size=200, overlap=40)
    if file_key.endswith(".md"):
        return chunk_md_by_header(text)
    if file_key.endswith(".pdf"):
        return chunk_pdf_by_section(text)
    # Default for .docx
    return chunk_fixed_size(text)
