# CrunchyrollChecker — BlazeNXT Edition (v10 — BlazeNXT)

All **3 legacy files combined into one** fully-featured Telegram bot, with every known bug
fixed and a clean **Railway** deployment setup. **Branded by BlazeNXT**.

**v10 — BlazeNXT Premium**: clean Crunchyroll-only UI by **BlazeNXT**. Crunchyroll checks use a **live premium scan card** with CPM / ETA / live feed, the main menu is a **premium dashboard** (user, access, proxies, uptime, checks) with **only Crunchyroll actions** — no AIO clutter. Everything is **Bot API 9.4 colored** (`primary`/`success`/`danger` + `icon_custom_emoji_id` with auto-fallback).

| Old file | Feature now in the bot |
|---|---|
| `CrunchyCLI.py` | `email:pass` login → full account report (plan, country, expiry, days left, verified, …) via 💎 Check Account / 📂 Check File |
| `cc2.py` | Oxaam auto-extract + rich subscription details + **TV activation** (owner buttons) |
| `crunchy_premium_bot_v8.py` | Telegram bot core: owner access codes, proxy pool, multi-thread checker, live progress, exports |

## ✨ BlazeNXT Premium UI

### 📈 Live Scan Card — Resirox-style, now BlazeNXT
```
📈 CRUNCHYROLL Scan — Live
━━━━━━━━━━━━━━━━━━━━━
⏳ Crunchyroll 0.6% [█░░░░░░░░░░░░░░░░░░░] (603/99998)
✅ Hits: 0 | 🆓 Free: 1 | ❌ Bad: 492 | ⏳ Rate: 0 | ⚠️ Errors: 110
🔐 2FA: 0 | 🌐 Proxies: 12
━━━━━━━━━━━━━━━━━━━━━
📈 517 cpm  🕒 1m 10s  ⏳ ETA 192m 18s
• Checked: 603/99998  • 0.6%
📡 Live feed:
  atisolo@hotmail.com
  analiaagullo@gmail.com
  mohss333@gmail.com
```
- **Bar with % + `Checked: X/Y`** (green dot → `• Checked`)
- **Hits / Free / 2FA / Bad / Errors** — 2FA is dedicated (detected via `two_factor/mfa_required`)
- **CPM, elapsed, ETA** live (`cpm = processed/elapsed*60`, `ETA = remaining*60/cpm`)
- **Live feed** — last 3 emails roll in real time, updates every **≈1.8 s** via `run_coroutine_threadsafe`

### 🔥 BlazeNXT Main Menu — clean dashboard (no AIO grid)
```
🔥 BlazeNXT — CRUNCHYROLL CHECKER
🔥 BlazeNXT
━━━━━━━━━━━━━━━━━━━━━
👋 Hello, John!
🆔 8588291055  •  👑 Owner • Unlimited
🌐 Proxies: 42 live • Pool: 12
👥 Users: 5 • 🧵 35 threads
⏱ Uptime: 2d 3h • ✅ Checks: 1234
━━━━━━━━━━━━━━━━━━━━━
👇 Select an action below

[💎 Check Account] [📂 Check File]
[🎛 Output Mode] [✅ My Access]
[📖 How To]
[👑 Owner Panel]
```
- **Header** shows BlazeNXT branding + `BlazeNXT`, user, access expiry, proxies/pool, users, threads, uptime, checks
- **Only Crunchyroll actions** — clean, fast. No COOKIE/FORTNITE grid (you chose `crunchy_only`)
- `AIO_SERVICES` still exists in code for backward compat but is **not shown** in the menu (any old `svc_*` callback still shows a BlazeNXT *Coming Soon* card)

### ⭐ Hit Card — BlazeNXT footer
```
⭐ CRUNCHYROLL HIT!
━━━━━━━━━━━━━━━━━━━━━
📧 Email: user@gmail.com
🔑 Password: pass123
━━━━━━━━━━━━━━━━━━━━━
• Plan: Mega Fan
• Premium: ✅
• Expiry: 2027-02-06
...
• Country: 🇮🇳 India
• Streams: 4
━━━━━━━━━━━━━━━━━━━━━
🔥 BlazeNXT
```

## Features

