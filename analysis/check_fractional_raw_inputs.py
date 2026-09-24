"""Read-only availability/hash check for the private raw-pipeline inputs."""
import argparse
import json
from pathlib import Path

from analysis.charts.fractional import ROOT, sha256
from analysis.fractional_reproduction import PACKAGE


def check(root):
    rows = json.loads((PACKAGE / "raw_inputs.json").read_text())
    result = []
    for row in rows:
        path = root / row["path"]
        status = "missing" if not path.is_file() else "ok" if sha256(path) == row["sha256"] else "hash_mismatch"
        result.append({**row, "status": status})
    return {"input_root": str(root), "inputs": result,
            "passed": all(row["status"] == "ok" for row in result),
            "counts": {s: sum(r["status"] == s for r in result) for s in ["ok", "missing", "hash_mismatch"]}}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input-root", type=Path, default=ROOT)
    parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args()
    if args.report.exists():
        raise FileExistsError(args.report)
    report = check(args.input_root.resolve())
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    print(json.dumps(report["counts"]))
    raise SystemExit(0 if report["passed"] else 1)
