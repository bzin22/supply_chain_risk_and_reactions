#!/usr/bin/env python3
"""Build a supply-chain term library from historical SEC 10-K filings.

The downloader uses one process-wide leaky-bucket limiter for every SEC
request, including retries.  The default is deliberately the SEC maximum of
10 request starts per second, as requested.
"""

from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
import gzip
import html
import json
import os
import re
import sys
import threading
import time
from dataclasses import asdict, dataclass
from datetime import date
from html.parser import HTMLParser
from pathlib import Path
from typing import Iterable
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


SEEDS = [
    "channel partners",
    "customers",
    "demand management",
    "distribution",
    "fulfillment",
    "inventory",
    "logistics",
    "manufacturing",
    "procurement",
    "purchasing",
    "sourcing",
    "suppliers",
    "supply",
    "supply chain",
    "transportation",
    "warehousing",
]

WORD_RE = re.compile(r"[a-z]{3,}")
FIELD_RE = re.compile(r"^<([A-Z]+)>(.*)$", re.MULTILINE)
DOC_RE = re.compile(r"<DOCUMENT>(.*?)</DOCUMENT>", re.IGNORECASE | re.DOTALL)
TEXT_RE = re.compile(r"<TEXT>(.*?)</TEXT>", re.IGNORECASE | re.DOTALL)
TYPE_RE = re.compile(r"<TYPE>\s*([^\r\n]+)", re.IGNORECASE)
FILENAME_RE = re.compile(r"<FILENAME>\s*([^\r\n]+)", re.IGNORECASE)

STOPWORDS = {
    "about", "above", "after", "again", "against", "almost", "also", "among",
    "and", "any", "are", "because", "been", "being", "below", "between", "both",
    "but", "can", "could", "did", "does", "doing", "during", "each", "few", "for",
    "from", "further", "had", "has", "have", "having", "here", "how", "into", "its",
    "itself", "more", "most", "other", "our", "ours", "out", "over", "same", "should",
    "some", "such", "than", "that", "their", "theirs", "them", "then", "there", "these",
    "they", "this", "those", "through", "too", "under", "until", "very", "was", "were",
    "what", "when", "where", "which", "while", "who", "whom", "why", "will", "with",
    "would", "you", "your", "yours", "able", "could", "may", "might", "must", "shall",
    "herein", "thereof", "therein", "wherein", "pursuant", " thereto", "hereby",
}


@dataclass(frozen=True)
class Filing:
    cik: str
    company: str
    form: str
    filed: str
    filename: str

    @property
    def accession(self) -> str:
        name = Path(self.filename).name
        return name.removesuffix(".txt")

    @property
    def raw_path_part(self) -> str:
        return f"{self.cik}/{self.accession}.txt"


class RateLimiter:
    """Process-wide leaky bucket, limiting request starts to max_rps."""

    def __init__(self, max_rps: float = 10.0) -> None:
        if max_rps <= 0:
            raise ValueError("max_rps must be positive")
        # Add a small guard against clock granularity and inclusive sliding
        # window boundaries turning an exact 10.0 interval into 11 starts.
        self.interval = (1.0 / max_rps) + 0.001
        self._lock = threading.Lock()
        self._next_start = 0.0
        self.total_requests = 0
        self.max_observed_rps = 0.0
        self._starts: list[float] = []

    def wait(self) -> None:
        with self._lock:
            now = time.monotonic()
            start = max(now, self._next_start)
            self._next_start = start + self.interval
            delay = start - now
            if delay:
                time.sleep(delay)
            observed = time.monotonic()
            self.total_requests += 1
            self._starts.append(observed)
            cutoff = observed - 1.0
            while self._starts and self._starts[0] < cutoff:
                self._starts.pop(0)
            self.max_observed_rps = max(self.max_observed_rps, len(self._starts))


