"""Shared extraction and tokenization. Every filing, cached or newly downloaded,
goes through exactly this code so the two collection paths cannot diverge."""
from __future__ import annotations

import gzip
import hashlib
import html as htmllib
import re

DOC_BLOCK = re.compile(rb"<DOCUMENT>(.*?)</DOCUMENT>", re.S)
DOC_TYPE = re.compile(rb"<TYPE>([^\r\n<]*)")
DOC_TEXT = re.compile(rb"<TEXT>(.*?)</TEXT>", re.S)
PERIOD = re.compile(rb"CONFORMED PERIOD OF REPORT:\s*(\d{8})")
PRIMARY_TYPES = {"10-K", "10-K405"}

# Inline XBRL hides a large machine-readable block inside the visible document.
# Left in, it contributes tens of thousands of junk tokens per modern filing.
IX_HEADER = re.compile(r"<ix:header\b.*?</ix:header>", re.S | re.I)
HIDDEN_DIV = re.compile(r'<div[^>]*style="[^"]*display:\s*none[^"]*"[^>]*>.*?</div>', re.S | re.I)
SCRIPT_STYLE = re.compile(r"<(script|style)\b.*?</\1>", re.S | re.I)
TAG = re.compile(r"<[^>]+>")

# Hyphens and soft separators are JOINED, not split: the paper's Table 2 shows
# 'workinprocess', 'slowmoving', 'eprocurement', 'endcustomers', 'supplychain'.
JOIN_CHARS = re.compile(r"[‐-―\-­/']")
WORD = re.compile(r"[a-z]+")


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def find_primary_document(payload: bytes) -> tuple[bytes | None, str | None]:
    """Return (document bytes, its TYPE) for the first 10-K / 10-K405 document."""
    for m in DOC_BLOCK.finditer(payload):
        block = m.group(1)
        t = DOC_TYPE.search(block)
        doc_type = t.group(1).decode("latin-1").strip() if t else ""
        if doc_type in PRIMARY_TYPES:
            body = DOC_TEXT.search(block)
            return (body.group(1) if body else block), doc_type
    return None, None


def conformed_period(payload: bytes) -> str | None:
    m = PERIOD.search(payload[:200_000])
    return m.group(1).decode() if m else None


def document_to_text(doc: bytes) -> str:
    raw = doc.decode("utf-8", errors="replace")
    if re.search(r"<(html|body|div|table|p)\b", raw[:20_000], re.I):
        raw = IX_HEADER.sub(" ", raw)
        raw = HIDDEN_DIV.sub(" ", raw)
        raw = SCRIPT_STYLE.sub(" ", raw)
        raw = TAG.sub(" ", raw)
    raw = htmllib.unescape(raw)
    return re.sub(r"\s+", " ", raw).strip()


def tokenize(text: str) -> list[str]:
    """Lowercase, join hyphenated forms, drop numbers and punctuation.

    Stopwords are KEPT: removing them would collapse the co-occurrence windows
    that both word2vec and PPMI are defined over.
    """
    text = JOIN_CHARS.sub("", text.lower())
    return WORD.findall(text)


def write_gz(path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with gzip.open(tmp, "wb", compresslevel=6) as fh:
        fh.write(data)
    tmp.replace(path)


def read_gz(path) -> bytes:
    with gzip.open(path, "rb") as fh:
        return fh.read()
