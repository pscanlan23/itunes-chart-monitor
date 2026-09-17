#!/usr/bin/env python3
"""
Add, update or remove an email recipient in config.json.

Driven by the "Manage alert recipients" workflow, which gives you a form in the
Actions tab -- no need to hand-edit JSON. Can also be run locally:

    python3 manage_recipients.py --action add \
        --address someone@legionm.com --alerts significant --min-move 5
"""
import argparse
import json
import os
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
CONFIG = HERE / "config.json"
VALID = {"every_change", "significant", "milestones", "none"}
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def describe(r):
    mode = r.get("alerts", "every_change")
    if mode == "significant":
        return f"moves of {r.get('min_move', 5)}+ places"
    return {"every_change": "every change",
            "milestones": "top 5/10/25/50 crossings",
            "none": "muted"}.get(mode, mode)


def summarise(recipients):
    lines = ["| Address | Alerts on |", "|---|---|"]
    for r in recipients:
        lines.append(f"| {r['address']} | {describe(r)} |")
    if not recipients:
        lines.append("| _(nobody)_ | |")
    return "\n".join(lines)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--action", required=True, choices=["add", "update", "remove", "list"])
    ap.add_argument("--address", default="")
    ap.add_argument("--alerts", default="every_change")
    ap.add_argument("--min-move", default="5")
    a = ap.parse_args()

    cfg = json.loads(CONFIG.read_text())
    email = cfg.setdefault("email", {})
    recipients = email.setdefault("recipients", [])
    address = a.address.strip().lower()

    if a.action != "list":
        if not EMAIL_RE.match(address):
            print(f"::error::'{a.address}' does not look like an email address")
            sys.exit(1)
        if a.alerts not in VALID:
            print(f"::error::alerts must be one of {sorted(VALID)}")
            sys.exit(1)

    existing = next((r for r in recipients if r.get("address", "").lower() == address), None)

    if a.action == "list":
        pass

    elif a.action == "remove":
        if not existing:
            print(f"::warning::{address} was not on the list; nothing to remove")
        else:
            recipients.remove(existing)
            print(f"Removed {address}")

    else:  # add or update
        rule = {"address": address, "alerts": a.alerts}
        if a.alerts == "significant":
            try:
                rule["min_move"] = max(1, int(a.min_move))
            except ValueError:
                rule["min_move"] = 5
        if existing:
            recipients[recipients.index(existing)] = rule
            print(f"Updated {address} -> {describe(rule)}")
        else:
            recipients.append(rule)
            print(f"Added {address} -> {describe(rule)}")

    recipients.sort(key=lambda r: r["address"])
    CONFIG.write_text(json.dumps(cfg, indent=2) + "\n")

    table = summarise(recipients)
    print("\nCurrent recipients:\n")
    print(table)

    summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary:
        with open(summary, "a") as f:
            f.write("## Alert recipients\n\n" + table + "\n")


if __name__ == "__main__":
    main()