class SECClient:
    def __init__(self, user_agent: str, max_rps: float = 10.0, retries: int = 5) -> None:
        if not user_agent or "@" not in user_agent:
            raise ValueError(
                "SEC_USER_AGENT must identify the application and include a contact email"
            )
        self.user_agent = user_agent
        self.limiter = RateLimiter(max_rps)
        self.retries = retries
        self.status_counts: dict[str, int] = {}
        self._status_lock = threading.Lock()

    def _count_status(self, status: str) -> None:
        with self._status_lock:
            self.status_counts[status] = self.status_counts.get(status, 0) + 1

    def get(self, url: str) -> bytes | None:
        for attempt in range(self.retries + 1):
            self.limiter.wait()
            request = Request(
                url,
                headers={
                    "User-Agent": self.user_agent,
                    "Host": "www.sec.gov",
                },
            )
            try:
                with urlopen(request, timeout=90) as response:
                    status = str(response.status)
                    self._count_status(status)
                    body = response.read()
                    if response.headers.get("Content-Encoding", "").lower() == "gzip":
                        body = gzip.decompress(body)
                    return body
            except HTTPError as exc:
                status = str(exc.code)
                self._count_status(status)
                if exc.code == 404:
                    return None
                if exc.code not in {403, 429, 500, 502, 503, 504} or attempt == self.retries:
                    print(f"request failed ({exc.code}): {url}", file=sys.stderr)
                    return None
                retry_after = exc.headers.get("Retry-After")
                try:
                    delay = float(retry_after) if retry_after else 2**attempt
                except ValueError:
                    delay = 2**attempt
                time.sleep(min(delay, 60.0))
            except (URLError, TimeoutError, OSError) as exc:
                self._count_status("network_error")
                if attempt == self.retries:
                    print(f"request failed ({exc}): {url}", file=sys.stderr)
                    return None
                time.sleep(min(2**attempt, 60.0))
        return None


class VisibleTextParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self.skip_depth = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag.lower() in {"script", "style", "head", "ix:header"}:
            self.skip_depth += 1

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() in {"script", "style", "head", "ix:header"} and self.skip_depth:
            self.skip_depth -= 1

    def handle_data(self, data: str) -> None:
        if not self.skip_depth:
            self.parts.append(data)


def visible_text(payload: str) -> str:
    if re.search(r"<html|<body|<table|<div", payload[:10000], re.IGNORECASE):
        parser = VisibleTextParser()
        parser.feed(payload)
        payload = " ".join(parser.parts)
    payload = html.unescape(payload)
    return re.sub(r"\s+", " ", payload).strip()


def extract_primary_10k(payload: bytes) -> str:
    text = payload.decode("utf-8", errors="replace")
    blocks = DOC_RE.findall(text)
    for block in blocks:
        type_match = TYPE_RE.search(block)
        if not type_match or type_match.group(1).strip().upper() != "10-K":
            continue
        body_match = TEXT_RE.search(block)
        body = body_match.group(1) if body_match else block
        return visible_text(body)
    return visible_text(text)


def tokenize(text: str) -> list[str]:
    return [token for token in WORD_RE.findall(text.lower()) if token not in STOPWORDS]


def quarter_range(start_year: int, end_year: int) -> Iterable[tuple[int, int]]:
    for year in range(start_year, end_year + 1):
        for quarter in range(1, 5):
            yield year, quarter


def parse_index(payload: bytes, start: date, end: date) -> list[Filing]:
    result: list[Filing] = []
    text = payload.decode("latin-1", errors="replace")
    for line in text.splitlines():
        if not line or line.startswith("CIK|") or line.startswith("---"):
            continue
        fields = line.split("|")
        if len(fields) != 5:
            continue
        cik, company, form, filed, filename = fields
        if form != "10-K":
            continue
        try:
            filed_date = date.fromisoformat(filed)
        except ValueError:
            continue
        if start <= filed_date <= end:
            result.append(Filing(cik.zfill(10), company, form, filed, filename))
    return result


def discover_filings(client: SECClient, start_year: int, end_year: int, max_filings: int | None) -> list[Filing]:
    start = date(start_year, 1, 1)
    end = date(end_year, 12, 31)
    filings: dict[str, Filing] = {}
    for year, quarter in quarter_range(start_year, end_year):
        url = f"https://www.sec.gov/Archives/edgar/full-index/{year}/QTR{quarter}/master.idx"
        payload = client.get(url)
        if payload is None:
            continue
        for filing in parse_index(payload, start, end):
            filings[filing.accession] = filing
        print(f"discovered {len(filings):,} unique 10-K filings through {year} Q{quarter}", flush=True)
        if max_filings and len(filings) >= max_filings:
            break
    ordered = sorted(filings.values(), key=lambda item: (item.filed, item.accession))
    return ordered[:max_filings] if max_filings else ordered


