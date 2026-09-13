# Crunchyroll Checker — V1

Premium, fast & reliable Crunchyroll account checker — **Telegram Bot + Mini App** in one.

* **Developer:** `BlazeNXT` — `https://t.me/blaze_nxt` (`Developed by : BlazeNXT` footer only)
* **Owner:** auto-detected from `OWNER_ID` / `OWNER_USERNAME` env (no hardcode)
* **Single checker:** `CRUNCHYROLL` only — no AIO clutter

---

## ✨ V1 Highlights

* **100x Fast • 1:1 Proxy per Account** — `150 workers • 2s timeout • 1000 tested → 500 live` — real live refresh with `[bar] % Live N Rate ETA`
* **Real Live Refresh** — `Testing X/Y [bar] % Live N Elapsed/ETA • 150 workers` (not fake time)
* **12 Auto Proxy Sources** — `cdn.jsdelivr.net`, `proxyscrape`, `raw.githubusercontent` etc. — auto-harvest every 5 min, `Auto Load ON/OFF`, 24x7 loop
* **Clean Inline UI** — Bot API 9.4 `style` (`primary`/`success`/`danger`) with auto-fallback, 100% `InlineKeyboardMarkup` (no ReplyKeyboard — no double message)
* **Live Progress Card** — `CRUNCHYROLL Scan — Live • Checked X/Y • Hits/Free/2FA/Bad/Errors • CPM • Elapsed • ETA • Live feed (last 3 emails)` ~1.8s updates
* **Premium Detection** — `subs/v1 benefits` (`concurrent_streams` → Fan/Mega/Ultimate) + `subs/v3` expiry/sku/auto_renew + `subs/v4` price/cycle/trial
* **500 Threads Max** — user can `/threads 50/100/200/300/500` (default 150)
* **Owner + Admins Only** — `is_admin(OWNER_ID + ADMIN_IDS + ADMIN_USERNAMES)`, `Access Denied` shows `OWNER_ID`/`OWNER_USERNAME` from env + `💬 Contact Owner` url button (`https://t.me/owner`) — tap opens owner chat

---

## 🔘 Button Flow

**Main Menu** (`/start`):
```
╭────────────────────────╮
│  🔥 CRUNCHYROLL 🔥     │
│  Premium Checker • FREE│
╰────────────────────────╯
👋 Hey <first_name>
👑 Owner • Unlimited  |  ✅ Free Access • Unlimited
┌─ STATS ────────────────┐
│ 🌐 Proxies: 110 live • 📦 Pool: 0
│ 👥 Users: 0 • 🧵 Threads: 150 (max 500)
│ ⏱ Uptime: 10m • ✅ Checks: 0
└────────────────────────┘
👇 Choose an action — buttons below 👇
━━━━━━━━━━━━━━━━━━━━━
Developed by : BlazeNXT

[💎 Check Account] [📂 Check File]
[📖 How To Use] [📊 Bot Stats]
[⚙️ Proxy Settings]
[👥 Admins] (owner only)
```

**Proxy Settings** (`⚙️ Proxy Settings` — owner/admins only):
```
⚙️ Proxy Settings — Auto Load 100x Fast
━━━━━━━━━━━━━━━━━━━━━
📊 Status: ON/OFF • 📦 Pool: 0 • 🌐 Live: 0
🔄 Auto Load: ON/OFF • 🧵 Threads: 150 (max 500)
⚡ Speed: 100x Fast • 1:1 Proxy per Account
━━━━━━━━━━━━━━━━━━━━━
Format: user:pass@ip:port or ip:port
Auto: 12 sources • Manual: text/file

[🔄 Refresh Auto] [📥 Upload Proxies]
[❌ Disable Proxies] [🧹 Clear Proxies]
[🔄 Auto Load: ON/OFF] [🧵 Set Threads]
[⬅️ Back]
```

Other: `Help` (all cmds + proxy 12 sources), `Bot Stats`, `Check Account` (`EMAIL:PASS` paste), `Check File` (`.txt/.csv`), `Admins` (owner only → Add/Remove).

---

## 📖 Help — V1

```
╭────────────────────────╮
│  📖 HELP               │
╰────────────────────────╯
🔥 Crunchyroll Checker — Powerful, Secure, Fast
━━━━━━━━━━━━━━━━━━━━━
👑 Owner + Admins Only • 24x7 Auto Proxy • 500 Threads • Smart Scoring
...
🚀 QUICK START | Buttons | Commands (/start /cmds /help /proxy /addproxy /clearproxy /threads /autoproxy /admins /addadmin /removeadmin)
...
Proxy: 12 sources • Checker: 150→500 threads
...
Developed by : BlazeNXT • Owner: @owner
```

---

## ⭐ Hit Card (V1)

