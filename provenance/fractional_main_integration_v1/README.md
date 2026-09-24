# Historical code on current main

The frozen fractional dataset records hashes for the two top-level scoring/CAR CLI scripts that existed when the raw run was made. GitHub `main` later merged primary risk and Resolution dictionary handling and 2010Q1–2019Q4 input validation. This publish branch retains those current scripts.

`historical_code/` preserves the exact prior versions named by the frozen manifest. `manifest.json` pins both the historical and current versions. Reproduction verifies both hashes before using the compact dataset; the current top-level CLIs are not used to regenerate its CARs. The CAR implementation for the compact reproduction is `analysis/primary_event_study/core.py`, which remains separately pinned.
