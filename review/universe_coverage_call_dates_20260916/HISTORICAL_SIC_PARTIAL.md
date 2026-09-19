# Inactive historical-SIC experiment

The SEC 10-K header experiment stopped after 525 checksummed issuer records
because the archive endpoint throughput made a complete, representative pass
impractical for this stage. No completion marker was written.

`build_historical_universe.py` ignores this partial manifest unless
`sec_historical_sic_complete.json` exists. Therefore none of these 525 records
is used selectively in the active universe. The active build instead uses the
complete SEC issuer-metadata SIC field for all resolved companies and records
that limitation in the universe manifest and methodology.