def atomic_write(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_bytes(data)
    temporary.replace(path)


def download_filings(client: SECClient, filings: list[Filing], output: Path, workers: int) -> list[dict]:
    raw_root = output / "raw"
    manifest_path = output / "filings.jsonl"
    records: list[dict] = []
    existing: dict[str, dict] = {}
    if manifest_path.exists():
        for line in manifest_path.read_text().splitlines():
            try:
                record = json.loads(line)
                existing[record["accession"]] = record
            except (json.JSONDecodeError, KeyError):
                continue

    results: dict[str, dict] = {}
    pending: list[Filing] = []
    for filing in filings:
        destination = raw_root / filing.raw_path_part
        if destination.exists():
            if filing.accession in existing:
                results[filing.accession] = existing[filing.accession]
            else:
                results[filing.accession] = asdict(filing) | {
                    "accession": filing.accession,
                    "url": f"https://www.sec.gov/Archives/{filing.filename}",
                    "status": "reused",
                    "bytes": destination.stat().st_size,
                }
        else:
            pending.append(filing)

    def download_one(filing: Filing) -> dict:
        destination = raw_root / filing.raw_path_part
        url = f"https://www.sec.gov/Archives/{filing.filename}"
        payload = client.get(url)
        record = asdict(filing) | {"accession": filing.accession, "url": url}
        if payload is None:
            record["status"] = "download_failed"
        else:
            atomic_write(destination, payload)
            record["status"] = "downloaded"
            record["bytes"] = len(payload)
        return record

    completed = len(results)
    with manifest_path.open("a") as manifest:
        with ThreadPoolExecutor(max_workers=max(1, workers)) as executor:
            for offset in range(0, len(pending), 500):
                batch = pending[offset:offset + 500]
                futures = [executor.submit(download_one, filing) for filing in batch]
                for future in as_completed(futures):
                    record = future.result()
                    results[record["accession"]] = record
                    manifest.write(json.dumps(record) + "\n")
                    completed += 1
                    if completed % 100 == 0:
                        manifest.flush()
                        print(f"downloaded or reused {completed:,}/{len(filings):,} filings", flush=True)
    return [results[filing.accession] for filing in filings]


def build_token_corpus(records: list[dict], output: Path) -> tuple[Path, int, int]:
    corpus_path = output / "tokenized_corpus.txt"
    documents = 0
    tokens = 0
    with corpus_path.open("w") as corpus:
        for record in records:
            if record.get("status") not in {"downloaded", "reused"}:
                continue
            raw_path = output / "raw" / f"{record['cik']}/{record['accession']}.txt"
            if not raw_path.exists():
                continue
            words = tokenize(extract_primary_10k(raw_path.read_bytes()))
            if len(words) < 20:
                continue
            corpus.write(" ".join(words) + "\n")
            documents += 1
            tokens += len(words)
    return corpus_path, documents, tokens


def train_and_rank(
    corpus_path: Path,
    output: Path,
    min_count: int,
    vector_size: int,
    epochs: int,
    embedding_workers: int,
) -> dict:
    try:
        import numpy as np
        from gensim.models import Word2Vec
    except ImportError as exc:
        raise RuntimeError(
            "Embedding stage requires gensim and numpy; install requirements.txt"
        ) from exc

    class LineCorpus:
        def __iter__(self):
            with corpus_path.open() as source:
                for line in source:
                    words = line.split()
                    if words:
                        yield words

    model = Word2Vec(
        sentences=LineCorpus(),
        vector_size=vector_size,
        window=5,
        min_count=min_count,
        workers=max(1, embedding_workers),
        sg=1,
        negative=10,
        epochs=epochs,
        seed=13,
    )
    model.save(str(output / "word2vec.model"))

    words = model.wv.index_to_key
    vectors = model.wv.vectors.astype("float32")
    vectors /= np.maximum(np.linalg.norm(vectors, axis=1, keepdims=True), 1e-12)
    candidate_mask = np.array([bool(WORD_RE.fullmatch(word)) and word not in STOPWORDS for word in words])
    seed_rows: dict[str, list[dict]] = {}
    final: dict[str, dict] = {}

    for seed in SEEDS:
        parts = [part for part in seed.split() if part in model.wv]
        if not parts:
            seed_rows[seed] = []
            continue
        seed_vector = np.mean([model.wv[part] for part in parts], axis=0)
        seed_vector = seed_vector / max(float(np.linalg.norm(seed_vector)), 1e-12)
        scores = vectors @ seed_vector
        order = np.argsort(-scores)
        rows: list[dict] = []
        for row_index in order:
            term = words[int(row_index)]
            if not candidate_mask[row_index] or term in parts:
                continue
            row = {
                "term": term,
                "seed": seed,
                "seed_rank": len(rows) + 1,
                "cosine": round(float(scores[row_index]), 8),
                "count": int(model.wv.get_vecattr(term, "count")),
            }
            rows.append(row)
            prior = final.get(term)
            if prior is None or row["cosine"] > prior["max_cosine"]:
                final[term] = {
                    "term": term,
                    "max_cosine": row["cosine"],
                    "best_seed": seed,
                    "count": row["count"],
                    "matches": [row],
                }
            else:
                prior["matches"].append(row)
            if len(rows) == 100:
                break
        seed_rows[seed] = rows

    # Add the single-word seeds explicitly; multiword seeds are intentionally absent.
    single_word_seeds = [seed for seed in SEEDS if " " not in seed and seed in model.wv]
    for term in single_word_seeds:
        final.setdefault(term, {
            "term": term,
            "max_cosine": 1.0,
            "best_seed": term,
            "count": int(model.wv.get_vecattr(term, "count")),
            "matches": [],
        })

    ranked = sorted(final.values(), key=lambda row: (-row["max_cosine"], row["term"]))
    (output / "terms.txt").write_text("\n".join(row["term"] for row in ranked) + "\n")
    with (output / "terms.jsonl").open("w") as destination:
        for row in ranked:
            destination.write(json.dumps(row) + "\n")
    (output / "per_seed.json").write_text(json.dumps(seed_rows, indent=2) + "\n")
    return {
        "vocabulary_size": len(words),
        "min_count": min_count,
        "vector_size": vector_size,
        "epochs": epochs,
        "embedding_workers": max(1, embedding_workers),
        "preliminary_candidates": sum(len(rows) for rows in seed_rows.values()),
        "final_library_size": len(ranked),
        "single_word_seeds_added": single_word_seeds,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=Path("artifacts/sec_10k_supply_chain"))
    parser.add_argument("--start-year", type=int, default=2001)
    parser.add_argument("--end-year", type=int, default=date.today().year)
    parser.add_argument("--max-filings", type=int, default=None, help="small validation run; omit for full corpus")
    parser.add_argument("--min-count", type=int, default=25)
    parser.add_argument("--vector-size", type=int, default=200)
    parser.add_argument("--epochs", type=int, default=5)
    parser.add_argument("--embedding-workers", type=int, default=8)
    parser.add_argument("--max-rps", type=float, default=10.0)
    parser.add_argument("--workers", type=int, default=12)
    parser.add_argument("--refresh-discovery", action="store_true")
    parser.add_argument(
        "--from-manifest",
        action="store_true",
        help="build from already recorded downloaded filings without contacting SEC",
    )
    parser.add_argument("--user-agent", default=os.environ.get("SEC_USER_AGENT"))
    args = parser.parse_args()

    if args.end_year < args.start_year:
        parser.error("--end-year must be >= --start-year")
    try:
        client = SECClient(args.user_agent or "", max_rps=args.max_rps)
    except ValueError as exc:
        parser.error(str(exc))

    args.output.mkdir(parents=True, exist_ok=True)
    manifest_path = args.output / "filings.jsonl"
    if args.from_manifest:
        if not manifest_path.exists():
            parser.error(f"manifest does not exist: {manifest_path}")
        manifest_rows = [json.loads(line) for line in manifest_path.read_text().splitlines() if line.strip()]
        filings = []
        for row in manifest_rows:
            destination = args.output / "raw" / f"{row['cik']}/{row['accession']}.txt"
            if row.get("status") in {"downloaded", "reused"} and destination.exists():
                filings.append(Filing(row["cik"], row["company"], row["form"], row["filed"], row["filename"]))
        print(f"using {len(filings):,} recorded downloaded filings from {manifest_path}", flush=True)
    else:
        discovery_path = args.output / "discovered_filings.json"
        if discovery_path.exists() and not args.refresh_discovery and not args.max_filings:
            filings = [Filing(**row) for row in json.loads(discovery_path.read_text())]
            print(f"reusing {len(filings):,} discovered filings from {discovery_path}", flush=True)
        else:
            filings = discover_filings(client, args.start_year, args.end_year, args.max_filings)
            discovery_path.write_text(json.dumps([asdict(filing) for filing in filings], indent=2) + "\n")
    records = download_filings(client, filings, args.output, args.workers)
    corpus_path, documents, tokens = build_token_corpus(records, args.output)
    if documents == 0:
        raise RuntimeError("No filings were successfully tokenized; refusing to train an empty model")
    ranking = train_and_rank(
        corpus_path,
        args.output,
        args.min_count,
        args.vector_size,
        args.epochs,
        args.embedding_workers,
    )
    summary = {
        "seeds": SEEDS,
        "start_year": args.start_year,
        "end_year": args.end_year,
        "filings_discovered": len(filings),
        "filings_downloaded_or_reused": sum(record.get("status") in {"downloaded", "reused"} for record in records),
        "documents_tokenized": documents,
        "tokens_tokenized": tokens,
        "requests": client.limiter.total_requests,
        "max_observed_requests_in_one_second": client.limiter.max_observed_rps,
        "http_status_counts": client.status_counts,
        **ranking,
    }
    (args.output / "summary.json").write_text(json.dumps(summary, indent=2) + "\n")
    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
