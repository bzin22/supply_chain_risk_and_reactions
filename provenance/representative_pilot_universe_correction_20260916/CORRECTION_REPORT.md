# Preferred-share filter correction

During pilot reconciliation, `CHK-P-D` revealed that separator-plus-`P`
preferred-share symbols were not covered by the original suffix rule. Before
changing the derived universe, the original 800-row sample and its manifest
were preserved in this directory. Its SHA-256 is
`2a6ab40a18ff71ebb693d9cae8ed0ce76188d06f95ad7d6dd25c5be683056c30`.

The corrected rule excludes forms such as `CHK-P-D`, `SCE--P-D`, `BAC-PL`,
and `TY-P`. It removed 489 security histories and reduced the active resolved
universe from 172,945 to 172,782 firm-quarters.

A subsequent domicile audit found that this intermediate universe still
treated US-listed foreign registrants as US companies. SEC
state-of-incorporation metadata is now required to confirm US domicile;
foreign and unverified-domicile issuers remain in exclusion/review provenance
but not in request inputs. The final active universe has 151,073 firm-quarters.
The stable replacement sample preserves 672 eligible rows from the intermediate
sample and fills 128 year-exchange-SIC shortages using the same seed. All
earlier requests remain immutable, but superseded observations are excluded
from active pilot statistics and listed
in `review/representative_coverage_pilot_20260916/superseded_sample_attempt_manifest.csv`.