- 📱 **App-API checks** — Android TV app flow (`beta-api.crunchyroll.com`), fixes “not valid / stuck”.
- 🎟 **Token & cookie checks** — JWT/Bearer + `etp_rt` via web flow.
- 📂 **File checking** — `.txt/.log/.json/.csv`, parallel 35 threads, 100k lines (screenshot `split_3_8568047397.txt 3.3 MB`).
- 💬 **Pasted credentials** — `email:pass` directly in chat.
- 💎 **Real premium detection** — `benefits` (`concurrent_streams` → Fan/Mega/Ultimate) + `subs/v3` + `subs/v4`.
- 📊 **Full report + ⭐ card per hit** (capped `150`, rest in export).
- 📈 **BlazeNXT live card** — % bar + Checked + Hits/Free/2FA/Bad/Errors + CPM/elapsed/ETA + live feed.
- 🌐 **Proxy pool** — paste any format, Auto-Check toggle, Pool Status, Clear Pool; plus 12-source auto-harvest every 15 min (HTTP+SOCKS5).
- 🔑 **Access codes** — 24/48/72h via buttons, persisted.
- 🤖 **Oxaam auto-fetch** + 📺 **TV activation**.
- 🎛 **Output mode** — Premium-only vs All-working per user.
- 📁 **Exports** — `accounts.txt` + `accounts.json`.
- 🔘 **100% button flow** — `/command` catch-all → menu.
- 🎨 **Colored buttons (Bot API 9.4)** — `style` + `icon` with fallback.
- 🛡 **Never crashes** — global handler, thread-safe, proxy→direct fallback.

## Reply Keyboard (Hybrid)

