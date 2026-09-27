#!/usr/bin/env python3
"""
scripts/generate_submission.py

Loads the expanded dataset (dataset/expanded/, produced by
dataset/generate_dataset.py) and the canonical 30 test_pairs.json, calls
bot.compose() for each pair, and writes submission.jsonl in exactly the
shape challenge-brief.md section 7.2 asks for:

    {"test_id": "T01", "body": "...", "cta": "...", "send_as": "...",
     "suppression_key": "...", "rationale": "..."}

Run:
    python3 scripts/generate_submission.py
        [--expanded-dir expanded] [--out submission.jsonl]

This is pure offline composition — no HTTP server needs to be running.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from bot import compose  # noqa: E402


def load_json(path: Path) -> dict:
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def build_lookup(expanded_dir: Path):
    categories = {}
    for f in (expanded_dir / "categories").glob("*.json"):
        d = load_json(f)
        categories[d["slug"]] = d

    merchants = {}
    for f in (expanded_dir / "merchants").glob("*.json"):
        d = load_json(f)
        merchants[d["merchant_id"]] = d

    customers = {}
    for f in (expanded_dir / "customers").glob("*.json"):
        d = load_json(f)
        customers[d["customer_id"]] = d

    triggers = {}
    for f in (expanded_dir / "triggers").glob("*.json"):
        d = load_json(f)
        triggers[d["id"]] = d

    return categories, merchants, customers, triggers


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--expanded-dir", default=str(ROOT / "expanded"))
    parser.add_argument("--out", default=str(ROOT / "submission.jsonl"))
    args = parser.parse_args()

    expanded_dir = Path(args.expanded_dir)
    categories, merchants, customers, triggers = build_lookup(expanded_dir)
    test_pairs = load_json(expanded_dir / "test_pairs.json")["pairs"]

    print(f"Loaded {len(categories)} categories, {len(merchants)} merchants, "
          f"{len(customers)} customers, {len(triggers)} triggers, {len(test_pairs)} test pairs")

    lines = []
    slow = []
    for pair in test_pairs:
        test_id = pair["test_id"]
        trigger = triggers.get(pair["trigger_id"])
        merchant = merchants.get(pair["merchant_id"])
        customer = customers.get(pair["customer_id"]) if pair.get("customer_id") else None

        if not trigger or not merchant:
            print(f"  [SKIP] {test_id}: missing trigger or merchant in expanded dataset")
            continue

        category = categories.get(merchant.get("category_slug", ""))
        if not category:
            print(f"  [SKIP] {test_id}: missing category '{merchant.get('category_slug')}'")
            continue

        t0 = time.time()
        result = compose(category, merchant, trigger, customer)
        elapsed = time.time() - t0
        if elapsed > 5:
            slow.append((test_id, elapsed))

        line = {
            "test_id": test_id,
            "body": result["body"],
            "cta": result["cta"],
            "send_as": result["send_as"],
            "suppression_key": result["suppression_key"],
            "rationale": result["rationale"],
        }
        lines.append(line)
        print(f"  [OK] {test_id} ({trigger['kind']}, {elapsed*1000:.1f}ms): {line['body'][:88]}...")

    out_path = Path(args.out)
    with open(out_path, "w", encoding="utf-8") as f:
        for line in lines:
            f.write(json.dumps(line, ensure_ascii=False) + "\n")

    print(f"\nWrote {len(lines)} lines to {out_path}")
    if slow:
        print(f"WARNING: {len(slow)} compositions took >5s: {slow}")
    empties = [l["test_id"] for l in lines if not l["body"].strip()]
    if empties:
        print(f"WARNING: empty bodies for: {empties}")
    else:
        print("All bodies non-empty. Good to submit.")


if __name__ == "__main__":
    main()
