# Publication on current main

The cleanup was integrated on `21fedc3`, the current GitHub `main`, in an
isolated worktree. The original local branch and staged index were preserved.
That main revision contains collection and dictionary updates absent from the
older local checkout used for the initial layout cleanup.

The publication retains main's primary dictionary handling and hard
2010Q1–2019Q4 checks. Additional root-level collection/preparation scripts moved
to `collection/`, and their tests moved to `tests/`. Module imports, repository
roots, provisional export paths and executable examples were updated. Use
`python -m collection.<module>` and `python -m scoring.<module>` from the root.
All tests are discovered under `tests/`.

`manifest.json` records those additional relocations. For the two integrated
scoring/CAR modules, the verifier checks the original frozen source, the
unchanged `fractional_main_integration_v1` record, and the exact publication
layout edits. It uses these mappings in place of the initial local-checkout
layout mappings for those two files. Historical manifests and paths are not
rewritten. Other files continue to use the original naming/layout chain.

Direct checks passed in this worktree: **209 tests passed, 29 skipped** because
optional private/legacy inputs are absent. Ruff E9/F passed with the retained
primary-package unused-import exception. The documented reproduction shell
command regenerated all five fractional panels and verified 52,533 calls from
2,026 firms. The five published tables and frozen dataset/dictionary files are
unchanged. No raw collection, model training or full raw scoring/CAR rebuild
was run, and dependencies used the existing pinned environment.

The broader checks found a pre-existing missing `re` import in the upstream
transcript extractor; it was restored, with a regression test for its text
helpers. Two unused imports were removed. The private cleanup inventories
remain ignored. No-mistakes was not run, per the publishing instruction in
`AGENTS.md`.

The earlier `repository_layout_v1` validation/storage records describe the
original local cleanup. Its local deletion count is not a claim that all those
ignored files were ever stored on GitHub. Two obsolete chart/report builders
are deleted from Git; renamed source files remain recoverable in history.
