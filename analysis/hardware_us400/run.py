"""Hardware-specific scoring, Carhart returns, and fractional chart entry point."""

from __future__ import annotations
import argparse
import csv
import gzip
import hashlib
import json
import math
import platform
import shutil
from collections import Counter
from datetime import date
from pathlib import Path
import numpy as np
import pandas as pd
from analysis.primary_event_study import core
from analysis.primary_event_study.run import Prices
from analysis.charts import fractional
from analysis.fractional_reproduction import PANELS, matrices
from analysis.fractional_covariance import pairwise_comparisons
from .inventory import ART, FINAL, OUT, read, payload_text
from .data import records


class HardwarePrices(Prices):
    def __init__(self):
        super().__init__()
        self.links.clear()
        path = ART / "security_history.csv"
        for row in read(path):
            self.links[row["ticker"]].append(row)
        self.mapping_hash = core.sha256(path)

    def for_call(self, row):
        lookup = dict(row)
        if row.get("price_ticker_override"):
            assert row.get("alias_identity_evidence")
            lookup["historical_ticker"] = row["price_ticker_override"]
            links = [
                x
                for x in self.links[lookup["historical_ticker"]]
                if x["cik"] == row["cik"]
            ]
            assert len({x["security_id"] for x in links}) == 1
            lookup["security_id"] = links[0]["security_id"]
        prices, meta = super().for_call(lookup)
        if row.get("price_ticker_override"):
            meta["price_mapping_method"] = (
                "documented issuer/name/ticker continuation; current provider adjusted history mapped to same historical CIK"
            )
            meta["price_alias_evidence"] = row["alias_identity_evidence"]
            meta["price_security_id"] = lookup["security_id"]
        symbol = lookup["historical_ticker"]
        if meta["market_data_status"] != "ok":
            requests = [
                r
                for r in records()
                if r["params"].get("function") == "TIME_SERIES_DAILY_ADJUSTED"
                and r["params"].get("symbol") == symbol
                and r["status"] == "ok"
            ]
            if requests:
                r = requests[-1]
                p = core.ROOT / r["raw_path"]
                assert core.sha256(p) == r["raw_sha256"]
                wrapper = json.loads(p.read_text())
                payload = wrapper.get("payload", wrapper)
                prices = {}
                for d, x in payload["Time Series (Daily)"].items():
                    v = float(x["5. adjusted close"])
                    if "2008-01-01" <= d <= "2021-01-01" and math.isfinite(v) and v > 0:
                        prices[date.fromisoformat(d)] = v
                meta.update(
                    market_data_status="ok" if prices else "no_prices_in_study_period",
                    price_source_path=r["raw_path"],
                    price_source_sha256=r["raw_sha256"],
                    price_retrieved_at_utc=r["fetched_at_utc"],
                )
                if prices:
                    meta.update(
                        price_first_date=min(prices).isoformat(),
                        price_last_date=max(prices).isoformat(),
                    )
        return prices, meta


def code_hashes():
    paths = list(Path(__file__).parent.glob("*.py")) + [
        Path(core.__file__),
        Path(fractional.__file__),
        core.ROOT / "analysis/fractional_covariance.py",
        core.ROOT / "analysis/fractional_reproduction.py",
        core.ROOT / "scoring/calculate_supply_chain_transcript_scores.py",
    ]
    return {core.relative(p): core.sha256(p) for p in paths}


