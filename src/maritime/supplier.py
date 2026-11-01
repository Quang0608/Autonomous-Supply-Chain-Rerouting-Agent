"""Read only AlMahri's source CSV and select direct supplier relationships.

Do not infer actual transportation transactions from suppliesTo edges.
"""
from __future__ import annotations

import csv
from collections import defaultdict, deque
from pathlib import Path
import random

REQUIRED = ("Supplier", "Supplier Industry", "Supplier Country",
            "Customer", "Customer Industry", "Customer Country")
# The AlMahri extract uses this BMW manufacturing entity name; retain legacy
# aliases where they occur, and include the actual name present in this graph.
TARGETS = {"Tesla Inc", "BMW AG", "BMW Group", "BMW Brilliance Automotive Ltd", "Mercedes-Benz Group AG"}


def locate_csv(workspace: Path, upstream: str | None = None) -> Path:
    if upstream:
        root = Path(upstream).expanduser().resolve()
        candidate = root if root.is_file() else root / "dataset" / "supplychainKG_clean.csv"
        if not candidate.is_file():
            raise FileNotFoundError(f"Upstream CSV not found: {candidate}")
        return candidate
    workspace = workspace.resolve()
    candidates = [workspace.parent / "dataset" / "supplychainKG_clean.csv"]
    candidates += [p / "dataset" / "supplychainKG_clean.csv"
                   for p in workspace.parent.iterdir() if p.is_dir() and p != workspace]
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    raise FileNotFoundError(
        "Cannot find AlMahri's dataset/supplychainKG_clean.csv in a sibling folder. "
        "Pass --upstream PATH_TO_ALMAHRI_REPOSITORY."
    )


def read_edges(csv_path: Path) -> list[dict[str, str]]:
    rows = []
    seen = set()
    with csv_path.open(encoding="utf-8-sig", errors="replace", newline="") as fh:
        reader = csv.DictReader(fh)
        missing = set(REQUIRED) - set(reader.fieldnames or [])
        if missing:
            raise ValueError(f"CSV missing expected fields: {sorted(missing)}")
        for row in reader:
            if any(not row.get(k, "").strip() for k in REQUIRED):
                continue
            record = {k: row[k].strip() for k in REQUIRED}
            key = (record["Supplier"], record["Customer"])
            if key not in seen:
                rows.append(record)
                seen.add(key)
    return rows


def tier_from_manufacturer(edges: list[dict[str, str]], max_tier: int = 4) -> dict[str, int]:
    """Tier of each supplier company from the nearest listed manufacturer.

    suppliesTo points upstream -> downstream. We traverse backwards.
    """
    suppliers_for_customer = defaultdict(set)
    companies = set()
    for row in edges:
        suppliers_for_customer[row["Customer"]].add(row["Supplier"])
        companies.update([row["Customer"], row["Supplier"]])
    starts = sorted(TARGETS & companies)
    depth = {x: 0 for x in starts}
    queue = deque(starts)
    while queue:
        customer = queue.popleft()
        if depth[customer] == max_tier:
            continue
        for supplier in sorted(suppliers_for_customer[customer]):
            if supplier not in depth or depth[supplier] > depth[customer] + 1:
                depth[supplier] = depth[customer] + 1
                queue.append(supplier)
    return depth


def choose_pairs(edges: list[dict[str, str]], supported: set[str], limit: int, seed: int) -> tuple[list[dict], dict]:
    tiers = tier_from_manufacturer(edges)
    eligible = []
    for row in edges:
        sc, cc = row["Supplier Country"], row["Customer Country"]
        if sc not in supported or cc not in supported or sc == cc:
            continue
        supplier_tier = tiers.get(row["Supplier"])
        customer_tier = tiers.get(row["Customer"])
        in_chain = supplier_tier is not None and customer_tier is not None and supplier_tier == customer_tier + 1
        eligible.append({**row, "tier": supplier_tier if in_chain else "", "linked_to_manufacturer": in_chain})
    rng = random.Random(seed)
    linked = [r for r in eligible if r["linked_to_manufacturer"]]
    others = [r for r in eligible if not r["linked_to_manufacturer"]]
    rng.shuffle(linked)
    rng.shuffle(others)
    selected = (linked + others)[:limit]
    report = {
        "input_relationships": len(edges), "eligible_international_pairs": len(eligible),
        "eligible_connected_to_target_within_four_tiers": len(linked),
        "selected_pairs": len(selected),
        "selected_linked_to_manufacturer": sum(bool(x["linked_to_manufacturer"]) for x in selected),
        "requested_pairs": limit,
        "warning": "An original suppliesTo edge does not prove a specific product, facility or historical shipment."
    }
    return selected, report
