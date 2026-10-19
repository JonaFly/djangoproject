"""Binance Options (eapi) vs Deribit: same expiry/strike implied-vol and executable price gaps.

Data sources (public):
  * eapi.binance.com /eapi/v1/mark    -> markIV per option symbol (BTC-251226-100000-C)
  * eapi.binance.com /eapi/v1/ticker  -> bid/ask in USDT
  * www.deribit.com  book summary     -> bid/ask in BTC, mark_iv, underlying price

Fees (public schedules, verify before trading):
  Binance options taker 0.03% of notional, capped at 10% of premium.
  Deribit options taker 0.03% of underlying (BTC) per contract, capped at 12.5% of option price.
"""
from __future__ import annotations

import sys
from datetime import datetime, timezone

from common import get_json, md_table
from deribit_vrp import fetch_option_chain, parse_instrument

EAPI = "https://eapi.binance.com"
BINANCE_FEE_NOTIONAL, BINANCE_FEE_CAP = 0.0003, 0.10
DERIBIT_FEE_UNDERLYING, DERIBIT_FEE_CAP = 0.0003, 0.125


def fetch_binance_marks() -> list[dict]:
    return get_json(f"{EAPI}/eapi/v1/mark", cache_ttl=300)


def fetch_binance_tickers() -> list[dict]:
    return get_json(f"{EAPI}/eapi/v1/ticker", cache_ttl=300)


def parse_binance_symbol(sym: str):
    try:
        ccy, exp, strike, cp = sym.split("-")
        return ccy, datetime.strptime(exp, "%y%m%d").replace(hour=8, tzinfo=timezone.utc), float(strike), cp == "C"
    except ValueError:
        return None


def option_fee(venue: str, premium_usd: float, spot: float) -> float:
    if venue == "binance":
        return min(BINANCE_FEE_NOTIONAL * spot, BINANCE_FEE_CAP * premium_usd)
    return min(DERIBIT_FEE_UNDERLYING * spot, DERIBIT_FEE_CAP * premium_usd)


def executable_edge(buy_ask: float, sell_bid: float, spot: float, buy_venue: str, sell_venue: str) -> float:
    """USD profit per 1 BTC of option notional from buying at one venue's ask and selling at the other's bid."""
    return sell_bid - buy_ask - option_fee(buy_venue, buy_ask, spot) - option_fee(sell_venue, sell_bid, spot)


def match(binance_marks: list[dict], binance_tickers: list[dict], deribit_chain: list[dict]) -> list[dict]:
    tick = {t["symbol"]: t for t in binance_tickers}
    bmap = {}
    for m in binance_marks:
        p = parse_binance_symbol(m["symbol"])
        if p and p[0] == "BTC":
            bmap[(p[1].date(), p[2], p[3])] = m
    out = []
    for row in deribit_chain:
        p = parse_instrument(row["instrument_name"])
        if not p:
            continue
        key = (p[0].date(), p[1], p[2])
        bm = bmap.get(key)
        if not bm or not row.get("mark_iv") or not row.get("underlying_price"):
            continue
        spot = float(row["underlying_price"])
        d_bid = (row.get("bid_price") or 0) * spot
        d_ask = (row.get("ask_price") or 0) * spot
        bt = tick.get(bm["symbol"], {})
        b_bid, b_ask = float(bt.get("bidPrice", 0) or 0), float(bt.get("askPrice", 0) or 0)
        iv_gap = float(bm["markIV"]) * 100 - float(row["mark_iv"])
        edges = []
        if b_ask and d_bid:
            edges.append(("buy Binance / sell Deribit", executable_edge(b_ask, d_bid, spot, "binance", "deribit")))
        if d_ask and b_bid:
            edges.append(("buy Deribit / sell Binance", executable_edge(d_ask, b_bid, spot, "deribit", "binance")))
        best = max(edges, key=lambda e: e[1]) if edges else ("n/a", float("nan"))
        out.append({"expiry": key[0].isoformat(), "strike": key[1], "type": "C" if key[2] else "P",
                    "deribit_iv": float(row["mark_iv"]), "binance_iv": float(bm["markIV"]) * 100, "iv_gap": iv_gap,
                    "best_direction": best[0], "net_edge_usd": best[1], "deribit_oi": row.get("open_interest", 0)})
    return sorted(out, key=lambda r: -(r["net_edge_usd"] if r["net_edge_usd"] == r["net_edge_usd"] else -1e9))


def run() -> dict:
    rows = match(fetch_binance_marks(), fetch_binance_tickers(), fetch_option_chain("BTC"))
    pos = [r for r in rows if r["net_edge_usd"] > 0]
    gaps = [abs(r["iv_gap"]) for r in rows]
    return {"n_matched": len(rows), "n_positive_after_fees": len(pos),
            "mean_abs_iv_gap": sum(gaps) / len(gaps) if gaps else float("nan"), "top": rows[:15]}


def to_markdown(res: dict) -> str:
    return "\n".join([
        "### Binance Options vs Deribit 同到期同行权价 IV/可执行价差",
        md_table(["指标", "值"], [["匹配合约数", res["n_matched"]], ["扣费后正收益合约数", res["n_positive_after_fees"]],
                                 ["平均 |IV 差| (vol pts)", res["mean_abs_iv_gap"]]]),
        "", md_table(["到期", "行权", "C/P", "Deribit IV", "Binance IV", "IV 差", "方向", "扣费净边际 $/BTC", "Deribit OI"],
                     [[r["expiry"], r["strike"], r["type"], r["deribit_iv"], r["binance_iv"], r["iv_gap"],
                       r["best_direction"], r["net_edge_usd"], r["deribit_oi"]] for r in res["top"]])])


if __name__ == "__main__":
    print(to_markdown(run()))
