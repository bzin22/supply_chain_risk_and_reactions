# outputs/

Everything in this directory is generated locally and is not committed. This
README is the only tracked file here. `.gitignore` carries `outputs/**` plus an
exception for this file.

## Why nothing is committed

There are no canonical, paper-comparable results yet. Every figure and table
this repository has produced so far came out of a provisional pipeline that
differs from Theile et al. (2026) on the points listed under "Known
methodological gaps" in the root `README.md`: provisional risk and resolution
dictionaries, a different supply-chain vocabulary, proxy event dates, a
different firm universe and sample period, non-SIC industry groupings,
positive-only quintiles, no 1%/99% winsorization, and no paper-equivalent
fixed-effects regression.

A committed chart reads as a result. None of these are results. They were
diagnostics for the scoring code, so they live here, untracked, and are
regenerated on demand.

## Regenerating

The diagnostic scripts under `analysis/provisional_diagnostics/` write here.
Each takes an explicit run directory and output directory; see
`analysis/provisional_diagnostics/README.md`.

## When results can be committed

Only after the paper-alignment checks in the root `README.md` pass. At that
point add a separate, clearly named directory for validated results rather
than un-ignoring this one.
