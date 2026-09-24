# Chart filename revision

Current charts use names such as `portfolio_charts_fractional_ties.pdf`.
`manifest.json` records each renamed artifact and its unchanged content hash.
The change affects names and descriptive labels only.

Two original source files are retained byte for byte under `historical_code/`.
The reproduction and export commands verify their original pinned hashes,
apply the recorded text replacements, and require an exact match to current
source, including its new hash. Scoring, allocation and statistical calculations
are unchanged. No frozen dataset, dictionary or packaged historical manifest
was rewritten.

`historical_records/` retains machine records from before the filename change.
Current validation and local output records use the new paths with the same
artifact hashes. The archived records and frozen package retain original labels
as historical evidence; their paths describe the files at the time of the run.

Some generated audit files were subsequently removed from output directories
at the user's request. The paths in this naming record describe the earlier
revision; archived records remain intact.
