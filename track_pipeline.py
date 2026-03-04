from __future__ import annotations

import datetime as dt
import json
import logging
import os
import re
import base64
from dataclasses import dataclass
from difflib import SequenceMatcher
from typing import Any, Dict, Iterable, List, Optional

import requests
from bs4 import BeautifulSoup

# module logger
logger = logging.getLogger(__name__)


NSE_HOME = "https://www.nseindia.com/"
NSE_IPO_API = "https://www.nseindia.com/api/ipo-current-issue"
CHITTORGARH_GMP_URL = "https://www.chittorgarh.com/ipo/ipo-grey-market-premium-latest-gmp/22/"
IPOWATCH_GMP_URL = "https://ipowatch.in/ipo-grey-market-premium-latest/"
SAFEGOLD_POST_RATE_URL = "https://www.safegold.com/YnV5LXJhdGU="
SAFEGOLD_TID_URL = "https://www.safegold.com/get-tid"


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


def _walk_dict_values(data: Any) -> Iterable[tuple[str, Any]]:
    if isinstance(data, dict):
        for k, v in data.items():
            yield str(k).lower(), v
            yield from _walk_dict_values(v)
    elif isinstance(data, list):
        for item in data:
            yield from _walk_dict_values(item)


def _b64decode_with_padding(value: str) -> bytes:
    padded = value + "=" * (-len(value) % 4)
    return base64.urlsafe_b64decode(padded.encode("utf-8"))


def _decode_jwt_no_verify(token: str) -> Optional[Dict[str, Any]]:
    parts = token.split(".")
    if len(parts) != 3:
        return None
    try:
        payload_raw = _b64decode_with_padding(parts[1]).decode("utf-8")
        return json.loads(payload_raw)
    except Exception:
        return None


