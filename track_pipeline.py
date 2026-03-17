from __future__ import annotations

import datetime as dt
import json
import logging
import os
import re
from dataclasses import dataclass
from difflib import SequenceMatcher
from typing import Any, Dict, List, Optional

import requests
from bs4 import BeautifulSoup

# module logger
logger = logging.getLogger(__name__)


NSE_HOME = "https://www.nseindia.com/"
NSE_IPO_API = "https://www.nseindia.com/api/ipo-current-issue"
CHITTORGARH_GMP_URL = "https://www.chittorgarh.com/ipo/ipo-grey-market-premium-latest-gmp/22/"
IPOWATCH_GMP_URL = "https://ipowatch.in/ipo-grey-market-premium-latest/"
SAFEGOLD_BUY_URL = (
    "https://website-backend.safegold.com/api/v1/metal/prices/buy/gold_9999"
    "?has_discount=0&discount_type=upi"
)
SAFEGOLD_SELL_URL = (
    "https://website-backend.safegold.com/api/v1/metal/prices/sell/gold_9999"
    "?has_discount=0&discount_type=upi"
)


@dataclass
class IPOEntry:
    ipo_name: str
    symbol: str
    open_date: dt.date
    close_date: dt.date
    issue_price: float


@dataclass
class GMPEntry:
    ipo_name: str
    gmp: float
    source: str


def _session() -> requests.Session:
    session = requests.Session()
    session.headers.update(
        {
            "User-Agent": (
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/123.0.0.0 Safari/537.36"
            ),
            "Accept": "application/json,text/html,application/xhtml+xml",
            "Accept-Language": "en-US,en;q=0.9",
            "Referer": NSE_HOME,
        }
    )
    logger.debug("Created HTTP session with headers: %s", session.headers)
    return session


def _normalize_name(name: str) -> str:
    cleaned = re.sub(r"[^a-z0-9 ]+", " ", name.lower())
    cleaned = re.sub(r"\b(ipo|limited|ltd|sme|mainboard|board|issue)\b", " ", cleaned)
    return re.sub(r"\s+", " ", cleaned).strip()


def _extract_first_number(text: str) -> Optional[float]:
    nums = re.findall(r"\d+(?:\.\d+)?", text.replace(",", ""))
    if not nums:
        return None
    return float(nums[-1])


def _extract_float(value: Any) -> Optional[float]:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        nums = re.findall(r"[+-]?\d+(?:\.\d+)?", value.replace(",", ""))
        if nums:
            try:
                return float(nums[0])
            except ValueError:
                return None
    return None




def _extract_gmp_value(text: str) -> Optional[float]:
    s = text.strip().lower()
    if not s:
        return None
    compact = re.sub(r"\s+", "", s)
    if compact in {"na", "n/a", "--", "-", "nil"}:
        return None
    if "not traded" in s or "not available" in s:
        return None
    # Prefer explicit currency/signed values in GMP cells.
    m = re.search(r"(?:₹|rs\.?)\s*([+-]?\d+(?:\.\d+)?)", s)
    if not m:
        m = re.search(r"([+-]?\d+(?:\.\d+)?)", s)
    if not m:
        return None
    try:
        val = float(m.group(1))
    except ValueError:
        return None
    # Guard against accidentally parsing years/dates as GMP.
    if abs(val) > 999:
        return None
    return val


def _parse_issue_price(value: Any) -> Optional[float]:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    value_str = str(value).strip()
    if not value_str:
        return None
    parts = re.findall(r"\d+(?:\.\d+)?", value_str.replace(",", ""))
    if not parts:
        return None
    return float(parts[-1])


def _parse_date(value: str) -> Optional[dt.date]:
    if not value:
        return None
    value = value.strip().replace(",", "")
    formats = [
        "%d-%b-%Y",
        "%d-%B-%Y",
        "%d %b %Y",
        "%d %B %Y",
        "%d/%m/%Y",
        "%Y-%m-%d",
    ]
    for fmt in formats:
        try:
            return dt.datetime.strptime(value, fmt).date()
        except ValueError:
            continue
    return None


def _today() -> dt.date:
    return dt.date.today()


