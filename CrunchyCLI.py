import uuid
import requests
import re
from datetime import datetime, timezone
from user_agent import generate_user_agent

def GetRDay(expiry_date):
    expiry = datetime.strptime(expiry_date, "%Y-%m-%d").replace(tzinfo=timezone.utc)
    current = datetime.now(timezone.utc)
    delta = expiry - current
    return max(0, delta.days)

c = input("Enter mail:pass =>  ").strip()

if ':' in c:
    user, pasw = c.split(':', 1)
else:
    print("Invalid format. Use mail:pass")
    exit()

id = str(uuid.uuid4())
userA = generate_user_agent()
login = "https://beta-api.crunchyroll.com/auth/v1/token"
header = {
    "Host": "beta-api.crunchyroll.com",
    "User-Agent": userA,
    "Content-Type": "application/x-www-form-urlencoded",
    "Accept": "application/json",
    "Origin": "https://sso.crunchyroll.com",
    "Referer": "https://sso.crunchyroll.com/login",
    "Accept-Encoding": "gzip, deflate, br",
    "Accept-Language": "en-GB,en-US;q=0.9,en;q=0.8",
    "Sec-Ch-Ua": '"Chromium";v="137", "Not/A)Brand";v="24"',
    "Sec-Ch-Ua-Mobile": "?1",
    "Sec-Ch-Ua-Platform": '"Android"',
    "Sec-Fetch-Site": "same-site",
    "Sec-Fetch-Mode": "cors",
    "Sec-Fetch-Dest": "empty"
}

data = {
    "grant_type": "password",
    "username": user,
    "password": pasw,
    "scope": "offline_access",
    "client_id": "rjs0ltx0dbwkliwxdzdf",
    "client_secret": "4V7rf21-UFXeZ-5XAd0X_QPwr1gu_i1s",
    "device_type": "@xyz",
    "device_id": id,
    "device_name": "Luis"
}

r1 = requests.post(login, headers=header, data=data)
login_r = r1.json()

if "error" in login_r:
    print(f"Login Failed {login_r.get('error')} [❌]")
    exit()
elif "access_token" in login_r:
    act = login_r.get("access_token")
    print(f"Login Done [✅]")
else:
    print("Unknown Resp")
    exit()

get_id = "https://beta-api.crunchyroll.com/accounts/v1/me"
header = {
    "etp-anonymous-id": "64a91812-bb46-40ad-89ca-ff8bb567243d",
    "Accept": "application/json, text/plain, */*",
    "Sec-Ch-Ua": '"Chromium";v="137", "Not/A)Brand";v="24"',
    "Sec-Ch-Ua-Mobile": "?1",
    "Authorization": f"Bearer {act}",
    "User-Agent": userA,
    "Sec-Ch-Ua-Platform": '"Android"',
    "Sec-Fetch-Site": "same-origin",
    "Sec-Fetch-Mode": "cors",
    "Sec-Fetch-Dest": "empty",
    "Referer": "https://www.crunchyroll.com/",
    "Accept-Encoding": "gzip, deflate, br",
    "Accept-Language": "en-GB,en-US;q=0.9,en;q=0.8"
}

r2 = requests.get(get_id, headers=header)
data = r2.json()

aci = data.get("account_id")
exi = data.get("external_id")

emailV = re.search(r'"email_verified":([^,}]*)', r2.text)
if emailV:
    EV = emailV.group(1).strip()
    print(f"Email Verified: {EV}")
else:
    print("Email Verified: N/A")

sts = f"https://beta-api.crunchyroll.com/subs/v1/subscriptions/{exi}/benefits"
header = {
    "Authorization": f"Bearer {act}"
}

r3 = requests.get(sts, headers=header)
data = r3.text

if '"total":0,' not in data:
    print("Status: PREMIUM")
else:
    print("Status: FREE")

country = re.search(r'"subscription_country":"([^"]*)"', data)
if country:
    C = country.group(1).strip()
    print(f"Country: {C}")
else:
    print("Country: Not found")

sub = f"https://beta-api.crunchyroll.com/subs/v3/subscriptions/{aci}"
header = {
    "Authorization": f"Bearer {act}"
}

r4 = requests.get(sub, headers=header)
data = r4.text

active = re.search(r'"is_active":([^,}]*)', data)
if active:
    alive = active.group(1).strip()
    print(f"Active Subscription: {alive}")
else:
    print("Active Subscription: N/A")

sku = re.search(r'"sku":"([^"]*)"', data)
if sku:
    Plan = sku.group(1).strip()
    print(f"Plan: {Plan}")
else:
    print("Plan: N/A")

ex = re.search(r'"expiration_date":"([^"]*)"', data)
if ex:
    Expiry = ex.group(1).strip().split("T")[0]
else:
    ex2 = re.search(r'"next_renewal_date":"([^"]*)"', data)
    if ex2:
        Expiry = ex2.group(1).strip().split("T")[0]
    else:
        Expiry = "N/A"

if Expiry != "N/A":
    Days = GetRDay(Expiry)
    print(f"Expiry Date: {Expiry}")
    print(f"Days Remaining: {Days}")
else:
    print("Expiry Date: N/A")

print(f"Crunchyroll Account Checker")