from curl_cffi import requests as cffi_requests
import re
import random
import string
import uuid
import json
import os
import sys
import time
from bs4 import BeautifulSoup
from datetime import datetime, timedelta
import pytz
import requests

G = "\033[92m"; R = "\033[91m"; Y = "\033[93m"; B = "\033[94m"
M = "\033[95m"; C = "\033[96m"; D = "\033[90m"; W = "\033[97m"; X = "\033[0m"

scraper = cffi_requests.Session(impersonate='chrome')

BASE_URL = "https://www.oxaam.com/"
FREE_URL = "https://www.oxaam.com/freeservice.php"

headers = {
    'User-Agent': 'Mozilla/5.0 (Linux; Android 10; K) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/137.0.0.0 Mobile Safari/537.36',
    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8',
    'Accept-Language': 'en-US,en;q=0.9',
    'Content-Type': 'application/x-www-form-urlencoded',
    'Origin': 'https://www.oxaam.com',
    'Referer': 'https://www.oxaam.com/'
}

def generate_uuid():
    return str(uuid.uuid4())

def get_user_agent():
    return "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:140.0) Gecko/20100101 Firefox/140.0"

def make_request(method, url, headers=None, data=None, json_data=None, cookies=None):
    try:
        if method.upper() == "GET":
            response = scraper.get(url, headers=headers, data=data, json=json_data, cookies=cookies, timeout=30)
        elif method.upper() == "POST":
            response = scraper.post(url, headers=headers, data=data, json=json_data, cookies=cookies, timeout=30)
        else:
            raise ValueError(f"Unsupported method: {method}")
        
        return {
            "SOURCE": response.text,
            "RESPONSECODE": str(response.status_code),
            "COOKIES": response.cookies.get_dict(),
            "JSON": response.json() if response.headers.get('content-type', '').startswith('application/json') else None
        }
    except Exception as e:
        return {"SOURCE": f"Error: {str(e)}", "RESPONSECODE": "ERROR", "COOKIES": {}, "JSON": None}

def parse_between(text, left_delim, right_delim):
    try:
        start = text.find(left_delim)
        if start == -1:
            return ""
        start += len(left_delim)
        end = text.find(right_delim, start)
        if end == -1:
            return ""
        return text[start:end]
    except:
        return ""

def extract_crunchyroll():
    name = ''.join(random.choices(string.ascii_letters, k=8))
    email = f"{name.lower()}_{random.randint(100,999)}@gmail.com"
    password = f"{''.join(random.choices(string.ascii_letters, k=8))}{random.randint(100,999)}@{''.join(random.choices(string.ascii_letters, k=4))}"

    data = {
        'name': name,
        'email': email,
        'phone': '9' + ''.join(random.choices(string.digits, k=9)),
        'password': password,
        'country': 'India'
    }

    scraper.post(BASE_URL, data=data, headers=headers)
    resp = scraper.get(FREE_URL, headers={**headers, "Referer": BASE_URL + "dashboard.php"})

    soup = BeautifulSoup(resp.text, 'html.parser')
    
    for details in soup.find_all('details'):
        summary = details.find('summary')
        if not summary:
            continue
        
        title = summary.get_text().strip()
        
        if 'krunshy' in title.lower() or 'crunchy' in title.lower():
            content = str(details)
            
            emails = re.findall(r'[\w\.-]+@[\w\.-]+\.\w+', content)
            if emails:
                crunchy_email = emails[0]
            else:
                lines = resp.text.split('\n')
                if len(lines) > 403:
                    line_403 = lines[402]
                    match = re.search(r'([a-zA-Z0-9._%+-]+@gmail\.com):([^\s<>"]+)', line_403)
                    if match:
                        crunchy_email = match.group(1)
                        crunchy_password = match.group(2)
                        return crunchy_email, crunchy_password
            
            pass_match = re.search(r'[Pp]ass(?:word)?\s*[:=]\s*([^\s<>"\'{},;]+)', content)
            if pass_match:
                crunchy_password = pass_match.group(1)
            else:
                json_match = re.search(r'"password"\s*:\s*"([^"]+)"', content)
                if json_match:
                    crunchy_password = json_match.group(1)
                else:
                    text_match = re.search(r'(?i)password[:\s]+([a-zA-Z0-9@#!$%^&*]{6,})', details.get_text())
                    if text_match:
                        crunchy_password = text_match.group(1)
            
            return crunchy_email, crunchy_password
    
    return None, None

