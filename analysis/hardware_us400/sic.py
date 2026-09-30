"""Reuse historical filing headers and evidenced issuer continuity for SIC."""

import re
from collections import defaultdict
from .inventory import ART, read
from analysis.primary_event_study import core
from analysis.primary_event_study.prepare import CACHE

AVGO_EVIDENCE = [
    "https://investors.broadcom.com/news-releases/news-release-details/broadcom-completes-redomiciliation-united-states-0",
    "https://www.globenewswire.com/news-release/2016/12/08/896283/19933/en/Broadcom-Limited-Announces-Fourth-Quarter-and-Fiscal-Year-2016-Financial-Results-and-Interim-Dividend.html",
]


def history():
    companies = read(ART / "company_manifest.csv")
    ciks = {r["historical_cik"] for r in companies} | {"0001441634", "0001649338"}
    h = defaultdict(list)
    for r in read(CACHE / "sic_history.csv"):
        if r["cik"] in ciks:
            h[r["cik"]].append(r)
    added = []
    roots = [
        core.ROOT / "artifacts" / x / "raw"
        for x in [
            "sec_10k_supply_chain",
            "sec_10k_supply_chain_pilot",
            "sec_10k_supply_chain_pilot_strict",
            "sec_10k_supply_chain_pilot_concurrent",
        ]
    ]
    known = {(r["cik"], r["accession"]) for rows in h.values() for r in rows}
    for root in roots:
        for cik in sorted(ciks):
            for p in sorted((root / cik).glob("*.txt")):
                with p.open(errors="replace") as f:
                    head = f.read(50000).split("</SEC-HEADER>")[0]
                ci = re.search(r"CENTRAL INDEX KEY:\s*(\d+)", head)
                si = re.search(
                    r"STANDARD INDUSTRIAL CLASSIFICATION:[^\n]*\[(\d{4})\]", head
                )
                fd = re.search(r"FILED AS OF DATE:\s*(\d{8})", head)
                if not (ci and si and fd) or ci[1].zfill(10) != cik:
                    continue
                if (cik, p.stem) in known:
                    continue
                d = fd[1]
                r = {
                    "cik": cik,
                    "sic": si[1],
                    "filing_date": f"{d[:4]}-{d[4:6]}-{d[6:]}",
                    "accession": p.stem,
                    "source_path": core.relative(p),
                    "source_sha256": core.sha256(p),
                    "source_url": f"https://www.sec.gov/Archives/edgar/data/{int(cik)}/{p.stem}.txt",
                }
                h[cik].append(r)
                added.append(r)
                known.add((cik, p.stem))
    # One continuing AVGO issuer chain. Do not substitute BRCM's distinct pre-merger
    # business/security (CIK 1054374), which is not the AVGO price series.
    chain = []
    for cik, lo, hi in [
        ("0001441634", "0000-01-01", "2016-01-31"),
        ("0001649338", "2016-02-01", "2018-04-03"),
        ("0001730168", "2018-04-04", "9999-12-31"),
    ]:
        chain.extend(r for r in h[cik] if lo <= r["filing_date"] <= hi)
    h["0001730168"] = chain
    core.write_csv(ART / "supplemental_sic_history.csv", added)
    core.write_json(
        ART / "sic_continuity.json",
        {
            "AVGO": {
                "issuer_chain": ["0001441634", "0001649338", "0001730168"],
                "evidence": AVGO_EVIDENCE,
                "rule": "same continuing AVGO shareholder/security chain; retain latest public filing by fiscal end; no BRCM standalone predecessor substitution",
            }
        },
    )
    return h


def assign(row, h):
    result = core.assign_sic(row, h)
    if result["sic_match_status"] == "matched_point_in_time":
        selected = [
            r
            for r in h[row["cik"]]
            if r["accession"] == result["sic_accession"]
            and r["source_path"] == result["sic_source_path"]
        ]
        assert selected
        result["sic_evidence_issuer_cik"] = selected[0]["cik"]
        result["sic_continuity_evidence"] = (
            ";".join(AVGO_EVIDENCE) if selected[0]["cik"] != row["cik"] else ""
        )
    return result
