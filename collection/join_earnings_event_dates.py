#!/usr/bin/env python3
"""Write a date-enriched copy of a source transcript CSV without changing it."""

from __future__ import annotations

import argparse
import csv
import os
import sys
import tempfile
from pathlib import Path

from collection.study_period import validate_csv_event_dates_in_study_period, validate_csv_in_study_period


DATE_COLUMNS = ["event_date", "event_date_source", "event_date_status", "event_date_mapping_method"]


def configure_csv_field_size_limit() -> None:
    limit = sys.maxsize
    while True:
        try:
            csv.field_size_limit(limit)
            return
        except OverflowError:
            limit //= 10


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--mapping", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--include-tickers", help="comma-separated filter for a bounded validation output")
    args = parser.parse_args()
    configure_csv_field_size_limit()
    if args.input.resolve() == args.output.resolve():
        raise SystemExit("Refusing to overwrite --input")
    validate_csv_in_study_period(args.input, context="event-date join input")
    validate_csv_in_study_period(args.mapping, context="event-date mapping")
    validate_csv_event_dates_in_study_period(args.input, context="event-date join input")
    validate_csv_event_dates_in_study_period(args.mapping, context="event-date mapping")
    included = None
    if args.include_tickers:
        included = {ticker.strip().upper() for ticker in args.include_tickers.split(",") if ticker.strip()}
    mapping: dict[tuple[str, str], dict[str, str]] = {}
    with args.mapping.open(newline="", encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            key = ((row.get("ticker") or "").strip().upper(), (row.get("quarter_label") or "").strip().upper())
            if not all(key) or key in mapping:
                raise ValueError(f"Invalid or duplicate mapping key {key}")
            mapping[key] = row
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.input.open(newline="", encoding="utf-8") as source, tempfile.NamedTemporaryFile(
        "w", newline="", encoding="utf-8", dir=args.output.parent, delete=False
    ) as temporary:
        reader = csv.DictReader(source)
        source_fields = reader.fieldnames or []
        conflict = set(DATE_COLUMNS) & set(source_fields)
        if conflict:
            raise ValueError(f"Input already contains derived columns: {sorted(conflict)}")
        writer = csv.DictWriter(temporary, fieldnames=source_fields + DATE_COLUMNS)
        writer.writeheader()
        total = matched = 0
        for row in reader:
            if included is not None and (row.get("ticker") or "").strip().upper() not in included:
                continue
            total += 1
            key = ((row.get("ticker") or "").strip().upper(), (row.get("quarter_label") or "").strip().upper())
            date_row = mapping.get(key)
            if date_row is None:
                row.update({"event_date": "", "event_date_source": "", "event_date_status": "missing_mapping", "event_date_mapping_method": ""})
            else:
                matched += 1
                row.update({
                    "event_date": date_row.get("event_date", ""),
                    "event_date_source": date_row.get("event_date_source", ""),
                    "event_date_status": date_row.get("mapping_status", ""),
                    "event_date_mapping_method": date_row.get("mapping_method", ""),
                })
            writer.writerow(row)
        output_name = Path(temporary.name)
    os.replace(output_name, args.output)
    print(f"Wrote {args.output} ({total:,} rows; {matched:,} mapping-key matches)")


if __name__ == "__main__":
    main()