def get_account_details(email, password):
    session = requests.Session()
    
    try:
        login_url = "https://sso.crunchyroll.com/api/login"
        login_headers = {
            "User-Agent": get_user_agent(),
            "Accept": "*/*",
            "Accept-Language": "en-US,en;q=0.5",
            "Accept-Encoding": "gzip, deflate, br, zstd",
            "Content-Type": "application/json",
            "Origin": "https://sso.crunchyroll.com",
            "Referer": "https://sso.crunchyroll.com/login?return_url=%2Fauthorize%3Fclient_id%3Dnoaihdevm_6iyg0a8l0q%26redirect_uri%3Dhttps%253A%252F%252Fwww.crunchyroll.com%252Fcallback%26response_type%3Dcookie%26state%3D%252F%253Fsrsltid%253DAfmBOoqn5bnvWJ78FbqtjzUi67cg6vitCYf_ttqw104OgWJ1iId2h3j2"
        }
        
        login_data = {
            "email": email,
            "password": password,
            "recaptchaToken": "",
            "eventSettings": {}
        }
        
        login_response = session.post(login_url, headers=login_headers, json=login_data, timeout=30)
        
        if login_response.status_code != 200:
            return None
        
        device_id = login_response.cookies.get("device_id", "")
        etp_rt = login_response.cookies.get("etp_rt", "")
        
        token_url = "https://www.crunchyroll.com/auth/v1/token"
        token_headers = {
            "User-Agent": get_user_agent(),
            "Accept": "application/json, text/plain, */*",
            "Accept-Language": "en-US,en;q=0.5",
            "Accept-Encoding": "gzip, deflate",
            "Content-Type": "application/x-www-form-urlencoded",
            "Authorization": "Basic bm9haWhkZXZtXzZpeWcwYThsMHE6",
            "Origin": "https://www.crunchyroll.com",
            "Referer": "https://www.crunchyroll.com/",
            "ETP-Anonymous-Id": generate_uuid()
        }
        
        token_data = {
            "device_id": device_id,
            "device_type": "Firefox on Windows",
            "grant_type": "etp_rt_cookie"
        }
        
        token_response = session.post(token_url, headers=token_headers, data=token_data, timeout=30)
        
        if token_response.status_code != 200:
            return None
        
        token_json = token_response.json()
        access_token = token_json.get('access_token', '')
        account_id = token_json.get('account_id', '')
        
        profile_url = "https://www.crunchyroll.com/accounts/v1/me/multiprofile"
        profile_headers = {
            "User-Agent": get_user_agent(),
            "Accept": "application/json, text/plain, */*",
            "Accept-Language": "en-MM,en-GB;q=0.9,en-US;q=0.8,en;q=0.7",
            "Authorization": f"Bearer {access_token}",
            "ETP-Anonymous-Id": generate_uuid(),
            "Referer": "https://www.crunchyroll.com/discover"
        }
        
        profile_response = session.get(profile_url, headers=profile_headers, timeout=30)
        profile_data = profile_response.json() if profile_response.status_code == 200 else {}
        
        sub_url = f"https://www.crunchyroll.com/subs/v4/accounts/{account_id}/subscriptions"
        sub_headers = {
            "User-Agent": get_user_agent(),
            "Accept": "application/json, text/plain, */*",
            "Accept-Language": "en-MM,en-GB;q=0.9,en-US;q=0.8,en;q=0.7",
            "Authorization": f"Bearer {access_token}",
            "Referer": "https://www.crunchyroll.com/account/membership"
        }
        
        sub_response = session.get(sub_url, headers=sub_headers, timeout=30)
        sub_data = sub_response.json() if sub_response.status_code == 200 else {}
        
        product_url = "https://www.crunchyroll.com/subs/v2/products/cr_premium.1_month"
        product_headers = {
            "User-Agent": get_user_agent(),
            "Accept": "application/json, text/plain, */*",
            "Accept-Language": "en-MM,en-GB;q=0.9,en-US;q=0.8,en;q=0.7",
            "Authorization": f"Bearer {access_token}",
            "Referer": "https://www.crunchyroll.com/discover"
        }
        
        product_response = session.get(product_url, headers=product_headers, timeout=30)
        product_data = product_response.json() if product_response.status_code == 200 else {}
        
        profiles = profile_data.get('profiles', [])
        primary_profile = None
        for p in profiles:
            if p.get('is_primary', False):
                primary_profile = p
                break
        
        if not primary_profile and profiles:
            primary_profile = profiles[0]
        
        subscriptions = sub_data.get('subscriptions', [])
        subscription = subscriptions[0] if subscriptions else {}
        plan = subscription.get('plan', {})
        tier = plan.get('tier', {})
        price = plan.get('price', {})
        payment = sub_data.get('currentPaymentMethod', {})
        
        next_renewal = subscription.get('nextRenewalDate', '')
        days_left = "N/A"
        if next_renewal:
            try:
                renewal_date = datetime.strptime(next_renewal.replace('Z', '+00:00'), "%Y-%m-%dT%H:%M:%S%z")
                now = datetime.now(pytz.UTC)
                days_left = max(0, (renewal_date - now).days)
            except:
                pass
        
        profile_names = [p.get('profile_name', '') for p in profiles if p.get('profile_name')]
        
        benefits = plan.get('benefits', [])
        max_streams = "N/A"
        for benefit in benefits:
            if benefit.get('name') == 'concurrent_streams.4':
                max_streams = benefit.get('text', '4')
            elif benefit.get('name') == 'concurrent_streams.1':
                max_streams = benefit.get('text', '1')
        
        country_map = {
            "IN": "India", "US": "United States", "GB": "United Kingdom",
            "CA": "Canada", "AU": "Australia", "DE": "Germany",
            "FR": "France", "BR": "Brazil", "JP": "Japan"
        }
        
        country_code = payment.get('countryCode', '') or plan.get('countryCode', '')
        country = country_map.get(country_code, country_code or 'Unknown')
        
        cycle = price.get('cycleDuration', plan.get('cycle_duration', ''))
        billing_map = {"P1D": "Daily", "P1W": "Weekly", "P1M": "Monthly", "P3M": "3 Months", "P1Y": "Annual"}
        billing = billing_map.get(cycle, cycle or 'Unknown')
        
        return {
            "email": email,
            "password": password,
            "active": subscription.get('status') == 'active',
            "plan": tier.get('text', 'Unknown'),
            "days_left": days_left,
            "country": country,
            "country_code": country_code,
            "profile_name": primary_profile.get('profile_name', 'Unknown') if primary_profile else 'Unknown',
            "verified": payment.get('status') == 'verified',
            "created": subscription.get('startDate', 'Unknown')[:10] if subscription.get('startDate') else 'Unknown',
            "free_trial": plan.get('activeFreeTrial', False),
            "max_profiles": profile_data.get('max_profiles', 'N/A'),
            "streams": max_streams,
            "currency": price.get('currencyCode', 'Unknown'),
            "billing": billing,
            "last_payment": product_data.get('amount', 'N/A'),
            "last_currency": product_data.get('currency_code', ''),
            "last_billed": subscription.get('startDate', 'Unknown')[:10] if subscription.get('startDate') else 'Unknown',
            "last_device": "Chrome on Windows (Falkenstein, Germany)",
            "last_seen": datetime.now().strftime('%Y-%m-%d'),
            "plan_type": plan.get('planType', 'Unknown').capitalize(),
            "plan_price": price.get('amount', 'N/A'),
            "plan_currency": price.get('currencyCode', ''),
            "payment_method": payment.get('paymentMethodType', 'Unknown').replace('_', ' ').title(),
            "payment_source": payment.get('paymentMethodType', 'Unknown').replace('_', ' ').title(),
            "card_info": payment.get('name', 'Unknown'),
            "card_status": payment.get('status', 'Unknown').capitalize(),
            "card_expiry": payment.get('expiresAt', 'Unknown'),
            "auto_renew": subscription.get('subscriptionQualifier') == 'RECURRING',
            "member_since": subscription.get('startDate', 'Unknown')[:10] if subscription.get('startDate') else 'Unknown',
            "active_devices": len(profiles),
            "profiles": profile_names,
            "language": primary_profile.get('preferred_communication_language', 'Unknown') if primary_profile else 'Unknown',
            "access_token": access_token
        }
        
    except Exception as e:
        return None

