"""Stage 3: retrieve and parse the 50,000 selected filings.

Download years stream the submission and abort the connection once the primary
10-K/10-K405 document closes, so exhibits and XBRL sidecars are never pulled.
Cached years (2001-2004) read the submission already on disk. Both paths then run
the identical extraction in filing_text.py.

Resumable: rerunning skips accessions already recorded in manifest.jsonl.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).parent))
import filing_text as ft

END_DOC = re.compile(rb"</DOCUMENT>")


class RateLimiter:
    def __init__(self, rps: float) -> None:
        self._interval = 1.0 / rps
        self._lock = threading.Lock()
        self._next = time.monotonic()

    def wait(self) -> None:
        with self._lock:
            now = time.monotonic()
            if self._next < now:
                self._next = now
            delay = self._next - now
            self._next += self._interval
        if delay > 0:
            time.sleep(delay)

    def penalise(self, seconds: float) -> None:
        """Push the shared schedule back so every worker backs off, not just this one."""
        with self._lock:
            self._next = max(self._next, time.monotonic() + seconds)


RETRY_STATUS = {403, 429, 500, 502, 503, 504}


def _get_once(session, url, limiter, max_bytes, want, attempts=6):
    """One streamed GET, retrying throttles with exponential backoff.

    Without this, a 429 raised immediately, the worker moved straight to the next
    URL, and the effective request rate went UP during throttling, which is how
    the first run lost ~4,000 filings across 2010-2013.
    """
    for attempt in range(attempts):
        limiter.wait()
        try:
            with session.get(url, stream=True, timeout=180) as r:
                if r.status_code in RETRY_STATUS:
                    wait = float(r.headers.get("Retry-After") or 0) or min(2 ** attempt, 60)
                    limiter.penalise(wait)
                    time.sleep(wait)
                    continue
                r.raise_for_status()
                buf = bytearray()
                streamed = 0
                for chunk in r.iter_content(262144):
                    buf += chunk
                    streamed += len(chunk)
                    if streamed > max_bytes or len(END_DOC.findall(buf)) >= want:
                        break
                return bytes(buf), streamed
        except requests.exceptions.RequestException:
            if attempt == attempts - 1:
                raise
            time.sleep(min(2 ** attempt, 60))
    raise requests.exceptions.RetryError(f"exhausted retries: {url}")


def stream_primary(session, url, limiter, max_bytes, max_docs=6):
    """Stream until the Nth </DOCUMENT>, then abort. Returns (payload, bytes_streamed)."""
    want = 1
    while True:
        payload, streamed = _get_once(session, url, limiter, max_bytes, want)
        doc, doc_type = ft.find_primary_document(payload)
        if doc is not None or want >= max_docs or streamed > max_bytes:
            return payload, streamed
        want += 1  # primary was not sequence 1; read one more document


def process(rec, session, limiter, raw_dir, text_dir, max_bytes):
    out = {
        "accession": rec["accession"], "cik": rec["cik"], "company": rec["company"],
        "form": rec["form"], "filed": rec["filed"], "filed_year": rec["filed_year"],
        "url": rec["url"], "source": rec["source"],
    }
    try:
        if rec["source"] == "cached":
            payload = Path(rec["cached_path"]).read_bytes()
            out["http_status"] = None
            out["bytes_streamed"] = len(payload)
        else:
            payload, streamed = stream_primary(session, rec["url"], limiter, max_bytes)
            out["http_status"] = 200
            out["bytes_streamed"] = streamed
    except Exception as exc:
        out["parser_status"] = "download_failed"
        out["error"] = f"{type(exc).__name__}: {exc}"[:300]
        return out

    out["conformed_period"] = ft.conformed_period(payload)
    doc, doc_type = ft.find_primary_document(payload)
    if doc is None:
        out["parser_status"] = "no_primary_document"
        out["document_type"] = None
        return out

    out["document_type"] = doc_type
    out["bytes_primary_document"] = len(doc)
    out["sha256_primary_document"] = ft.sha256(doc)

    text = ft.document_to_text(doc)
    tokens = ft.tokenize(text)
    out["text_chars"] = len(text)
    out["token_count"] = len(tokens)
    out["parser_status"] = "ok" if len(tokens) >= 500 else "too_few_tokens"

    ft.write_gz(raw_dir / rec["cik"] / f"{rec['accession']}.primary.gz", doc)
    ft.write_gz(text_dir / rec["cik"] / f"{rec['accession']}.txt.gz", " ".join(tokens).encode())
    return out


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--sample", type=Path, required=True)
    p.add_argument("--raw-dir", type=Path, required=True)
    p.add_argument("--text-dir", type=Path, required=True)
    p.add_argument("--manifest", type=Path, required=True)
    p.add_argument("--user-agent", required=True)
    p.add_argument("--rps", type=float, default=8.0)
    p.add_argument("--workers", type=int, default=8)
    p.add_argument("--max-bytes", type=int, default=60_000_000)
    p.add_argument("--only-source", choices=["cached", "download"])
    p.add_argument("--limit", type=int)
    a = p.parse_args()

    records = [json.loads(l) for l in a.sample.open()]
    if a.only_source:
        records = [r for r in records if r["source"] == a.only_source]

    done = set()
    if a.manifest.exists():
        for line in a.manifest.open():
            try:
                r = json.loads(line)
            except json.JSONDecodeError:
                continue
            if r.get("parser_status") not in (None, "download_failed"):
                done.add(r["accession"])
    todo = [r for r in records if r["accession"] not in done]
    if a.limit:
        todo = todo[: a.limit]
    print(f"records={len(records):,} already_done={len(done):,} todo={len(todo):,}", flush=True)

    session = requests.Session()
    session.headers.update({"User-Agent": a.user_agent, "Accept-Encoding": "gzip, deflate"})
    adapter = requests.adapters.HTTPAdapter(pool_connections=a.workers * 2, pool_maxsize=a.workers * 2)
    session.mount("https://", adapter)
    limiter = RateLimiter(a.rps)

    a.manifest.parent.mkdir(parents=True, exist_ok=True)
    lock = threading.Lock()
    t0 = time.time()
    counts = {"ok": 0, "fail": 0, "bytes": 0}

    with a.manifest.open("a") as fh, ThreadPoolExecutor(a.workers) as pool:
        for i, out in enumerate(pool.map(
            lambda r: process(r, session, limiter, a.raw_dir, a.text_dir, a.max_bytes), todo), 1):
            with lock:
                fh.write(json.dumps(out) + "\n")
                if i % 200 == 0:
                    fh.flush()
                counts["ok" if out.get("parser_status") == "ok" else "fail"] += 1
                counts["bytes"] += out.get("bytes_streamed", 0) or 0
            if i % 500 == 0:
                el = time.time() - t0
                print(f"{i:>6,}/{len(todo):,}  ok={counts['ok']:,} other={counts['fail']:,}  "
                      f"{counts['bytes']/1e9:.1f}GB  {i/el:.1f}/s  eta {(len(todo)-i)/(i/el)/60:.0f}m",
                      flush=True)
    print(f"DONE ok={counts['ok']:,} other={counts['fail']:,} bytes={counts['bytes']/1e9:.1f}GB "
          f"elapsed={(time.time()-t0)/60:.1f}m", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
