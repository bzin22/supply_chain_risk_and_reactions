"""Verify frozen source hashes and documented changes to active files."""
import hashlib
import json


def verify_historical_code(root, hashes):
    changes = json.loads((root / "provenance/fractional_naming_v1/manifest.json").read_text())["code"]
    integration_path = root / "provenance/fractional_main_integration_v1/manifest.json"
    integration = json.loads(integration_path.read_text())["code"] if integration_path.exists() else {}
    for name, expected in hashes.items():
        current = (root / name).read_bytes()
        if hashlib.sha256(current).hexdigest() == expected:
            continue
        change = changes.get(name)
        if change is None:
            change = integration.get(name)
            if change is None or change["historical_sha256"] != expected:
                raise ValueError(f"Historical implementation differs: {name}")
            original = (root / change["historical_path"]).read_bytes()
            if hashlib.sha256(original).hexdigest() != expected:
                raise ValueError(f"Historical source snapshot differs: {name}")
            if hashlib.sha256(current).hexdigest() != change["current_sha256"]:
                raise ValueError(f"Current integrated source differs: {name}")
            continue
        if change["historical_sha256"] != expected:
            raise ValueError(f"Historical implementation differs: {name}")
        original = (root / change["historical_path"]).read_bytes()
        if hashlib.sha256(original).hexdigest() != expected:
            raise ValueError(f"Historical source snapshot differs: {name}")
        renamed = original
        for edit in change["replacements"]:
            renamed = renamed.replace(edit["old"].encode(), edit["new"].encode())
        if current != renamed or hashlib.sha256(current).hexdigest() != change["current_sha256"]:
            raise ValueError(f"Changes exceed the recorded naming edits: {name}")