def activate_tv(access_token, user_code):
    user_agent = get_user_agent()
    
    activation_headers = {
        "User-Agent": user_agent,
        "Accept": "application/json, text/plain, */*",
        "Accept-Language": "en-US,en;q=0.9",
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/json",
        "Origin": "https://www.crunchyroll.com",
        "Referer": "https://www.crunchyroll.com/activate",
        "ETP-Anonymous-Id": generate_uuid()
    }

    activation_data = {"user_code": user_code}

    activation_response = scraper.post("https://www.crunchyroll.com/auth/v1/device",
                                       headers=activation_headers, json=activation_data)

    if activation_response.status_code == 200:
        print("\n✅ TV ACTIVATION SUCCESSFUL!")
        return True
    else:
        print("\n❌ TV ACTIVATION FAILED")
        try:
            error = activation_response.json()
            if error and 'code' in error:
                print(f"Error: {error['code']}")
        except:
            pass
        return False

def main():
    email, password = extract_crunchyroll()
    
    if not email or not password:
        print("❌ Failed to extract credentials!")
        return
    
    print("\n" + "="*35)
    print("✅ CRUNCHYROLL AUTO TV LOGIN")
    print("="*35)
    
    details = get_account_details(email, password)
    
    if not details:
        print("❌ Failed to get account details!")
        return
    
    print("\n📊 Account Details")
    print(f"- Active: {'✅ Yes' if details['active'] else '❌ No'}")
    print(f"- Plan: {details['plan']}")
    print(f"- Expires In: {details['days_left']} days left" if details['days_left'] != "N/A" else "- Expires In: N/A")
    print(f"- Country: {details['country']} {'🇺🇸' if details['country_code'] == 'US' else '🌍'}")
    
    print("\n👤 Account Info")
    print(f"- Name: {details['profile_name']}")
    print(f"- Verified: {'Yes' if details['verified'] else 'No'}")
    print(f"- Created: {details['created']}")
    print(f"- Free Trial: {'True' if details['free_trial'] else 'False'}")
    print(f"- Max Profiles: {details['max_profiles']}")
    
    print("\n💳 Subscription")
    print(f"- Sub Plan: {details['plan']} MEMBER")
    print(f"- Max Streams: {details['streams']}")
    print(f"- Currency: {details['currency']}")
    print(f"- Billing: {details['billing']}")
    print(f"- Last Payment: {details['last_payment']} {details['last_currency']}")
    print(f"- Last Billed: {details['last_billed']}")
    print(f"- Last Device: {details['last_device']}")
    print(f"- Last Seen: {details['last_seen']}")
    print(f"- Plan Type: {details['plan_type']}")
    print(f"- Plan Price: {details['plan_price']} {details['plan_currency']} / {details['billing'].lower()}")
    print(f"- Payment Method: {details['payment_method']} / Web")
    print(f"- Payment Source: {details['payment_source']}")
    print(f"- Card Info: {details['card_info']}")
    print(f"- Card Status: {details['card_status']}")
    print(f"- Card Expiry: {details['card_expiry']}")
    print(f"- Auto Renewal: {'Yes' if details['auto_renew'] else 'No'}")
    print(f"- Member Since: {details['member_since']}")
    print(f"- Active Devices: {details['active_devices']}")
    
    print(f"\n👥 Profiles ({details['active_devices']})")
    print(f"- {', '.join(details['profiles'])}")
    print(f"- Language: {details['language']}")
    
    print("\n" + "━"*30)
    print("="*30)
    
    print("\n" + "━"*30)
    print("1. Mobile Login (show credentials)")
    print("2. TV Activation (enter code)")
    choice = input("\nSelect (1/2): ").strip()

    if choice == "1":
        print("\n📱 MOBILE LOGIN CREDENTIALS")
        print(f"   Email:    {details['email']}")
        print(f"   Password: {details['password']}")
        print("\n   Open Crunchyroll app → Login → Enter above credentials")
    elif choice == "2":
        user_code = input("\nEnter TV activation code :").strip().upper()
        if user_code and details.get('access_token'):
            print("\n[TV] Activating TV...")
            activate_tv(details['access_token'], user_code)
        elif user_code:
            print("❌ No access token available!")
    else:
        print("\n📱 MOBILE LOGIN CREDENTIALS")
        print(f"   Email:    {details['email']}")
        print(f"   Password: {details['password']}")

if __name__ == "__main__":
    main()
