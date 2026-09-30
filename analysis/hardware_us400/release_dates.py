"""Evidence-bound fiscal-period/release mapping and explicit collision gates.

Quarter labels and date windows are diagnostics, never release-date evidence.
The decision table is authoritative for the reviewed hardware baseline.
"""
from __future__ import annotations

from collections import defaultdict
from datetime import date

ACCEPTED = {"verified_correction", "verified_existing", "screened_existing"}


def map_verified_periods(payload, periods):
    """Join exact, independently evidenced fiscal ends to provider releases.

    Annual year-end proximity is deliberately unsupported. Historical fiscal
    calendars may change, and provider annual rows can be retrospectively
    normalized to the current calendar. An ambiguous exact match stays open.
    """
    result = []
    for period in periods:
        required = ("quarter_label", "fiscal_period_end", "source_url", "evidence")
        if not all(period.get(k) for k in required):
            raise ValueError("Fiscal period requires explicit source evidence")
        end = date.fromisoformat(period["fiscal_period_end"])
        candidates = {
            r.get("reportedDate", "")
            for r in payload.get("quarterlyEarnings", [])
            if r.get("fiscalDateEnding") == end.isoformat()
        }
        candidates.discard("")
        if len(candidates) != 1:
            continue
        reported = candidates.pop()
        if date.fromisoformat(reported) < end:
            continue
        result.append({
            "quarter_label": period["quarter_label"],
            "fiscal_date_ending": end.isoformat(),
            "reported_date": reported,
            "period_source_url": period["source_url"],
            "period_evidence": period["evidence"],
            "match_method": "exact_evidenced_fiscal_period_end",
        })
    return result


def collision_groups(rows):
    groups = defaultdict(list)
    for row in rows:
        if row.get("release_date"):
            groups[(row["cik"], row["release_date"])].append(row["call_id"])
    return {key: ids for key, ids in groups.items() if len(ids) > 1}


def validate_decisions(rows, decisions):
    """Require one reviewed disposition per input and documented collisions."""
    by_id = {r["call_id"]: r for r in rows}
    selected = {r["call_id"]: r for r in decisions}
    if len(selected) != len(decisions) or set(selected) != set(by_id):
        raise ValueError("Date audit must cover each input call exactly once")
    for key, d in selected.items():
        original = by_id[key]
        if d["cik"] != original["cik"]:
            raise ValueError("Date evidence belongs to a different issuer")
        if d["provider_quarter_label"] != original.get("provider_quarter_label", original["quarter_label"]):
            raise ValueError("Date evidence belongs to a different provider call")
        if d["status"] in ACCEPTED:
            if not all(d.get(k) for k in ("fiscal_period_label", "fiscal_period_end", "release_date", "source_url", "evidence")):
                raise ValueError("Accepted mapping lacks explicit period/release evidence")
            if date.fromisoformat(d["release_date"]) < date.fromisoformat(d["fiscal_period_end"]):
                raise ValueError("Release predates its fiscal period end")
        elif d.get("release_date"):
            raise ValueError("Unresolved mappings must not supply an analysis event")
        if d["status"] not in ACCEPTED | {"unresolved"}:
            raise ValueError("Unknown audit disposition")
        if "duplicate_issuer_release" in d.get("audit_flags", "") and not (
            d.get("collision_adjudication") and d.get("collision_adjudication_url")
        ):
            raise ValueError("Original date collision lacks documented adjudication")
        if d.get("transcript_status") in {"invalid_issuer_or_period", "unresolved_period"} and d["status"] in ACCEPTED:
            raise ValueError("Unresolved transcript identity/period cannot receive an event")
    for _, ids in collision_groups(decisions).items():
        members = [selected[key] for key in ids]
        if not all(d.get("collision_adjudication_url") and d.get("collision_adjudication") for d in members):
            raise ValueError("Shared issuer/event date requires documented adjudication")
        if len({d["collision_adjudication"] for d in members}) != 1:
            raise ValueError("Collision decisions disagree")
    periods = defaultdict(list)
    issuers = defaultdict(list)
    for d in decisions:
        if d["status"] in ACCEPTED:
            periods[(d["cik"], d["fiscal_period_label"])].append(d)
            issuers[d["cik"]].append(d)
    if any(len(group) > 1 for group in periods.values()):
        raise ValueError("Multiple transcripts for one issuer fiscal period require separate adjudication")
    for group in issuers.values():
        ordered = sorted(group, key=lambda d: d["fiscal_period_end"])
        for earlier, later in zip(ordered, ordered[1:]):
            if earlier["release_date"] > later["release_date"]:
                raise ValueError("Release ordering conflicts with fiscal-period ordering")
    return selected


def apply_decision(row, decision):
    """Clear unsafe fields, keeping independently confirmed call dates separate."""
    row = dict(row)
    row["provider_quarter_label"] = decision["provider_quarter_label"]
    row["issuer_fiscal_period_label"] = decision.get("fiscal_period_label", "")
    row["date_audit_status"] = decision["status"]
    row["date_audit_flags"] = decision["audit_flags"]
    row["date_audit_evidence"] = decision["evidence"]
    row["date_audit_source_url"] = decision["source_url"]
    row["transcript_identity_period_status"] = decision["transcript_status"]
    accepted = decision["status"] in ACCEPTED
    release = decision["release_date"] if accepted else ""
    row.update(earnings_call_date=release, reported_earnings_date=release,
               call_date=release, event_date_policy="release",
               event_date_source_field="earnings_call_date",
               date_fiscal_date_ending=decision.get("fiscal_period_end", ""),
               date_status=decision["status"], date_source_url=decision["source_url"],
               date_match_method="audited_issuer_fiscal_period_release_evidence",
               call_date_source_url=decision["source_url"])
    # A new source must never inherit a hash/evidence snippet for an old quarter.
    row["date_response_sha256"] = decision.get("source_sha256", "")
    row["call_date_source_sha256"] = decision.get("source_sha256", "")
    row["date_evidence_snippet"] = decision["evidence"]
    row["call_date_evidence"] = decision["evidence"]
    row["date_source_agreement"] = decision["status"]
    if decision["status"] != "screened_existing":
        # Old call-date evidence can refer to the misassigned quarter. Revalidation
        # is separate from this earnings-release-date audit.
        for key in list(row):
            if key == "confirmed_call_date" or key.startswith("confirmed_call_date_"):
                row[key] = ""
        row["call_date_confirmation_status"] = "not_revalidated_in_release_date_audit"
        row["release_date_differs_from_confirmed_call"] = False
    return row