def render(output, frame):
    if not len(frame):
        raise ValueError("No common eligible calls; cannot render portfolios")
    frame, thresholds = fractional.winsorize(frame.reset_index(drop=True))
    risk, joint, zero = fractional.fractional_assignments(frame)
    rw, zw, jw = matrices(frame, risk, joint)
    tables = fractional.fractional_tables(frame, risk, joint)
    core.write_csv(output / "winsorization_thresholds.csv", thresholds)
    core.write_csv(output / "zero_tie_audit.csv", zero)
    for data, name in [(risk, "scrisk_memberships"), (joint, "nested_memberships")]:
        data = data.copy()
        data["call_id"] = frame.loc[data.row_id, "call_id"].to_numpy()
        data["cik"] = frame.loc[data.row_id, "cik"].to_numpy()
        data.to_csv(output / f"{name}.csv.gz", index=False, float_format="%.17g")
    frame.to_csv(
        output / "eligible_winsorized_calls.csv.gz", index=False, float_format="%.17g"
    )
    comparisons = []
    for n, panel in enumerate(PANELS, 1):
        table = pd.DataFrame(tables[panel])
        w = jw if "heatmap" in panel else zw if "resolution" in panel else rw
        table["membership_rows"] = table.contributing_calls
        table["contributing_calls"] = (w > 0).sum(axis=0)
        table["fractional_mass"] = table.effective_n
        for f in ["mean", "se_firm_clustered", "ci_low", "ci_high"]:
            table[f + "_percent"] = table[f] * 100
        labels = (
            [f"S{s}R{r}" for s in range(1, 6) for r in range(1, 6)]
            if "heatmap" in panel
            else [f"Q{q}" for q in range(1, 6)]
        )
        var = "CAR_2_60_winsor" if "2_60" in panel else "CAR_0_1_winsor"
        if table.firms.min() >= 2:
            contrast, cov = pairwise_comparisons(
                frame[var].to_numpy(), w, frame.cik.to_numpy(), labels
            )
            np.testing.assert_allclose(
                np.sqrt(np.diag(cov)), table.se_firm_clustered, rtol=1e-12, atol=1e-14
            )
            contrast.insert(0, "panel", panel)
            comparisons.append(contrast)
            cov.to_csv(output / f"{n:02d}_{panel}_covariance.csv", float_format="%.17g")
        table.to_csv(output / f"{n:02d}_{panel}.csv", index=False, float_format="%.17g")
        tables[panel] = table.to_dict("records")
    if comparisons:
        pd.concat(comparisons, ignore_index=True).to_csv(
            output / "portfolio_comparisons.csv", index=False, float_format="%.17g"
        )
    fractional.PAGE_CACHE = output / "pages"
    pdf = output / "us_hardware_fractional_charts.pdf"
    fractional.render_pdf(
        pdf,
        tables,
        "US hardware portfolio | fiscal 2010-2019 | earnings-release events",
        f"US hardware: {len(frame):,} calls, {frame.cik.nunique():,} firms. Winsorization: hardware sample 1st/99th percentiles.",
        "Fractional ties within SIC divisions; nested Resolution sorts. Current-company screen; descriptive estimates.",
        True,
    )
    for n, panel in enumerate(PANELS, 1):
        shutil.copyfile(
            fractional.PAGE_CACHE / f"{pdf.stem}_page_{n}.png",
            output / f"{n:02d}_{panel}.png",
        )
    return {
        "eligible_calls": len(frame),
        "eligible_firms": int(frame.cik.nunique()),
        "risk_membership_rows": len(risk),
        "nested_membership_rows": len(joint),
        "per_call_weight_sum": 1,
        "quintile_mass": len(frame) / 5,
        "nested_cell_mass": len(frame) / 25,
        "allocation_checks_passed": True,
    }