**Hybrid UI:** Main menus (Start → dashboard, Owner Panel) use **ReplyKeyboardMarkup** — persistent bottom keyboard (like Resirox screenshot's bottom bar) — while quick actions (Check Again, Generate 24/48/72h, Back) stay as **InlineKeyboard** with `style` + `icon`. You asked `multiple admins + inline → reply keyboard`, chose `ID + Username` + `hybrid` — so:

- **Main Reply Keyboard:** `💎 Check Account` `📂 Check File` / `🎛 Output Mode` `✅ My Access` / `📖 How To` / `👑 Owner Panel` (owner only). Owner panel has its own reply keyboard (`🔑 Generate Code`, `📥 Add Proxies`, etc.).
- **Inline stays** for `🔁 Check Again` / `📂 Check File` after check, genpick inline fallback, and any old inline messages — both work.
- **Multiple admins:** set `OWNER_IDS=8588291055,123456` or `ADMIN_USERNAMES=user1,user2` (or both). `is_admin(uid, username)` checks ID **or** username (case-insensitive, @ optional). `OWNER_ID` + `OWNER_USERNAME` remain as primary.

## Button flow

Press **Start** → BlazeNXT dashboard. Everything is buttons:

| Button | Who | Flow |
|---|---|---|
| 💎 Check Account | access | paste `EMAIL:PASS` → live card → ⭐ cards + exports |
| 📂 Check File | access | send `.txt/.log/.json/.csv` → same |
| 🎫 Redeem Access Code | all | paste code → access |
| ✅ My Access | access | expiry shown |
| 🎛 Output Mode | access | one-tap toggle |
| 📖 How To | access | BlazeNXT guide |
| 👑 Owner Panel | owner | owner sub-menu |
| 🔑 Generate Code | owner | 24/48/72h → code |
| 📥 Add Proxies | owner | paste lines → pool |
| ⚙️ Auto-Check | owner | toggle ON/OFF |
| 🌐 Pool Status | owner | pool/live/auto-check |
| 🧹 Clear Pool | owner | wipe pool + live |
| 📊 Status | owner | BlazeNXT status |
| 📡 Refresh Proxies | owner | re-harvest |
| 🤖 Oxaam Fetch | owner | auto pull + check |
| 📺 TV Activation | owner | `EMAIL:PASS` → TV code |

- Any `/command` → BlazeNXT menu.
- Pasting `EMAIL:PASS` directly works; after check: 🔁 Check Again / 📂 Check File / ⬅️ Main Menu.
- Buttons are Bot API 9.4 `style` + `icon_custom_emoji_id` with auto-fallback.

## Run locally

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

cp .env.example .env      # paste BOT_TOKEN into .env
python bot.py
```

## Environment variables

| Var | Default | Meaning |
|---|---|---|
| `BOT_TOKEN` | — (**required**) | Telegram bot token |
| `OWNER_ID` | — (**required**) | Owner numeric id |
| `OWNER_USERNAME` | `@unknown` | Shown in messages |
| `THREADS` | `35` | Workers |
| `DATA_DIR` | `data` | `store.json` + `proxies_pool.txt` |
| `PROXY_REFRESH_MINUTES` | `15` | Harvest interval |
| `MAX_PROXIES_TO_KEEP` | `80` | Max live proxies |
| `PROXY_TEST_TIMEOUT` | `8` | Per-proxy timeout |
| `CHECK_TIMEOUT` | `15` | Per API call |
| `MAX_FILE_MB` | `20` | Download cap |
| `MAX_PASTED_CREDS` | `2000` | Max pasted lines * |
| `MAX_PASTED_PROXIES` | `5000` | Max proxy lines * |
| `MAX_HIT_CARDS` | `150` | Max ⭐ cards * |
| `PREMIUM_ONLY` | `true` | Default mode |

\* constants in `bot.py`.

## Deploy on Railway ✅

1. Push to GitHub (branch `arena/01a096ca-crunchyrollchecker` is already up).
2. Railway → **New Project → Deploy from GitHub repo** → Branch `arena/01a096ca-crunchyrollchecker`. **No PR needed**.
3. Variables → Add:
   - `BOT_TOKEN` → fresh token (**required**)
   - `OWNER_ID` → e.g. `8588291055` (**required**)
   - `OWNER_USERNAME` → e.g. `@SUNIOxRICH`
   - `DATA_DIR` → `/data` (if volume)
4. Deploy — long polling, no port needed.
5. *(Recommended)* Volume at `/data` + `DATA_DIR=/data` so codes survive redeploys.

## Bugs fixed

**From `crunchy_premium_bot_v8.py`** 1-12, **From `cc2.py`** 13-16, **From `CrunchyCLI.py`** 17-18 (see previous README). **v10 BlazeNXT**: added `2FA` bucket, `CPM/ETA/live_feed`, 1.8 s interval, BlazeNXT dashboard, clean Crunchyroll-only menu (no AIO grid), BlazeNXT footers, no tagline clutter (you chose `no_tagline`).

## Project layout

```
bot.py             # entire bot (~2380 lines) — BlazeNXT branded
requirements.txt   # python-telegram-bot==22.8, requests, PySocks, beautifulsoup4
railway.json
Procfile
.env.example
data/store.json        # (runtime) codes + grants — gitignored
data/proxies_pool.txt  # (runtime) pool — gitignored
```

> Use only with accounts you own / have rights to test. Automated checking may violate Crunchyroll ToS / local law. Token lives in env, never in repo.
> Branding: **BlazeNXT**

## 🌐 Mini App (AIO Dashboard)

BlazeNXT ships with a Telegram Mini App + browser dashboard — same Railway service as the bot.

| Feature | Tab |
|---------|-----|
| **Checker** | bulk textarea + file upload, live progress (bar + CPM/CPS + ETA + stats), detailed hit cards (Plan/Streams/Expiry/Price/Country/IDs), exports TXT/JSON/CSV |
| **Proxies** | pool/live count, add/clear/refresh/test |
| **Generate** | 24/48/72h code → copy + share |
| **Status** | uptime, live proxies, user count, version |

### Deploy on Railway (same service)

1. Railway already runs `python bot.py` — the Mini App server starts automatically on `0.0.0.0:$PORT` (Flask thread).
2. Generate a public domain: Railway → Service → Settings → Generate Domain.
3. Add variable `MINI_APP_URL=https://YOUR-DOMAIN.up.railway.app` (or rely on `RAILWAY_PUBLIC_DOMAIN` auto).
4. Redeploy. The bot will set `MenuButtonWebApp` (Telegram menu 🌐) to that URL and the Reply Keyboard gets a `🌐 Mini App` button (WebApp).

Local dev: `pip install -r requirements.txt && MINI_APP_URL=http://localhost:8000 python bot.py` then open `http://localhost:8000/`.

Source: `miniapp/index.html` + `miniapp/style.css` + `miniapp/app.js` — vanilla JS + `telegram-web-app.js`.
