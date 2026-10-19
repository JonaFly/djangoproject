"""Shared helpers: HTTP with retry + on-disk cache, math utilities, markdown tables."""
from __future__ import annotations

import hashlib
import json
import math
import os
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone

CACHE_DIR = os.environ.get("CER_CACHE_DIR", os.path.join(os.path.dirname(__file__), "data"))
USER_AGENT = "crypto-edge-research/0.1 (+research; contact via repo)"


def _cache_path(url: str) -> str:
    os.makedirs(CACHE_DIR, exist_ok=True)
    return os.path.join(CACHE_DIR, hashlib.sha1(url.encode()).hexdigest() + ".json")


def get_json(url: str, params: dict | None = None, *, retries: int = 3, timeout: int = 25,
             headers: dict | None = None, cache_ttl: int = 0):
    """GET a JSON endpoint. cache_ttl>0 reuses an on-disk copy younger than that many seconds."""
    if params:
        url = url + ("&" if "?" in url else "?") + urllib.parse.urlencode(params)
    path = _cache_path(url)
    if cache_ttl and os.path.exists(path) and time.time() - os.path.getmtime(path) < cache_ttl:
        with open(path) as fh:
            return json.load(fh)
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": "application/json", **(headers or {})})
    last_err: Exception | None = None
    for attempt in range(retries):
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                data = json.loads(resp.read().decode())
            with open(path, "w") as fh:
                json.dump(data, fh)
            return data
        except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, json.JSONDecodeError) as exc:
            last_err = exc
            time.sleep(1.5 * (attempt + 1))
    raise RuntimeError(f"GET failed after {retries} attempts: {url} :: {last_err}")


def now_ms() -> int:
    return int(time.time() * 1000)


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def log_returns(closes: list[float]) -> list[float]:
    return [math.log(b / a) for a, b in zip(closes[:-1], closes[1:]) if a > 0 and b > 0]


def realized_vol(closes: list[float], periods_per_year: int = 365) -> float:
    """Annualised close-to-close realized volatility in vol points (e.g. 45.2)."""
    r = log_returns(closes)
    if len(r) < 2:
        return float("nan")
    mu = sum(r) / len(r)
    var = sum((x - mu) ** 2 for x in r) / (len(r) - 1)
    return math.sqrt(var * periods_per_year) * 100


def rolling_realized_vol(closes: list[float], window: int, periods_per_year: int = 365) -> list[float]:
    out: list[float] = []
    for i in range(len(closes)):
        if i + 1 < window + 1:
            out.append(float("nan"))
        else:
            out.append(realized_vol(closes[i - window:i + 1], periods_per_year))
    return out


def annualize_rate(rate_per_period: float, periods_per_year: float) -> float:
    """Simple (non-compounded) annualisation, matches Glassnode's 8h funding x3 x365 convention."""
    return rate_per_period * periods_per_year


def pct(x: float, nd: int = 2) -> str:
    return "n/a" if x is None or (isinstance(x, float) and math.isnan(x)) else f"{x:.{nd}f}%"


def md_table(headers: list[str], rows: list[list]) -> str:
    def fmt(v):
        if isinstance(v, float):
            return "n/a" if math.isnan(v) else f"{v:,.4g}" if abs(v) < 1 else f"{v:,.2f}"
        return str(v)
    lines = ["| " + " | ".join(headers) + " |", "|" + "|".join("---" for _ in headers) + "|"]
    lines += ["| " + " | ".join(fmt(c) for c in r) + " |" for r in rows]
    return "\n".join(lines)


def nanmean(xs) -> float:
    xs = [x for x in xs if x is not None and not (isinstance(x, float) and math.isnan(x))]
    return sum(xs) / len(xs) if xs else float("nan")


# ---- Black-Scholes helpers (no scipy dependency) ----
def _ncdf(x: float) -> float:
    return 0.5 * (1 + math.erf(x / math.sqrt(2)))


def bs_delta(spot: float, strike: float, t_years: float, iv: float, is_call: bool, r: float = 0.0) -> float:
    if t_years <= 0 or iv <= 0:
        itm = spot > strike if is_call else spot < strike
        return (1.0 if is_call else -1.0) if itm else 0.0
    d1 = (math.log(spot / strike) + (r + 0.5 * iv * iv) * t_years) / (iv * math.sqrt(t_years))
    return _ncdf(d1) if is_call else _ncdf(d1) - 1


def bs_price(spot: float, strike: float, t_years: float, iv: float, is_call: bool, r: float = 0.0) -> float:
    if t_years <= 0 or iv <= 0:
        return max(0.0, (spot - strike) if is_call else (strike - spot))
    d1 = (math.log(spot / strike) + (r + 0.5 * iv * iv) * t_years) / (iv * math.sqrt(t_years))
    d2 = d1 - iv * math.sqrt(t_years)
    if is_call:
        return spot * _ncdf(d1) - strike * math.exp(-r * t_years) * _ncdf(d2)
    return strike * math.exp(-r * t_years) * _ncdf(-d2) - spot * _ncdf(-d1)