def run(mode, input_path=None, output=None, pilot_dir=None):
    csv.field_size_limit(100_000_000)
    output = Path(output) if output else OUT / mode
    pilot_dir = Path(pilot_dir) if pilot_dir else OUT / "pilot"
    if output.exists():
        raise FileExistsError(f"Choose a new run; refusing to overwrite {output}")
    source = (
        Path(input_path)
        if input_path
        else FINAL
        / ("prepared_pilot_calls.csv" if mode == "pilot" else "prepared_calls.csv")
    )
    rows = read(source)
    from .release_dates import validate_decisions, apply_decision
    decision_rows = pd.read_csv(core.ROOT / "reproduction/hardware_baseline_v1/date_audit.csv.gz", dtype=str, keep_default_na=False).to_dict("records")
    decisions = validate_decisions(rows, decision_rows)
    rows = [apply_decision(r, decisions[r["call_id"]]) for r in rows]
    from .rebuild_audited import sic_history
    history = sic_history(core.ROOT)
    for r in rows:
        r.update(core.assign_sic(r, history))
    hashes = code_hashes()
    universe = {r["portfolio_cik"] for r in read(ART / "company_manifest.csv")}
    assert all(
        r["portfolio_cik"] in universe and "2010Q1" <= r["quarter_label"] <= "2019Q4"
        for r in rows
    )
    assert len({(r["portfolio_cik"], r["quarter_label"]) for r in rows}) == len(rows)
    assert core.sha256(core.SOURCE) == core.SOURCE_HASH
    weights, risk_terms, res_terms, dict_meta = core.load_dictionaries()
    indices = [
        core.scorer.build_phrase_index(x) for x in (weights, risk_terms, res_terms)
    ]
    old_path = (
        core.ROOT
        / "outputs/primary_event_study_2010_2019_release_dates_v1/full/call_level_scored_car.csv"
    )
    old = pd.read_csv(
        old_path,
        usecols=[
            "call_id",
            "SCRisk_raw",
            "Resolution_raw",
            "CAR_0_1",
            "CAR_2_60",
            "portfolio_eligible",
            "call_date",
        ],
        float_precision="round_trip",
    ).set_index("call_id")
    if mode == "pilot":
        ids = set()
        for year in range(2010, 2020):
            for nonzero in [False, True]:
                group = [
                    r
                    for r in rows
                    if r["call_id"] in old.index
                    and r["quarter_label"].startswith(str(year))
                    and bool(old.loc[r["call_id"], "SCRisk_raw"] > 0) == nonzero
                ]
                ids.update(
                    r["call_id"] for r in sorted(group, key=lambda x: x["call_id"])[:2]
                )
        for sym in ["MRVL", "GRMN", "AMD", "FORM", "INSG", "AOSL", "CAT", "DE", "ROK", "HUBB", "ONTO", "COHR", "ADTN", "BAX", "F", "BA", "WHR"]:
            ids.update(
                r["call_id"]
                for r in [r for r in rows if r["current_ticker"] == sym][:3]
            )
        ids.update(r["call_id"] for r in [x for x in rows if x["transcript_origin"] == "downloaded"][:12])
        rows = [r for r in rows if r["call_id"] in ids]
    else:
        pilot = json.loads((pilot_dir / "manifest.json").read_text())
        assert (pilot_dir / "INSPECTED.md").is_file() and pilot["validation_passed"]
        assert pilot["code_hashes"] == hashes, "Code changed since inspected pilot"
        assert pilot["dictionaries"] == dict_meta
    output.mkdir(parents=True)
    by_id = {r["call_id"]: r for r in rows}
    texts = {}
    with core.SOURCE.open() as f:
        for r in csv.DictReader(f):
            if r["call_id"] in by_id:
                texts[r["call_id"]] = r["transcript_text"]
    for r in rows:
        if r["call_id"] not in texts:
            p = core.ROOT / r["raw_path"]
            assert core.sha256(p) == r["raw_sha256"]
            wrapper = json.loads(p.read_text())
            texts[r["call_id"]] = payload_text(wrapper.get("payload", wrapper))
    validations = []
    with gzip.open(output / "match_audit.jsonl.gz", "wt") as audit:
        for i, r in enumerate(rows):
            text = texts[r["call_id"]]
            assert (
                hashlib.sha256(text.encode()).hexdigest()
                == r["canonical_transcript_sha256"]
            )
            scores, pairs = core.score_text(text, weights, indices, audit=True)
            r.update(scores)
            r["score_valid"] = (
                r["validation_status"] == "valid"
                and r["transcript_identity_period_status"] not in {"invalid_issuer_or_period", "unresolved_period"}
                and scores["transcript_word_count"] > 0
            )
            r["score_specification"] = (
                "exact_canonical_libraries_pair_sum_distance_le_10_population_sd_no_centering_v1"
            )
            if mode == "pilot":
                ref = core.scorer.calculate_raw_scores(
                    text,
                    weights,
                    risk_terms,
                    res_terms,
                    supply_chain_index=indices[0],
                    risk_index=indices[1],
                    resolution_index=indices[2],
                )
                assert math.isclose(
                    scores["SCRisk_weight_sum"],
                    ref.scrisk_weight_sum,
                    rel_tol=1e-13,
                    abs_tol=1e-13,
                )
                assert math.isclose(
                    scores["Resolution_weight_sum"],
                    ref.resolution_weight_sum,
                    rel_tol=1e-13,
                    abs_tol=1e-13,
                )
                assert scores["transcript_word_count"] == ref.word_count
            if r["call_id"] in old.index:
                for field in ["SCRisk_raw", "Resolution_raw"]:
                    np.testing.assert_allclose(
                        scores[field],
                        old.loc[r["call_id"], field],
                        rtol=1e-12,
                        atol=1e-15,
                    )
            validations.append(
                {
                    "call_id": r["call_id"],
                    "fresh_scoring": True,
                    "reference_scorer_checked": mode == "pilot",
                    "historical_score_parity": r["call_id"] in old.index,
                }
            )
            audit.write(
                json.dumps(
                    {
                        "call_id": r["call_id"],
                        "transcript_sha256": r["canonical_transcript_sha256"],
                        "pairs": pairs,
                    }
                )
                + "\n"
            )
            if (i + 1) % 1000 == 0:
                print("Freshly scored", i + 1, flush=True)
    population = [r["score_valid"] for r in rows]
    sds = {}
    for name in ["SCRisk", "Resolution"]:
        scaled, sd = core.scorer.normalize_raw_scores(
            [r[name + "_raw"] for r in rows], population
        )
        sds[name] = sd
        for r, x in zip(rows, scaled):
            r[name] = x
            r[name + "_sd"] = sd
            r["score_standardization_population"] = (
                mode + "_all_valid_hardware_calls_before_CAR_filter"
            )
    cal, factors, factor_meta = core.load_factors()
    prices = HardwarePrices()
    carparity = []
    sourceprices = {}
    with gzip.open(output / "event_day_audit.csv.gz", "wt", newline="") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=[
                "call_id",
                "event_day",
                "date",
                "stock_return",
                "expected_return",
                "abnormal_return",
            ],
        )
        writer.writeheader()
        for i, r in enumerate(rows):
            p, meta = prices.for_call(r)
            r.update(meta)
            sourceprices[r["historical_ticker"]] = meta
            result, daily = core.carhart(
                r.get("call_date", ""), p, cal, factors, audit=True
            )
            r.update(result)
            for d in daily:
                writer.writerow({"call_id": r["call_id"], **d})
            base = []
            if not r.get("call_date"):
                base.append("missing_release_date")
            if not r["score_valid"]:
                base.append("invalid_transcript")
            if r["market_data_status"] != "ok":
                base.append(r["market_data_status"])
            if r["price_identity_status"] != "matched_historical_ticker_cik_security":
                base.append(r["price_identity_status"])
            for w in ["0_1", "2_60"]:
                r[f"car_{w}_eligible"] = not base and r[f"car_{w}_status"] == "ok"
                if r[f"car_{w}_status"] == "ok":
                    assert r[f"car_{w}_observations"] == (2 if w == "0_1" else 59)
                    days = [d for d in daily if (d["event_day"] <= 1) == (w == "0_1")]
                    np.testing.assert_allclose(
                        sum(d["abnormal_return"] for d in days),
                        r[f"CAR_{w}"],
                        rtol=0,
                        atol=1e-14,
                    )
                    if r["call_id"] in old.index and r["call_date"] == old.loc[r["call_id"], "call_date"] and pd.notna(
                        old.loc[r["call_id"], f"CAR_{w}"]
                    ):
                        delta = r[f"CAR_{w}"] - old.loc[r["call_id"], f"CAR_{w}"]
                        np.testing.assert_allclose(delta, 0, rtol=0, atol=1e-12)
                        carparity.append(
                            {"call_id": r["call_id"], "window": w, "difference": delta}
                        )
            r["car_joint_eligible"] = r["car_0_1_eligible"] and r["car_2_60_eligible"]
            r["portfolio_eligible"] = (
                r["car_joint_eligible"]
                and r["sic_match_status"] == "matched_point_in_time"
            )
            r["portfolio_exclusion_reasons"] = ";".join(
                dict.fromkeys(
                    base
                    + [
                        r[f"car_{w}_status"]
                        for w in ["0_1", "2_60"]
                        if r[f"car_{w}_status"] != "ok"
                    ]
                    + (
                        []
                        if r["sic_match_status"] == "matched_point_in_time"
                        else [r["sic_match_status"]]
                    )
                )
            )
            if r["car_model_status"] == "ok":
                assert r["estimation_observations"] == 200 and r["estimation_rank"] == 5
            if r["sic_match_status"] == "matched_point_in_time":
                assert r["sic_filing_date"] <= r["sic_asof_date"]
            if (i + 1) % 1000 == 0:
                print("CAR recomputed", i + 1, flush=True)
    frame = pd.DataFrame(rows)
    frame.to_csv(
        output / "call_level_scored_car.csv", index=False, float_format="%.17g"
    )
    frame.loc[~frame.portfolio_eligible].to_csv(
        output / "excluded_calls.csv", index=False, float_format="%.17g"
    )
    core.write_csv(output / "scoring_validation.csv", validations)
    core.write_csv(output / "car_historical_parity.csv", carparity)
    core.write_csv(output / "market_data_sources.csv", sourceprices.values())
    core.write_json(
        output / "scaling.json",
        {
            "population": sum(population),
            "sd": sds,
            "ddof": 0,
            "centered": False,
            "before_car_filter": True,
        },
    )
    factor_frame = pd.DataFrame(factors, columns=["Mkt_RF", "SMB", "HML", "Mom", "RF"])
    factor_frame.insert(0, "date", cal)
    factor_frame.to_csv(output / "daily_factors.csv", index=False, float_format="%.17g")
    portfolio = render(output, frame.loc[frame.portfolio_eligible])
    gates = {
        k: int(frame[k].sum())
        for k in [
            "score_valid",
            "car_0_1_eligible",
            "car_2_60_eligible",
            "car_joint_eligible",
            "portfolio_eligible",
        ]
    }
    assert core.sha256(core.SOURCE) == core.SOURCE_HASH
    manifest = {
        "mode": mode,
        "source_rows": len(rows),
        "source_firms": int(frame.portfolio_cik.nunique()),
        "code_hashes": hashes,
        "dictionaries": dict_meta,
        "prepared_input_path": core.relative(source),
        "prepared_input_sha256": core.sha256(source),
        "factor_sources": factor_meta,
        "gates": gates,
        "portfolio": portfolio,
        "scoring": "fresh all calls; hardware population SD ddof=0 no centering before CAR filtering",
        "event_date_policy": "release, no after-hours shift",
        "environment": {
            "python": platform.python_version(),
            "numpy": np.__version__,
            "pandas": pd.__version__,
        },
        "validation_passed": True,
        "historical_car_comparisons": len(carparity),
        "original_frozen_source_unchanged": True,
        "transcript_origins": dict(Counter(r["transcript_origin"] for r in rows)),
        "output_hashes": {
            p.name: core.sha256(p) for p in output.iterdir() if p.is_file()
        },
    }
    core.write_json(output / "manifest.json", manifest)
    print(
        json.dumps({"mode": mode, "gates": gates, "portfolio": portfolio}, indent=2),
        flush=True,
    )


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("mode", choices=["pilot", "full"])
    p.add_argument("--input", type=Path)
    p.add_argument("--output", type=Path)
    p.add_argument("--pilot-dir", type=Path)
    a = p.parse_args()
    run(a.mode, a.input, a.output, a.pilot_dir)
