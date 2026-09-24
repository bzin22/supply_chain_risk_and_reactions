"""Verify frozen source hashes through recorded naming and layout revisions."""
import hashlib
import json


def digest(data):
    return hashlib.sha256(data).hexdigest()


def verify_historical_code(root, hashes):
    naming = json.loads((root / "provenance/fractional_naming_v1/manifest.json").read_text())["code"]
    layout_file = root / "provenance/repository_layout_v1/manifest.json"
    layout = json.loads(layout_file.read_text())["code"] if layout_file.is_file() else {}
    publication_file = root / "provenance/repository_publication_v1/manifest.json"
    if publication_file.is_file():
        layout.update(json.loads(publication_file.read_text())["code"])
    integration_file = root / "provenance/fractional_main_integration_v1/manifest.json"
    integration = json.loads(integration_file.read_text())["code"] if integration_file.is_file() else {}
    for name, expected in hashes.items():
        relocation = layout.get(name)
        current = (root / (relocation["current_path"] if relocation else name)).read_bytes()
        if digest(current) == expected:
            continue
        # Reconstruct the pre-layout bytes before applying the earlier naming check.
        previous = current
        if relocation:
            previous = (root / relocation["snapshot_path"]).read_bytes()
            if digest(previous) != relocation["before_sha256"]:
                raise ValueError(f"Layout source snapshot differs: {name}")
            revised = previous
            for edit in relocation["edits"]:
                start, end = edit["start"], edit["end"]
                if revised[start:end] != edit["old"].encode():
                    raise ValueError(f"Layout edit differs: {name}")
                revised = revised[:start] + edit["new"].encode() + revised[end:]
            if current != revised or digest(current) != relocation["current_sha256"]:
                raise ValueError(f"Changes exceed the recorded layout edits: {name}")
        if digest(previous) == expected:
            continue
        change = naming.get(name)
        if change is None and name in integration:
            change = integration[name]
            original = (root / change["historical_path"]).read_bytes()
            if change["historical_sha256"] != expected or digest(original) != expected:
                raise ValueError(f"Historical integrated source differs: {name}")
            if digest(previous) != change["current_sha256"]:
                raise ValueError(f"Current integrated source differs: {name}")
            continue
        if change is None or change["historical_sha256"] != expected:
            raise ValueError(f"Historical implementation differs: {name}")
        original = (root / change["historical_path"]).read_bytes()
        if digest(original) != expected:
            raise ValueError(f"Historical source snapshot differs: {name}")
        renamed = original
        for edit in change["replacements"]:
            renamed = renamed.replace(edit["old"].encode(), edit["new"].encode())
        if previous != renamed or digest(previous) != change["current_sha256"]:
            raise ValueError(f"Changes exceed the recorded naming edits: {name}")