def fetch_nse_ipos() -> List[IPOEntry]:
    session = _session()
    try:
        logger.debug("Fetching IPO data from NSE API")
        session.get(NSE_HOME, timeout=20)
        response = session.get(NSE_IPO_API, timeout=20)
        response.raise_for_status()
        payload = response.json()
        logger.debug("Received payload: %s", payload)
    except Exception as e:
        logger.exception("Error fetching IPOs: %s", e)
        return []

    raw_rows = payload if isinstance(payload, list) else payload.get("data", payload.get("records", []))
    ipos: List[IPOEntry] = []
    logger.debug("Parsing raw IPO rows, total %d", len(raw_rows) if raw_rows is not None else 0)
    for row in raw_rows:
        symbol = str(row.get("symbol") or "").strip()
        name = str(
            row.get("companyName")
            or row.get("symbol")
            or row.get("name")
            or row.get("issueName")
            or ""
        ).strip()
        series = str(row.get("series") or "").upper().strip()
        if series == "DEBT":
            continue
        open_date = _parse_date(str(row.get("issueStartDate") or row.get("openDate") or row.get("open_date") or ""))
        close_date = _parse_date(str(row.get("issueEndDate") or row.get("closeDate") or row.get("close_date") or ""))
        issue_price = _parse_issue_price(
            row.get("priceBand")
            or row.get("issuePrice")
            or row.get("issue_price")
            or row.get("price")
        )
        if not (name and open_date and close_date and issue_price):
            continue
        ipos.append(IPOEntry(name, symbol, open_date, close_date, issue_price))
    return ipos


def _parse_gmp_table(html: str, source: str) -> List[GMPEntry]:
    soup = BeautifulSoup(html, "html.parser")
    out: List[GMPEntry] = []
    for table in soup.select("table"):
        header_cells = table.select("thead th")
        if not header_cells:
            first_row = table.select_one("tr")
            header_cells = first_row.find_all(["th", "td"]) if first_row else []
        headers = [h.get_text(" ", strip=True).lower() for h in header_cells]
        name_idx = next(
            (i for i, h in enumerate(headers) if any(k in h for k in ["ipo", "company", "name"])),
            0,
        )
        gmp_idx = next((i for i, h in enumerate(headers) if "gmp" in h or "premium" in h), None)

        rows = table.select("tbody tr") or table.select("tr")
        for row in rows:
            cells = row.find_all(["td", "th"])
            if not cells:
                continue
            cols = [c.get_text(" ", strip=True) for c in cells]
            if len(cols) < 2:
                continue

            local_name_idx = name_idx if name_idx < len(cols) else 0
            name = cols[local_name_idx].strip()
            lowered = name.lower()
            if not name:
                continue
            if any(
                k in lowered
                for k in [
                    "ipo date",
                    "subject",
                    "allotment",
                    "listing",
                    "open date",
                    "close date",
                    "review",
                    "details",
                ]
            ):
                continue
            # Ignore obvious header-like rows.
            if len(re.findall(r"[a-zA-Z]", name)) < 3:
                continue

            maybe_gmp = None
            if gmp_idx is not None and gmp_idx < len(cols):
                maybe_gmp = _extract_gmp_value(cols[gmp_idx])
            if maybe_gmp is None:
                for i, col in enumerate(cols):
                    if i == local_name_idx:
                        continue
                    maybe_gmp = _extract_gmp_value(col)
                    if maybe_gmp is not None:
                        break
            if maybe_gmp is None:
                continue
            out.append(GMPEntry(name, maybe_gmp, source))
    return out


def scrape_chittorgarh_gmp() -> List[GMPEntry]:
    try:
        logger.debug("Scraping Chittorgarh GMP")
        resp = _session().get(CHITTORGARH_GMP_URL, timeout=20)
        resp.raise_for_status()
    except Exception as e:
        logger.exception("Chittorgarh scrape failed: %s", e)
        return []
    result = _parse_gmp_table(resp.text, "chittorgarh")
    logger.debug("Chittorgarh GMP entries: %s", result)
    return result


def scrape_ipowatch_gmp() -> List[GMPEntry]:
    try:
        logger.debug("Scraping IPOwatch GMP")
        resp = _session().get(IPOWATCH_GMP_URL, timeout=20)
        resp.raise_for_status()
    except Exception as e:
        logger.exception("IPOWatch scrape failed: %s", e)
        return []
    result = _parse_gmp_table(resp.text, "ipowatch")
    logger.debug("IPOWatch GMP entries: %s", result)
    return result


