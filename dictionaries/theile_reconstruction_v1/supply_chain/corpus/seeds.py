"""The 16 seed terms from Table 1 of Theile et al. (2026)."""
SEEDS = [
    "channel partners", "customers", "demand management", "distribution",
    "fulfillment", "inventory", "logistics", "manufacturing",
    "procurement", "purchasing", "sourcing", "suppliers",
    "supply", "supply chain", "transportation", "warehousing",
]
MULTIWORD_SEEDS = [s for s in SEEDS if " " in s]
SINGLE_WORD_SEEDS = [s for s in SEEDS if " " not in s]

# Table 2 of the paper: the 30 highest-cosine keywords, with the paper's values.
# Only 13 of the 16 seeds appear at 1.00; the three multiword seeds are absent,
# which is how we know multiword removal was applied to the seeds themselves.
TABLE_2 = {
    "customers": (1.00, 77945), "supply": (1.00, 58816), "inventory": (1.00, 29466),
    "manufacturing": (1.00, 12084), "distribution": (1.00, 11690), "suppliers": (1.00, 6519),
    "transportation": (1.00, 5515), "logistics": (1.00, 5037), "purchasing": (1.00, 2555),
    "sourcing": (1.00, 2370), "procurement": (1.00, 2197), "fulfillment": (1.00, 854),
    "warehousing": (1.00, 328), "resellers": (0.86, 159), "endcustomers": (0.84, 2),
    "vars": (0.83, 27), "pims": (0.83, 2), "inventories": (0.83, 5415),
    "supplychain": (0.81, 485), "isvs": (0.80, 10), "vendors": (0.80, 2189),
    "warehouse": (0.79, 1318), "workinprocess": (0.78, 31), "integrators": (0.78, 81),
    "endcustomer": (0.78, 21), "workflow": (0.78, 400), "eprocurement": (0.77, 4),
    "slowmoving": (0.76, 89), "customer": (0.76, 44204), "supplier": (0.75, 4854),
}
TABLE_2_NON_SEED = {k: v for k, v in TABLE_2.items() if k not in SINGLE_WORD_SEEDS}
PAPER_FINAL_SIZE = 208
PAPER_IN_TRANSCRIPTS = 193