```
⭐ CRUNCHYROLL HIT!
━━━━━━━━━━━━━━━━━━━━━
📧 Email: user@gmail.com
🔑 Password: pass123
━━━━━━━━━━━━━━━━━━━━━
• Plan: Mega Fan • Premium: ✅
• Expiry: 2027-02-06 • Days Left: 340
• Auto Renew: ✅ • Trial: ❌
• Price: $9.99 • Cycle: month
• Country: 🇮🇳 India • Streams: 4
━━━━━━━━━━━━━━━━━━━━━
🔥 CRUNCHYROLL
Developed by : BlazeNXT
```
Exports: `accounts.txt` + `accounts.json` (+ per-hit cards, capped 150, rest in file).

---

## ⚙️ Checker Details

* **Flow:** `beta-api.crunchyroll.com` AndroidTV UA → `subs/v1` → `subs/v3` → `subs/v4` → premium gate (`concurrent_streams` > 0)
* **1:1:** `need = len(creds)` → if `need > live` auto `refresh_live_proxies(force=True)` so each account gets dedicated proxy
* **Speed:** `PROXY_TEST_TIMEOUT=2`, `PROXY_TEST_SAMPLE=1000`, `MAX_PROXIES_TO_KEEP=500`, `ThreadPoolExecutor 150`
* **Errors:** `429` rate-limit short-circuit + retry, `2FA`, `Bad`, `Errors` buckets, `proxy→direct` fallback
* **Limits:** `MAX_FILE_MB=20`, `MAX_PASTED_CREDS=2000`, `MAX_PASTED_PROXIES=5000`, `MAX_HIT_CARDS=150`

---

## 🌐 Proxy Pool

* **Add:** paste `ip:port` / `user:pass@ip:port` in chat or upload `.txt` → auto-detected → `Pool` + `Live` (parallel test 150)
* **Auto:** 12 sources (`jsDelivr`, `proxyscrape`, `multiproxy`, `socks hunter` etc.) — every 5 min when `Auto Load ON`
* **Manual:** `Refresh Auto` (real live bar), `Upload`, `Clear`, `Disable`, `Auto Load ON/OFF`, `Set Threads`

---

## 🔑 Access & Admins

* `BOT_TOKEN` + `OWNER_ID` required (see below). `OWNER_USERNAME` optional (shown in `Access Denied` + `Developed by` is separate).
* `is_admin(uid, username)` checks `OWNER_ID` + `OWNER_IDS` (comma) + `ADMIN_IDS` + `ADMIN_USERNAMES` (ID or @username, case-insensitive).
* `Admins` panel (owner only): `Add Admin` / `Remove Admin` via `ID` or `@username` or forwarded message. `/admins` `/addadmin` `/removeadmin` also.
* Non-admin → `❌ Access Denied` + `💬 Contact Owner` (`https://t.me/<OWNER_USERNAME>` or `tg://user?id=<OWNER_ID>` — auto from env).

---

## 🚀 Run Locally

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env   # set BOT_TOKEN, OWNER_ID
python bot.py
```

## 🔧 Env

| Var | Default | Meaning |
|---|---|---|
| `BOT_TOKEN` | — | Telegram bot token (required) |
| `OWNER_ID` | — | Owner numeric ID (required, auto fills all owner places) |
| `OWNER_USERNAME` | `@unknown` | Owner @username (for Contact Owner link) |
| `THREADS` | `150` | Workers (max 500) |
| `DATA_DIR` | `data` | `store.json` + `pool` |
| `PROXY_REFRESH_MINUTES` | `5` | Auto harvest interval |
| `MAX_PROXIES_TO_KEEP` | `500` | Live kept (`1:1` needs many) |
| `PROXY_TEST_TIMEOUT` | `2` | Per-proxy sec (100x fast) |
| `PROXY_TEST_SAMPLE` | `1000` | Candidates tested |
| `CHECK_TIMEOUT` | `15` | Per API call |
| `BOT_USERNAME` | — | Optional |

Constants in `bot.py`: `MAX_FILE_MB`, `MAX_PASTED_CREDS`, `MAX_HIT_CARDS`, etc.

## ☁️ Deploy on Railway

1. Push `main` (or `arena/01a096ca-crunchyrollchecker`) to GitHub.
2. Railway → New Project → Deploy from GitHub → pick repo/branch.
3. Variables: `BOT_TOKEN`, `OWNER_ID` (e.g. `8756087411`), `OWNER_USERNAME` (e.g. `@owner`), `DATA_DIR=/data` (with volume).
4. Deploy — long polling, no port needed. Volume at `/data` recommended so `store.json` survives.

## 📁 Layout

```
bot.py              # V1 — ~128k, single checker, 100x fast, owner auto
requirements.txt    # python-telegram-bot==22.8, requests, PySocks, beautifulsoup4
railway.json / Procfile / .env.example
data/store.json        # (runtime, gitignored)
data/proxies_pool.txt  # (runtime, gitignored)
miniapp/            # Mini App (if enabled) — index.html/style.css/app.js
```

## 🛡 Notes

* Use only with accounts you own / have rights to test. May violate Crunchyroll ToS.
* Token in env only, never in repo.
* V1 — clean, fast, owner auto-detect, developer branding only on footer: `Developed by : BlazeNXT` (`https://t.me/blaze_nxt`).