def fetch_safegold_price() -> Optional[Dict[str, Any]]:
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/123.0.0.0 Safari/537.36"
        ),
        "Accept": "application/json",
    }


    buy_url = os.getenv("SAFEGOLD_BUY_URL", SAFEGOLD_BUY_URL).strip() or SAFEGOLD_BUY_URL
    sell_url = os.getenv("SAFEGOLD_SELL_URL", SAFEGOLD_SELL_URL).strip() or SAFEGOLD_SELL_URL

    def _fetch_json(url: str) -> Optional[Dict[str, Any]]:
        try:
            logger.debug("Fetching Safegold price URL: %s", url)
            resp = requests.get(url, headers=headers, timeout=20)
            logger.debug(
                "Safegold price response status=%s headers=%s body_sample=%s",
                resp.status_code,
                dict(resp.headers),
                (resp.text or "")[:500],
            )
            resp.raise_for_status()
            return resp.json()
        except Exception as e:
            logger.warning("Safegold price fetch failed for %s: %s", url, e)
            return None

    buy_payload = _fetch_json(buy_url)
    sell_payload = _fetch_json(sell_url)

    buy_rate = _extract_float(buy_payload.get("rate")) if isinstance(buy_payload, dict) else None
    sell_rate = _extract_float(sell_payload.get("rate")) if isinstance(sell_payload, dict) else None

    # If both failed, bail.
    if buy_rate is None and sell_rate is None:
        logger.warning("Safegold buy/sell price fetch failed")
        return None

    as_of = None
    if isinstance(buy_payload, dict):
        as_of = buy_payload.get("expires_at") or buy_payload.get("updated_at")
    if not as_of and isinstance(sell_payload, dict):
        as_of = sell_payload.get("expires_at") or sell_payload.get("updated_at")

    return {
        "source": "safegold",
        "buy_price_per_gram": round(buy_rate, 2) if buy_rate is not None else None,
        "sell_price_per_gram": round(sell_rate, 2) if sell_rate is not None else None,
        "currency": "INR",
        "as_of": as_of or dt.datetime.now(dt.timezone.utc).isoformat(),
    }


def _format_date(d: dt.date) -> str:
    return f"{d.day} {d.strftime('%b %Y')}"


def _token_set(name: str) -> set[str]:
    return {t for t in _normalize_name(name).split() if len(t) > 1}


def _find_best_gmp_match(ipo_name: str, symbol: str, gmp_entries: List[GMPEntry]) -> tuple[Optional[GMPEntry], float]:
    target_norm = _normalize_name(ipo_name)
    if not target_norm:
        return None, 0.0

    target_tokens = _token_set(ipo_name)
    symbol_tokens = _token_set(symbol) if symbol else set()
    best: Optional[GMPEntry] = None
    best_score = 0.0
    for candidate in gmp_entries:
        c_norm = _normalize_name(candidate.ipo_name)
        if not c_norm:
            continue
        if c_norm == target_norm:
            return candidate, 1.0

        c_tokens = _token_set(candidate.ipo_name)
        overlap = len(target_tokens & c_tokens)
        overlap_ratio = overlap / max(1, min(len(target_tokens), len(c_tokens)))
        symbol_overlap = 0.0
        if symbol_tokens:
            symbol_overlap = len(symbol_tokens & c_tokens) / max(1, len(symbol_tokens))
        seq_ratio = SequenceMatcher(a=target_norm, b=c_norm).ratio()
        score = (overlap_ratio * 0.6) + (seq_ratio * 0.3) + (symbol_overlap * 0.1)
        if score > best_score:
            best = candidate
            best_score = score

    # Conservative threshold to avoid wrong ticker->IPO mapping.
    if best_score >= 0.58:
        return best, best_score
    return None, best_score


def _decide_action(gmp_percent: float) -> Dict[str, str]:
    if gmp_percent < 5:
        return {
            "action": "AVOID",
            "reason": f"Low GMP around {round(gmp_percent, 1)}% and moderate subscription.",
        }
    if gmp_percent < 15:
        return {
            "action": "WATCH",
            "reason": f"Moderate GMP near {round(gmp_percent, 1)}%; wait for stronger demand signals.",
        }
    return {
        "action": "CONSIDER",
        "reason": f"Healthy GMP near {round(gmp_percent, 1)}% with stronger listing sentiment.",
    }


def build_track_payload() -> Dict[str, Any]:
    logger.debug("Building track payload")
    ipos = fetch_nse_ipos()
    logger.debug("Fetched %d IPOs", len(ipos))
    gmp_rows = scrape_chittorgarh_gmp() + scrape_ipowatch_gmp()
    logger.debug("Collected %d GMP rows", len(gmp_rows))
    gold_price = fetch_safegold_price()
    logger.debug("Safegold price found: %s", bool(gold_price))
    today = _today()
    out_rows: List[Dict[str, Any]] = []
    for ipo in ipos:
        if ipo.close_date < today:
            continue
        gmp, score = _find_best_gmp_match(ipo.ipo_name, ipo.symbol, gmp_rows)
        if not gmp:
            logger.debug("No GMP match found for IPO: %s (best score: %.2f)", ipo.ipo_name, score)
            continue
        gmp_percent = round((gmp.gmp / ipo.issue_price) * 100, 1)
        action_pack = _decide_action(gmp_percent)
        out_rows.append(
            {
                "ipo_name": ipo.ipo_name,
                "subscription_window": f"{_format_date(ipo.open_date)} – {_format_date(ipo.close_date)}",
                "gmp_percent": gmp_percent,
                "action": action_pack["action"],
                "reason": action_pack["reason"],
            }
        )

    return {
        "date": _format_date(today),
        "gold_price": gold_price,
        "ipos": out_rows,
    }


if __name__ == "__main__":
    print(json.dumps(build_track_payload(), indent=2))