def _decode_embedded_blob(blob: str) -> Optional[Dict[str, Any]]:
    candidates = [blob]
    for item in candidates:
        try:
            decoded = base64.b64decode(item).decode("utf-8")
            candidates.append(decoded)
        except Exception:
            pass
        try:
            decoded = _b64decode_with_padding(item).decode("utf-8")
            candidates.append(decoded)
        except Exception:
            pass

    for candidate in candidates:
        if candidate.startswith("{") and candidate.endswith("}"):
            try:
                return json.loads(candidate)
            except Exception:
                continue
        decoded_jwt = _decode_jwt_no_verify(candidate)
        if decoded_jwt:
            return decoded_jwt
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
        "Accept": "application/json,text/plain,*/*",
        "Origin": "https://www.safegold.com",
        "Referer": "https://www.safegold.com/",
        "X-Requested-With": "XMLHttpRequest",
    }

    def _mask_secret(value: str) -> str:
        if not value:
            return ""
        if len(value) <= 10:
            return "*" * len(value)
        return f"{value[:6]}...{value[-4:]}"

    def _parse_price_from_json(payload: Any) -> Optional[Dict[str, Any]]:
        buy_price = None
        sell_price = None
        as_of = None
        currency = "INR"

        buy_keys = {"buy_price", "buy", "gold_buy_price", "buyprice", "current_buy_price", "rate"}
        sell_keys = {"sell_price", "sell", "gold_sell_price", "sellprice", "current_sell_price"}
        ts_keys = {"updated_at", "last_updated", "timestamp", "as_of", "created_at"}
        ccy_keys = {"currency", "ccy"}

        for key, value in _walk_dict_values(payload):
            if buy_price is None and key in buy_keys:
                buy_price = _extract_float(value)
            if sell_price is None and key in sell_keys:
                sell_price = _extract_float(value)
            if as_of is None and key in ts_keys and isinstance(value, str):
                as_of = value
            if key in ccy_keys and isinstance(value, str) and value.strip():
                currency = value.strip().upper()

        if buy_price is None and sell_price is not None:
            buy_price = sell_price
        if buy_price is None:
            return None
        return {
            "source": "safegold",
            "buy_price_per_gram": round(buy_price, 2),
            "sell_price_per_gram": round(sell_price, 2) if sell_price is not None else None,
            "currency": currency,
            "as_of": as_of or dt.datetime.now(dt.timezone.utc).isoformat(),
        }

    def _fetch_from_post_jwt() -> Optional[Dict[str, Any]]:
        post_url = os.getenv("SAFEGOLD_POST_RATE_URL", SAFEGOLD_POST_RATE_URL).strip() or SAFEGOLD_POST_RATE_URL
        tid_url = os.getenv("SAFEGOLD_TID_URL", SAFEGOLD_TID_URL).strip() or SAFEGOLD_TID_URL
        home_url = os.getenv("SAFEGOLD_HOME_URL", "https://www.safegold.com/").strip() or "https://www.safegold.com/"
        csrf = os.getenv("SAFEGOLD_CSRF", "").strip()
        upi = os.getenv("SAFEGOLD_UPI", "0").strip() or "0"
        session = requests.Session()
        session.headers.update(headers)

        # Some Safegold edge rules require a prior page load before API calls.
        try:
            home_resp = session.get(home_url, timeout=20)
            logger.debug(
                "Safegold home bootstrap status=%s headers=%s cookies=%s",
                home_resp.status_code,
                dict(home_resp.headers),
                session.cookies.get_dict(),
            )
        except Exception as e:
            logger.debug("Safegold home bootstrap failed (continuing): %s", e)

        def _fetch_csrf_token() -> str:
            if csrf:
                logger.debug("Using SAFEGOLD_CSRF from env (masked): %s", _mask_secret(csrf))
                return csrf
            try:
                logger.debug("Fetching Safegold CSRF token from: %s", tid_url)
                logger.debug("Safegold get-tid request headers: %s", headers)
                tid_resp = session.get(tid_url, timeout=20)
                logger.debug(
                    "Safegold get-tid response status=%s headers=%s body_sample=%s",
                    tid_resp.status_code,
                    dict(tid_resp.headers),
                    (tid_resp.text or "")[:500],
                )
                logger.debug("Safegold get-tid cookies: %s", session.cookies.get_dict())
                tid_resp.raise_for_status()
                raw = (tid_resp.text or "").strip()
                if raw.startswith("{"):
                    try:
                        obj = tid_resp.json()
                    except Exception:
                        obj = {}
                    for key in ("csrf", "tid", "token", "data"):
                        val = obj.get(key)
                        if isinstance(val, str) and val.strip():
                            return val.strip()
                return raw.strip('"')
            except Exception as e:
                logger.warning("Safegold get-tid failed: %s", e)
                return ""

        csrf_value = _fetch_csrf_token()
        if not csrf_value:
            logger.debug("No Safegold CSRF token available; skipping POST JWT fetch")
            return None

        post_headers = {
            "User-Agent": headers["User-Agent"],
            "Accept": "application/json,text/plain,*/*",
            "csrf": csrf_value,
            "tid": csrf_value,
            "x-csrf-token": csrf_value,
            "x-xsrf-token": csrf_value,
            "upi": upi,
            "Origin": "https://www.safegold.com",
            "Referer": "https://www.safegold.com/",
            "X-Requested-With": "XMLHttpRequest",
        }
        safe_post_headers = dict(post_headers)
        safe_post_headers["csrf"] = _mask_secret(safe_post_headers.get("csrf", ""))
        safe_post_headers["tid"] = _mask_secret(safe_post_headers.get("tid", ""))
        safe_post_headers["x-csrf-token"] = _mask_secret(safe_post_headers.get("x-csrf-token", ""))
        safe_post_headers["x-xsrf-token"] = _mask_secret(safe_post_headers.get("x-xsrf-token", ""))
        try:
            logger.debug("Fetching Safegold rate JWT via POST URL: %s", post_url)
            logger.debug("Safegold POST request headers: %s", safe_post_headers)
            attempts = [
                {"kwargs": {"headers": post_headers}},
                {"kwargs": {"headers": {**post_headers, "Content-Type": "application/json"}, "json": {"upi": int(upi)}}},
                {
                    "kwargs": {
                        "headers": {**post_headers, "Content-Type": "application/x-www-form-urlencoded"},
                        "data": {"upi": upi},
                    }
                },
                {
                    "kwargs": {
                        "headers": {**post_headers, "Content-Type": "application/x-www-form-urlencoded"},
                        "data": {"upi": upi, "csrf": csrf_value, "tid": csrf_value},
                    }
                },
                {
                    "kwargs": {
                        "headers": {**post_headers, "Content-Type": "application/json"},
                        "json": {"upi": int(upi), "csrf": csrf_value, "tid": csrf_value},
                    }
                },
            ]
            resp = None
            last_error = None
            for idx, attempt in enumerate(attempts, start=1):
                try:
                    resp = session.post(post_url, timeout=20, **attempt["kwargs"])
                    logger.debug(
                        "Safegold POST attempt=%s status=%s headers=%s body_sample=%s cookies=%s",
                        idx,
                        resp.status_code,
                        dict(resp.headers),
                        (resp.text or "")[:500],
                        session.cookies.get_dict(),
                    )
                    if resp.status_code < 400:
                        break
                    last_error = RuntimeError(f"status={resp.status_code}")
                except Exception as err:
                    last_error = err
            if resp is None or resp.status_code >= 400:
                raise RuntimeError(f"Safegold POST failed after retries: {last_error}")
        except Exception as e:
            logger.warning("Safegold POST JWT fetch failed: %s", e)
            return None

        token_candidates: List[str] = []
        raw_text = (resp.text or "").strip().strip('"')
        if raw_text:
            token_candidates.append(raw_text)

        try:
            parsed = resp.json()
        except Exception:
            parsed = None
        if isinstance(parsed, dict):
            for key in ["token", "jwt", "data", "rate", "payload"]:
                val = parsed.get(key)
                if isinstance(val, str) and val.strip():
                    token_candidates.append(val.strip())
        elif isinstance(parsed, str) and parsed.strip():
            token_candidates.append(parsed.strip())

        for candidate in token_candidates:
            jwt_payload = _decode_jwt_no_verify(candidate)
            if not jwt_payload:
                decoded = _decode_embedded_blob(candidate)
                if decoded:
                    result = _parse_price_from_json(decoded)
                    if result:
                        return result
                continue

            result = _parse_price_from_json(jwt_payload)
            if result:
                return result

            inner_blob = jwt_payload.get("data")
            if isinstance(inner_blob, str) and inner_blob.strip():
                decoded_inner = _decode_embedded_blob(inner_blob.strip())
                if decoded_inner:
                    result = _parse_price_from_json(decoded_inner)
                    if result:
                        return result
        return None

    post_result = _fetch_from_post_jwt()
    if post_result:
        return post_result

    logger.warning("Safegold POST rate fetch failed; no fallback configured")
    return None


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
