"""Raw label -> attack category mapping for both datasets.

Order matters: patterns are tested top to bottom (e.g. "DDoS" before "DoS",
"Web Attack - Brute Force" before generic brute force).
"""
from __future__ import annotations

import re

ATTEMPTED_RE = re.compile(r"\s*-\s*attempted\s*$", re.IGNORECASE)

CATEGORY_PATTERNS: list[tuple[str, re.Pattern]] = [
    ("Benign", re.compile(r"^benign$", re.I)),
    ("WebAttack", re.compile(r"^web attack", re.I)),
    ("Infiltration", re.compile(r"^infilt(e)?ration", re.I)),
    ("DDoS", re.compile(r"^ddos", re.I)),
    ("DoS", re.compile(r"^(dos\b|heartbleed)", re.I)),
    ("BruteForce", re.compile(r"(ftp|ssh)[-_ ]?(patator|bruteforce|brute force)", re.I)),
    ("Botnet", re.compile(r"^bot(net)?\b", re.I)),
    ("PortScan", re.compile(r"^port\s?scan", re.I)),
]


def is_attempted(raw_label: str) -> bool:
    return bool(ATTEMPTED_RE.search(raw_label))


def base_label(raw_label: str) -> str:
    return ATTEMPTED_RE.sub("", raw_label).strip()


def to_category(raw_label: str) -> str:
    base = base_label(raw_label)
    for cat, pat in CATEGORY_PATTERNS:
        if pat.search(base):
            return cat
    raise ValueError(f"Unmapped label {raw_label!r}. Add it to src/ingestion/labels.py")


def build_label_table(raw_labels, attempted_policy: str) -> dict[str, str | None]:
    """Map every distinct raw label to its final category (None = drop the flow)."""
    table = {}
    for lab in raw_labels:
        cat = to_category(lab)
        if cat != "Benign" and is_attempted(lab):
            if attempted_policy == "benign":
                cat = "Benign"
            elif attempted_policy == "drop":
                cat = None
            elif attempted_policy != "attack":
                raise ValueError(f"Unknown attempted_policy {attempted_policy!r}")
        table[lab] = cat
    return table
