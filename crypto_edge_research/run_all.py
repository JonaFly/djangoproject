"""Run every scanner, write reports/snapshot_<UTC timestamp>.md, print it. Each module fails independently."""
from __future__ import annotations

import json
import os
import traceback
from datetime import datetime, timezone

import binance_carry
import cross_venue_iv
import deribit_vrp
import polymarket_scan

MODULES = [("Deribit 波动率溢价", deribit_vrp), ("资金费率 / 基差 carry", binance_carry),
           ("Binance vs Deribit 期权跨所", cross_venue_iv), ("Polymarket", polymarket_scan)]


def main() -> str:
    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H%MZ")
    parts = [f"# Crypto edge snapshot {stamp}", ""]
    raw = {}
    for title, mod in MODULES:
        parts.append(f"## {title}")
        try:
            res = mod.run()
            raw[mod.__name__] = res
            parts.append(mod.to_markdown(res))
        except Exception:
            parts.append("```\n" + traceback.format_exc() + "```")
        parts.append("")
    out_dir = os.path.join(os.path.dirname(__file__), "reports")
    os.makedirs(out_dir, exist_ok=True)
    md = "\n".join(parts)
    with open(os.path.join(out_dir, f"snapshot_{stamp}.md"), "w") as fh:
        fh.write(md)
    with open(os.path.join(out_dir, f"snapshot_{stamp}.json"), "w") as fh:
        json.dump(raw, fh, indent=1, default=str)
    return md


if __name__ == "__main__":
    print(main())
