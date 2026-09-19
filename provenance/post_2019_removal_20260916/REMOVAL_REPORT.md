# Post-2019 removal and verification report

## Result

The active transcript corpus is now bounded to 2010Q1-2019Q4. No collection
or scoring was run.

Before removal, the audit identified:

- 9,943 affected files totaling 7,836,081,247 bytes.
- 9,000 unique post-2019 ticker-quarter calls and 9,000 raw responses totaling
  303,105,482 bytes.
- 120,653 post-2019 call-level rows across consolidated and generated copies.
- 1,111,057 post-2019 segment rows across the three segment-level copies;
  each copy contained the same 370,131 post-2019 segments.

Every listed quarter was parsed and verified as later than 2019Q4 before any
file was moved. `post_2019_observations.csv` identifies every affected row and
includes ticker, quarter, raw path, raw size, raw SHA-256, provider-response
classification, source-file size and SHA-256, and planned action.
`affected_files.csv` records every affected file, including generated-output
dependencies that are not row-addressable.

## Actions

- Moved 9,000 post-2019 raw JSON responses, without changing their bytes, to
  `.archive/post_2019_removed_20260916/artifacts/earnings_call_responses/`.
- Archived the complete mixed-period `artifacts/earnings_call_supply_chain/`
  tree. Its pooled standard deviations, ranks, CARs, and sensitivities are not
  valid for the restricted sample and were not filtered or relabeled.
- Archived the mixed-period originals of both consolidated CSVs and wrote new
  active copies containing only 2010-2019 rows.
- Archived the downstream sector-ranking output derived from the mixed sample.

## Post-removal verification

| Active item | Verified result |
| --- | ---: |
| Raw responses | 18,000 |
| Post-2019 raw responses | 0 |
| Consolidated call rows | 18,000 |
| Consolidated segment rows | 785,993 |
| Mixed-period scored/CAR output tree | absent |
| Transcript CSV SHA-256 | `6cce49f5d70c1dd8148722a2fa9336c3cd62ca2249ba26e030179b70dcf56f4c` |
| Segment CSV SHA-256 | `68f0a23ece9774b9d80bca67235d1ea37c1156ee4c3df83ff18629d6819df8b6` |

`verify_active_study_period.py` passed against both active CSVs and all 18,000
active raw responses. The archive is gitignored and outside every default
pipeline scan path.

An independent post-move comparison against the earlier 27,000-row response
audit confirmed 18,000/18,000 active 2010-2019 raw SHA-256 values and
9,000/9,000 archived 2020-2024 raw SHA-256 values, with zero missing or
mismatched files. This proves that no 2010-2019 raw response was altered.
