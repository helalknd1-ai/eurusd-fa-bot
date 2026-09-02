#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
دستیار خبر فاندامنتال یورو/دلار – نسخه نهایی (ارتقا یافته برای تریدرها)
اضافه شدن: سیستم ارزیابی TP/SL (۲۰ پیپ)، فیلتر اخبار تکراری، اصلاح ترجمه‌ها و خطاهای AI
"""

import os
import re
import json
import random
import hashlib
import argparse
import requests
import feedparser
from datetime import datetime, timezone, timedelta
from bs4 import BeautifulSoup

try:
    from dotenv import load_dotenv
    load_dotenv()
except Exception:
    pass

try:
    import jdatetime
    HAS_JALALI = True
except Exception:
    HAS_JALALI = False

# ---------- هوش مصنوعی ----------
try:
    from groq import Groq
    GROQ_API_KEY = os.getenv("GROQ_API_KEY", "")
    HAS_GROQ = bool(GROQ_API_KEY)
    if HAS_GROQ:
        groq_client = Groq(api_key=GROQ_API_KEY)
except Exception as e:
    HAS_GROQ = False
    print("Groq در دسترس نیست:", e)

# ---------- تنظیمات ----------
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN", "PUT_YOURS")
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "PUT_YOURS")
SEND_VOICE = False

VOICE_NAME = os.getenv("VOICE_NAME", "fa-IR-DilaraNeural")
VOICE_RATE = os.getenv("VOICE_RATE", "-12%")
VOICE_PITCH = os.getenv("VOICE_PITCH", "+0Hz")

NEWS_IMPACT_LEVELS = os.getenv("NEWS_IMPACT", "High,Medium").split(",")

CURRENT_NARRATIVE_OVERRIDE = os.getenv("MARKET_NARRATIVE", "")

def build_market_narrative(news_text):
    if CURRENT_NARRATIVE_OVERRIDE:
        return CURRENT_NARRATIVE_OVERRIDE
    if not HAS_GROQ:
        return "روایت بازار در دسترس نیست."
    try:
        messages = [
            {"role": "system", "content": (
                "تو تحلیل‌گر ارشد فارکس هستی. بر اساس اخبار، روایت غالب فعلی بازار یورو/دلار را "
                "در ۲ تا ۳ جمله کوتاه فارسی خلاصه کن. "
                "فقط بگو الان بازار روی چه موضوعی تمرکز دارد و چه عاملی حرکت‌دهنده اصلی است. "
                "بدون کلمه انگلیسی."
            )},
            {"role": "user", "content": f"اخبار امروز:\n{news_text[:2000]}"},
        ]
        result = call_groq(messages, temperature=0.1, max_tokens=200)
        if result:
            return clean_foreign_chars(result)
    except Exception as ex:
        print("خطا در ساخت روایت بازار:", ex)
    return "روایت بازار در دسترس نیست."

SEEN_FILE = "seen_events.json"
PREDICTIONS_FILE = "predictions.json"
LAST_VIEW_FILE = "last_view.json"
BATCH_FILE = "news_batch.json"

TEHRAN_TZ = timezone(timedelta(hours=3, minutes=30))

AI_MODELS = [
    "openai/gpt-oss-120b",
    "qwen/qwen3.6-27b",
    "openai/gpt-oss-20b",
]

REASONING_MODELS = {"openai/gpt-oss-120b", "openai/gpt-oss-20b"}

SCHEDULES = {
    "morning": {"hour": 10, "minute": 10, "label": "🌅 پیش‌گشایش لندن (ثبت جهت)"},
    "us_preopen": {"hour": 16, "minute": 0, "label": "🌆 قبل بازار آمریکا"},
    "evening": {"hour": 21, "minute": 30, "label": "🌙 ارزیابی و جمع‌بندی روزانه"},
    "watch": {"hour": 0, "minute": 0, "label": "🔔 رصد اخبار فوری"},
    "manual": {"hour": 0, "minute": 0, "label": "🔧 اجرای دستی"},
    "weekly": {"hour": 20, "minute": 0, "label": "📊 گزارش هفتگی"},
    "verify": {"hour": 0, "minute": 0, "label": "🎯 بررسی دقت"},
}

SOURCES = {
    "fxstreet_rss": "https://www.fxstreet.com/news/forex/feed",
    "forexlive": "https://www.forexlive.com/feed/",
    "ecb_press": "https://www.ecb.europa.eu/rss/press.html",
    "fed_press": "https://www.federalreserve.gov/feeds/press_all.xml",
    "investing": "https://www.investing.com/rss/news_1.rss",
}

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/126.0 Safari/537.36"
    ),
    "Accept-Language": "en-US,en;q=0.9,fa;q=0.8",
}

SPEECH_INDICATORS = [
    "speech", "testimony", "statement", "press conference",
    "says", "speaks", "told", "warns", "urges", "remarks",
    "prepared text", "q&a", "qa", "questions",
]

# ==================================================================
# قوانین اقتصادی جامع EUR/USD
# ==================================================================
ECON_RULES = """قوانین اقتصادی EUR/USD (مطلقاً و دقیقاً رعایت کن):

۱. نفت (قانون مطلق):
- اروپا واردکننده خالص نفت است
- نفت گران = همیشه ضرر اروپا = نزولی یورو
- نفت ارزان = همیشه سود اروپا = صعودی یورو

۲. تورم آمریکا و نرخ بهره:
- تورم آمریکا در حال کاهش = دلار ضعیف = صعودی یورو
- تورم آمریکا در حال افزایش = دلار قوی = نزولی یورو

۳. بحران ژئوپلیتیک (قانون مطلق):
- جنگ، تنش، حمله = همیشه دلار پناهگاه امن = دلار قوی = نزولی یورو
- بحران حل شود = دلار ضعیف = صعودی یورو

۴. داده‌های اقتصادی آمریکا:
- داده قوی = دلار قوی = نزولی یورو
- داده ضعیف = دلار ضعیف = صعودی یورو

۵. داده‌های اقتصادی اروپا:
- داده قوی اروپا = یورو قوی = صعودی
- داده ضعیف اروپا = یورو ضعیف = نزولی

۶. بانک‌های مرکزی:
- فدرال رزرو سخت‌گیرانه = دلار قوی = نزولی یورو
- فدرال رزرو ملایم = دلار ضعیف = صعودی یورو

۷. شاخص‌ها:
- DXY بالا = نزولی یورو / بازده اوراق بالا = نزولی یورو / طلا بالا = صعودی یورو

۸. احساسات ریسک:
- ریسک‌پذیری = دلار ضعیف = صعودی یورو
- ریسک‌گریزی = دلار قوی = نزولی یورو

۹. قانون مطلق هم‌خوانی (بسیار مهم):
- توصیه نهایی حتماً باید با جهت تعیین‌شده هم‌خوان باشد
- اگر جهت صعودی است، مطلقاً نگوی بفروش
- اگر جهت نزولی است، مطلقاً نگوی بخر

۱۰. قانون مطلق عدم تکرار:
- هر نکته را فقط یک بار بگو و جملات را تکرار نکن.

۱۱. قانون پیش‌خور شدن (Priced In):
- اگر خبر مهمی آمد اما اوراق ۱۰ ساله واکنش نداد، یعنی خبر پیش‌خور شده است.

۱۲. قانون واگرایی و فیک‌اوت:
- حالت طبیعی: اگر EUR/USD صعودی است، DXY باید نزولی باشد.
- حالت تله: اگر هر دو با هم هم‌جهت بودند، هشدار تله نقدینگی بده.

۱۳. ممنوعیت‌ها و واژگان (قانون بسیار حیاتی):
- اکیداً ممنوع: به هیچ وجه درباره ارزهای دیجیتال، کریپتو، بیت‌کوین یا ETFهای آن‌ها در تحلیل صحبت نکن.
- واژگان صحیح: از عبارت "پوزیشن خرید" و "پوزیشن فروش" استفاده کن (به جای موقعیت طولانی/کوتاه). از "دارایی‌های پرریسک" استفاده کن (به جای خطرپذیر)."""

BREAKING_KEYWORDS = [
    "surges", "plunges", "plummets", "spikes", "jumps", "slides",
    "crashes", "soars", "tumbles", "slumps", "collapses", "skyrockets",
    "selloff", "sell-off", "rallies", "rally",
    "breaking", "urgent", "shock", "unexpected", "surprise",
    "cuts rates", "raises rates", "rate decision",
    "beats expectations", "misses expectations",
    "attack", "strikes", "sanctions", "invasion", "retaliation",
]

ROUTINE_KEYWORDS = [
    "preview", "outlook", "wrap", "recap", "what to expect",
    "weekly", "monthly", "analysis", "digest", "roundup",
    "calendar", "schedule", "watch list", "watchlist",
]

SPEAKERS = {
    "powell": "پاول (رئیس فدرال رزرو)",
    "lagarde": "لاگارد (رئیس بانک مرکزی اروپا)",
}

COUNTRY_FA = {
    "USD": "آمریکا", "EUR": "یوروزون", "EMU": "یوروزون",
    "US": "آمریکا", "EU": "یوروزون",
}

TITLE_TRANSLATIONS = {
    "core cpi m/m": "تورم هسته‌ای (ماهانه)",
    "core cpi y/y": "تورم هسته‌ای (سالانه)",
    "cpi m/m": "تورم مصرف‌کننده (ماهانه)",
    "cpi y/y": "تورم مصرف‌کننده (سالانه)",
    "core pce": "شاخص تورم پایه (Core PCE)",
    "core pce price index": "شاخص تورم پایه (Core PCE)",
    "core pce price index m/m": "تورم پایه ماهانه (Core PCE)",
    "core pce price index y/y": "تورم پایه سالانه (Core PCE)",
    "pce price index": "شاخص تورم (PCE)",
    "nonfarm payrolls": "اشتغال غیرکشاورزی",
    "nfp": "اشتغال غیرکشاورزی",
    "unemployment rate": "نرخ بیکاری",
    "initial jobless claims": "ادعای اولیه بیکاری",
    "gdp": "رشد اقتصادی",
    "gdp growth": "رشد اقتصادی",
    "retail sales": "خرده‌فروشی",
    "interest rate": "نرخ بهره",
    "rate decision": "تصمیم نرخ بهره",
    "fed chair": "رئیس فدرال رزرو",
    "fomc statement": "بیانیه فدرال رزرو",
    "consumer confidence": "اعتماد مصرف‌کننده",
    "ism manufacturing": "شاخص مدیران خرید صنایع",
    "pmi manufacturing": "شاخص PMI تولید",
    "pmi services": "شاخص PMI خدمات",
}

# ==================================================================
# بخش ۱: پیام‌های انگیزشی
# ==================================================================
MOTIVATIONAL_GENERAL = ["💎 معامله‌گر حرفه‌ای با صبر و نظم سود می‌کند.", "🎯 مدیریت ریسک، کلید بقای شما در بازار است."]
MOTIVATIONAL_BULLISH = ["🟢 روند صعودی به‌کنار، فرصت خوبی در راه است!"]
MOTIVATIONAL_BEARISH = ["🔴 بازار نزولی هم فرصت دارد — فقط هوشمندانه باش."]
MOTIVATIONAL_NEUTRAL = ["🟡 بازار نامشخص است — صبر هم یک استراتژی است."]
MOTIVATION_VIEW_CHANGE = ["🔄 بازار جهت عوض کرده — انعطاف‌پذیر باش!"]
MOTIVATION_MORNING = ["☀️ روز جدید، فرصت‌های تازه. آماده‌ای؟"]
MOTIVATION_EVENING = ["🔭 امروز را جمع‌بندی کن و فردا قوی‌تر برگرد."]

def get_motivation(direction=None, slot=None, view_changed=False):
    if view_changed: return random.choice(MOTIVATION_VIEW_CHANGE)
    if slot == "morning": return random.choice(MOTIVATION_MORNING)
    if slot == "evening": return random.choice(MOTIVATION_EVENING)
    if direction == "صعودی": return random.choice(MOTIVATIONAL_BULLISH)
    elif direction == "نزولی": return random.choice(MOTIVATIONAL_BEARISH)
    elif direction == "خنثی": return random.choice(MOTIVATIONAL_NEUTRAL)
    return random.choice(MOTIVATIONAL_GENERAL)

# ==================================================================
# بخش ۲: توابع کمکی
# ==================================================================
def clean_html_text(text):
    try:
        return BeautifulSoup(str(text), "html.parser").get_text(" ", strip=True)
    except Exception:
        return str(text or "").strip()

def clean_foreign_chars(text):
    if not text: return ""
    result = []
    for ch in str(text):
        code = ord(ch)
        if 0x0600 <= code <= 0x06FF or 0x0041 <= code <= 0x007A or code in (32, 46, 44, 45, 47, 58, 59, 33, 63, 40, 41, 37, 43) or 0x06F0 <= code <= 0x06F9 or 0x0030 <= code <= 0x0039 or code >= 0x1F000 or ch == "\n":
            result.append(ch)
        else:
            result.append(" ")
    text = "".join(result)
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()

def strip_think_tags(text):
    if not text: return ""
    text = re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL)
    text = re.sub(r"<think>.*", "", text, flags=re.DOTALL)
    return text.strip()

def translate_title(title):
    low = title.lower().strip()
    for eng, fa in TITLE_TRANSLATIONS.items():
        if eng in low:
            return fa
    return title

def to_fa_digits(text):
    fa = "۰۱۲۳۴۵۶۷۸۹"
    for i, d in enumerate("0123456789"):
        text = str(text).replace(d, fa[i])
    return text

WEEKDAYS_FA = {"Monday": "دوشنبه", "Tuesday": "سه‌شنبه", "Wednesday": "چهارشنبه", "Thursday": "پنج‌شنبه", "Friday": "جمعه", "Saturday": "شنبه", "Sunday": "یکشنبه"}

def get_date_fa():
    now = datetime.now(TEHRAN_TZ)
    wd_en = now.strftime("%A")
    wd_fa = WEEKDAYS_FA.get(wd_en, wd_en)
    if HAS_JALALI:
        jd = jdatetime.datetime.fromgregorian(datetime=now)
        return f"{wd_fa} {jd.strftime('%d')} {jd.strftime('%B')} {jd.strftime('%Y')}", f"{jd.strftime('%d %b')}"
    return f"{wd_fa} {now.strftime('%Y-%m-%d')}", f"{now.strftime('%d %b')}"

def get_time_fa():
    return to_fa_digits(datetime.now(TEHRAN_TZ).strftime("%H:%M"))

def normalize_voice_text(text):
    text = str(text or "").strip()
    for ch in ["/", "|", "-", "_", "•", "📌", "📅", "📰", "⚖️", "🤖", "🔔", "🌅", "🌆", "🌙", "🟢", "🟡", "🔴", "🚨", "📊", "⏰", "🔄", "🎤", "💡", "✅", "❌", "⚪", "━", "💪", "📉", "📈", "💎", "🎯", "⚡", "🌟", "🏔️", "🔮", "🛡️", "🌈", "🚀", "✨", "🌊", "🧠", "🧘", "⏳", "☀️", "🌄", "🔭", "💫", "👤", "🌐"]:
        text = text.replace(ch, " ")
    text = text.replace("ي", "ی").replace("ك", "ک")
    return re.sub(r"\s+", " ", text).strip()

def is_relevant_news(text):
    low = clean_html_text(text).lower()
    direct = ["eur/usd", "eurusd", "euro", "usd", "dollar", "ecb", "fed", "fomc", "powell", "lagarde", "eurozone", "treasury yields", "dxy"]
    macro = ["inflation", "cpi", "pce", "nfp", "payroll", "employment", "unemployment", "jobless claims", "pmi", "gdp", "retail sales", "interest rate", "rate cut", "rate hike", "yield"]
    region = ["us", "u.s.", "united states", "america", "euro area", "eurozone", "europe", "germany", "france"]
    geo = ["iran", "hormuz", "war", "oil", "geopolitical", "tariff"]

    if any(k in low for k in direct): return True
    if any(k in low for k in macro) and any(k in low for k in region): return True
    if any(k in low for k in geo) and any(k in low for k in ["dollar", "euro", "fed", "ecb", "yield", "risk"]): return True
    return False

def is_speech_related(text):
    low = clean_html_text(text).lower()
    return any(k in low for k in SPEECH_INDICATORS)

def is_breaking_news(text):
    low = clean_html_text(text).lower()
    if any(k in low for k in ROUTINE_KEYWORDS): return False
    if is_speech_related(text): return True
    if any(k in low for k in BREAKING_KEYWORDS): return True
    return False

def detect_speaker(text):
    low = clean_html_text(text).lower()
    for eng, fa in SPEAKERS.items():
        if eng in low: return fa
    return ""

# ==================================================================
# بخش ۳: مدیریت فایل
# ==================================================================
def load_json(filepath, default=None):
    try:
        if os.path.exists(filepath):
            with open(filepath, "r", encoding="utf-8") as f:
                return json.load(f)
    except Exception: pass
    return default if default is not None else {}

def save_json(filepath, data):
    try:
        with open(filepath, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    except Exception as ex: print(f"خطا در نوشتن {filepath}:", ex)

def load_seen():
    data = load_json(SEEN_FILE, {})
    today = datetime.now(TEHRAN_TZ).strftime("%Y-%m-%d")
    return {k: v for k, v in data.items() if v.get("date", "").startswith(today)}

def save_seen(seen): save_json(SEEN_FILE, seen)

# ==================================================================
# بخش ۴: قیمت + بازارهای موازی + کندل ۱۵ دقیقه‌ای
# ==================================================================
def get_eurusd_price():
    try:
        url = "https://query1.finance.yahoo.com/v8/finance/chart/EURUSD=X"
        r = requests.get(url, headers=HEADERS, timeout=8)
        if r.status_code == 200:
            price = r.json().get("chart", {}).get("result", [])[0].get("meta", {}).get("regularMarketPrice")
            if price: return round(price, 5)
    except Exception: pass
    return None

def get_market_assets():
    """دریافت مجزای قیمت بازارهای موازی برای جلوگیری از تداخل"""
    assets = {"DXY (شاخص دلار)": "DX-Y.NYB", "US10Y (اوراق 10 ساله)": "^TNX", "Gold (طلا)": "GC=F"}
    results = {}
    for name, ticker in assets.items():
        try:
            url = f"https://query1.finance.yahoo.com/v8/finance/chart/{ticker}"
            r = requests.get(url, headers=HEADERS, timeout=5)
            if r.status_code == 200:
                price = r.json().get("chart", {}).get("result", [])[0].get("meta", {}).get("regularMarketPrice")
                if price:
                    results[name] = round(price, 3)
                else:
                    results[name] = "نامشخص"
        except Exception:
            results[name] = "نامشخص"
            
    try:
        url_eur = "https://query1.finance.yahoo.com/v8/finance/chart/EURUSD=X"
        r_eur = requests.get(url_eur, headers=HEADERS, timeout=5)
        if r_eur.status_code == 200:
            meta = r_eur.json().get("chart", {}).get("result", [])[0].get("meta", {})
            current = meta.get("regularMarketPrice")
            prev_close = meta.get("chartPreviousClose")
            if current and prev_close:
                trend = "صعودی (بالاتر از روز قبل)" if current > prev_close else "نزولی (پایین‌تر از روز قبل)"
                results["وضعیت چارت امروز EUR/USD"] = trend
    except Exception: pass
    return results

def check_tp_sl_hits(predict_timestamp_iso, direction, entry_price):
    """
    اسکن کندل‌های ۱۵ دقیقه‌ای بعد از لحظه پیش‌بینی 
    برای تشخیص برخورد به حد سود (۲۰ پیپ) یا حد ضرر (۲۰ پیپ)
    """
    try:
        url = "https://query1.finance.yahoo.com/v8/finance/chart/EURUSD=X"
        params = {"range": "5d", "interval": "15m"}
        r = requests.get(url, params=params, headers=HEADERS, timeout=10)
        
        if r.status_code != 200: return None, 0
        result = r.json().get("chart", {}).get("result", [])
        if not result: return None, 0
            
        timestamps = result[0].get("timestamp", [])
        quotes = result[0].get("indicators", {}).get("quote", [{}])[0]
        highs = quotes.get("high", [])
        lows = quotes.get("low", [])
        
        pred_dt = datetime.fromisoformat(predict_timestamp_iso)
        pred_ts = pred_dt.timestamp()
        
        target_pips = 20.0
        target_price_diff = target_pips / 10000.0
        
        for ts, h, l in zip(timestamps, highs, lows):
            if not h or not l: continue
            if ts < pred_ts: continue
            
            if direction == "صعودی":
                if h >= entry_price + target_price_diff: return "correct", target_pips
                if l <= entry_price - target_price_diff: return "wrong", -target_pips
            elif direction == "نزولی":
                if l <= entry_price - target_price_diff: return "correct", target_pips
                if h >= entry_price + target_price_diff: return "wrong", -target_pips
                    
        return None, 0
    except Exception:
        return None, 0

# ==================================================================
# بخش ۵: سیستم ردیابی دیدگاه
# ==================================================================
def load_last_view():
    return load_json(LAST_VIEW_FILE, {"direction": None, "confidence": None, "reason": None, "timestamp": None})

def save_view(direction, confidence, reason):
    now = datetime.now(TEHRAN_TZ)
    save_json(LAST_VIEW_FILE, {"direction": direction, "confidence": confidence, "reason": reason, "timestamp": now.isoformat()})

def check_view_change(new_direction, new_reason):
    prev = load_last_view()
    prev_dir = prev.get("direction")
    if prev_dir and prev_dir != new_direction and new_direction != "خنثی":
        return True, prev_dir, prev.get("reason", "")
    return False, prev_dir, ""

# ==================================================================
# بخش ۶: سیستم batching
# ==================================================================
def load_batch(): return load_json(BATCH_FILE, {"items": [], "first_time": None, "last_time": None})
def save_batch(batch): save_json(BATCH_FILE, batch)
def clear_batch(): save_json(BATCH_FILE, {"items": [], "first_time": None, "last_time": None})
def add_to_batch(news_text):
    batch = load_batch()
    now_iso = datetime.now(TEHRAN_TZ).isoformat()
    if not batch.get("items"): batch["first_time"] = now_iso
    batch["items"].append(news_text[:500])
    batch["last_time"] = now_iso
    save_json(batch)

def should_wait_for_more_news():
    try:
        data = fetch_calendar()
        now = datetime.now(TEHRAN_TZ)
        for ev in data:
            if ev.get("country") not in ["USD", "EUR", "EMU"]: continue
            if ev.get("impact") != "High": continue
            dt = parse_event_dt(ev)
            if not dt: continue
            diff = (dt.astimezone(TEHRAN_TZ) - now).total_seconds() / 60
            if 0 < diff <= 25: return True, ev.get("title", "")
        return False, None
    except Exception: return False, None

# ==================================================================
# بخش ۷: سیستم عملکرد دو سشنی (لندن + آمریکا)
# ==================================================================
SESSION_CONFIG = {
    "morning": {"label": "لندن", "emoji": "🇬🇧", "eval_hour": 16, "eval_minute": 0},
    "us_preopen": {"label": "آمریکا", "emoji": "🇺🇸", "eval_hour": 21, "eval_minute": 30},
}

def save_prediction(direction, confidence, slot, has_news=False):
    price = get_eurusd_price()
    if not price: return
    predictions = load_json(PREDICTIONS_FILE, {})
    now = datetime.now(TEHRAN_TZ)
    today = now.strftime("%Y%m%d")
    
    existing_today = [k for k in predictions.keys() if k.startswith(today) and k.endswith(f"_{slot}")]
    if existing_today: return
    
    session = SESSION_CONFIG.get(slot, {})
    pid = f"{now.strftime('%Y%m%d_%H%M')}_{slot}"
    predictions[pid] = {
        "timestamp": now.isoformat(), "date": now.strftime("%Y-%m-%d"),
        "slot": slot, "session": session.get("label", slot),
        "direction": direction, "confidence": confidence,
        "price_at_prediction": price, "has_news": has_news,
        "verified": False, "result": None, "price_change_pips": None,
    }
    if len(predictions) > 200:
        for k in sorted(predictions.keys())[:len(predictions) - 200]:
            del predictions[k]
    save_json(PREDICTIONS_FILE, predictions)

def verify_predictions():
    predictions = load_json(PREDICTIONS_FILE, {})
    if not predictions: return {"total": 0, "decisive": 0, "correct": 0, "wrong": 0, "neutral": 0, "accuracy": 0, "unverified": 0}

    current = get_eurusd_price()
    if not current: return None
    now = datetime.now(TEHRAN_TZ)
    changed = False

    for pid, pred in predictions.items():
        if pred.get("verified"): continue
        try:
            ptime = datetime.fromisoformat(pred["timestamp"])
            slot = pred.get("slot", "morning")
            session = SESSION_CONFIG.get(slot, {})
            target_time = ptime.replace(hour=session.get("eval_hour", 21), minute=session.get("eval_minute", 30), second=0, microsecond=0)
            if ptime >= target_time: target_time += timedelta(days=1)
            
            if now < target_time: continue
            
            old = pred.get("price_at_prediction", 0)
            d = pred.get("direction", "خنثی")
            if not old: continue
            
            # اسکن TP/SL بیست پیپی
            intraday_result, pips_hit = check_tp_sl_hits(pred["timestamp"], d, old)
            
            if intraday_result is not None:
                result = intraday_result
                change = pips_hit
            else:
                change = round((current - old) * 10000, 1)
                MIN_PROFIT = 5.0
                
                if d == "صعودی" and change >= MIN_PROFIT: result = "correct"
                elif d == "نزولی" and change <= -MIN_PROFIT: result = "correct"
                elif d == "صعودی" and change <= -20.0: result = "wrong"
                elif d == "نزولی" and change >= 20.0: result = "wrong"
                elif d == "خنثی" and abs(change) < 20.0: result = "correct"
                else: result = "neutral"

            pred["verified"] = True
            pred["result"] = result
            pred["price_change_pips"] = change
            pred["threshold_used"] = 20.0
            changed = True
        except Exception as ex:
            print(f"خطا در ارزیابی {pid}:", ex)

    if changed: save_json(PREDICTIONS_FILE, predictions)
    return calculate_perf_from_json(predictions)

def calculate_perf_from_json(predictions=None):
    if predictions is None: predictions = load_json(PREDICTIONS_FILE, {})
    all_preds = list(predictions.values())
    verified = [p for p in all_preds if p.get("verified")]
    unverified = len(all_preds) - len(verified)
    total = len(verified)
    
    if total == 0:
        return {"total": 0, "decisive": 0, "correct": 0, "wrong": 0, "neutral": 0, "accuracy": 0, "unverified": unverified}
    
    correct = sum(1 for p in verified if p["result"] == "correct")
    wrong = sum(1 for p in verified if p["result"] == "wrong")
    neutral = sum(1 for p in verified if p["result"] == "neutral")
    decisive = correct + wrong
    accuracy = round(correct / decisive * 100, 1) if decisive > 0 else 0
    
    def _calc_session(slot):
        preds = [p for p in verified if p.get("slot") == slot]
        tot = len(preds)
        if tot == 0: return {"total": 0, "decisive": 0, "correct": 0, "wrong": 0, "neutral": 0, "accuracy": 0}
        c = sum(1 for p in preds if p["result"] == "correct")
        w = sum(1 for p in preds if p["result"] == "wrong")
        n = sum(1 for p in preds if p["result"] == "neutral")
        dec = c + w
        acc = round(c / dec * 100, 1) if dec > 0 else 0
        return {"total": tot, "decisive": dec, "correct": c, "wrong": w, "neutral": n, "accuracy": acc}
        
    return {
        "total": total, "decisive": decisive, "correct": correct,
        "wrong": wrong, "neutral": neutral, "accuracy": accuracy,
        "unverified": unverified,
        "london": _calc_session("morning"), "us": _calc_session("us_preopen"),
    }

def build_performance_view(perf):
    if not perf: return "🎯 عملکرد ربات:\nهنوز داده کافی نیست."
    total, unverified = perf.get("total", 0), perf.get("unverified", 0)
    if total < 1 and unverified < 1: return "🎯 عملکرد ربات:\nهنوز داده کافی نیست."
    
    decisive = perf.get("decisive", 0)
    acc = perf.get("accuracy", 0)
    parts = []
    
    if decisive > 0:
        if acc >= 70: rating = "🟢 عالی"
        elif acc >= 55: rating = "🟡 خوب"
        elif acc >= 45: rating = "🟠 متوسط"
        else: rating = "🔴 در حال یادگیری"
        parts.append(f"🎯 عملکرد کلی ({to_fa_digits(str(total + unverified))} پیش‌بینی):")
        parts.append(f"{rating} دقت: {to_fa_digits(str(acc))}٪ ({to_fa_digits(str(decisive))} قطعی)")
        parts.append(f"✅ {to_fa_digits(str(perf.get('correct', 0)))} | ❌ {to_fa_digits(str(perf.get('wrong', 0)))} | ⚪ {to_fa_digits(str(perf.get('neutral', 0)))}")
    else:
        parts.append(f"🎯 عملکرد ربات ({to_fa_digits(str(total + unverified))} پیش‌بینی):")
        
    london = perf.get("london", {})
    if london.get("decisive", 0) > 0:
        parts.append(f"🇬🇧 لندن: {to_fa_digits(str(london['accuracy']))}٪ دقت | ✅{to_fa_digits(str(london['correct']))} ❌{to_fa_digits(str(london['wrong']))} ⚪{to_fa_digits(str(london['neutral']))}")
        
    us = perf.get("us", {})
    if us.get("decisive", 0) > 0:
        parts.append(f"🇺🇸 آمریکا: {to_fa_digits(str(us['accuracy']))}٪ دقت | ✅{to_fa_digits(str(us['correct']))} ❌{to_fa_digits(str(us['wrong']))} ⚪{to_fa_digits(str(us['neutral']))}")
        
    if unverified > 0 and decisive > 0:
        parts.append(f"⏳ در انتظار ارزیابی: {to_fa_digits(str(unverified))}")
    return "\n".join(parts)

# ==================================================================
# بخش ۸: تقویم اقتصادی
# ==================================================================
def fetch_calendar():
    try: return requests.get("https://nfs.faireconomy.media/ff_calendar_thisweek.json", headers=HEADERS, timeout=12).json()
    except Exception: return []

def parse_event_dt(ev):
    raw = (ev.get("date") or "").strip()
    if not raw: return None
    try:
        dt = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        if dt.tzinfo is None: dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except Exception: return None

def event_time_fa(ev):
    dt = parse_event_dt(ev)
    return to_fa_digits(dt.astimezone(TEHRAN_TZ).strftime("%H:%M")) if dt else to_fa_digits(ev.get("time", "نامشخص"))

def impact_fa(impact):
    impact = (impact or "").strip().lower()
    if impact == "high": return "🔴 خیلی مهم"
    elif impact == "medium": return "🟠 متوسط"
    return "⚪ کم"

def country_fa(country): return COUNTRY_FA.get((country or "").upper(), country or "")
def event_title_fa(ev): return translate_title(ev.get("title", ""))

def expected_impact_fa(ev):
    return "بسته به داده‌های واقعی منتشر شده، روی دلار یا یورو تأثیر می‌گذارد."

def event_number(val):
    m = re.search(r"[-+]?\d+(?:\.\d+)?", str(val or "").replace(",", ""))
    return float(m.group()) if m else None

def get_today_events():
    data = fetch_calendar()
    now = datetime.now(TEHRAN_TZ)
    today = now.date()
    tomorrow = (now + timedelta(days=1)).date()
    out = []
    seen_events = set()
    
    for ev in data:
        if ev.get("country") not in ["USD", "EUR", "EMU"]: continue
        if ev.get("impact") not in ("High", "Medium"): continue
        dt = parse_event_dt(ev)
        if not dt: continue
        d = dt.astimezone(TEHRAN_TZ).date()
        
        # جلوگیری از رویدادهای تکراری مثل GDP با تیترهای متعدد
        ev_key = f"{d}_{ev.get('time')}_{ev.get('title')}_{ev.get('impact')}"
        if ev_key in seen_events: continue
        seen_events.add(ev_key)
        
        if d == today:
            ev["_today"] = True
            ev["_tomorrow"] = False
            out.append(ev)
        elif d == tomorrow:
            ev["_today"] = False
            ev["_tomorrow"] = True
            out.append(ev)
    return out

def get_week_events():
    return [ev for ev in fetch_calendar() if ev.get("country") in ["USD", "EUR", "EMU"] and ev.get("impact") == "High"]

def check_upcoming_events():
    try:
        data = fetch_calendar()
        now = datetime.now(TEHRAN_TZ)
        alerts = []
        seen = load_seen()
        for ev in data:
            if ev.get("country") not in ["USD", "EUR", "EMU"] or ev.get("impact") != "High": continue
            dt = parse_event_dt(ev)
            if not dt: continue
            diff = (dt.astimezone(TEHRAN_TZ) - now).total_seconds() / 60
            if 25 <= diff <= 35:
                uid = f"pre_{ev.get('title')}_{ev.get('date')}"
                if uid in seen: continue
                seen[uid] = {"date": now.strftime("%Y-%m-%d"), "sent_at": now.strftime("%H:%M")}
                alerts.append(ev)
        if alerts: save_seen(seen)
        return alerts
    except Exception: return []

# ==================================================================
# بخش ۹: دریافت اخبار
# ==================================================================
def fetch_rss(url, n=15):
    out = []
    try:
        d = feedparser.parse(url)
        for e in d.entries[:n]:
            text = f"{clean_html_text(getattr(e, 'title', ''))}. {clean_html_text(getattr(e, 'summary', ''))}".strip()
            if is_relevant_news(text): out.append(text[:400])
    except Exception: pass
    return out

def fetch_all_news():
    items = fetch_rss(SOURCES["fxstreet_rss"], 15) + fetch_rss(SOURCES["forexlive"], 12) + fetch_rss(SOURCES["ecb_press"], 8) + fetch_rss(SOURCES["fed_press"], 8) + fetch_rss(SOURCES["investing"], 10)
    seen = set()
    uniq = []
    for x in items:
        key = x.strip().lower()[:100]
        if key not in seen:
            seen.add(key)
            uniq.append(x)
    return uniq[:40]

def check_live_news():
    return []

def check_breaking_headlines():
    return []

# ==================================================================
# بخش ۱۰: هوش مصنوعی
# ==================================================================
def call_groq(messages, temperature, max_tokens):
    for model in AI_MODELS:
        try:
            is_reasoning = model in REASONING_MODELS
            if is_reasoning:
                merged_messages = []
                system_text = ""
                for msg in messages:
                    if msg["role"] == "system": system_text = msg["content"]
                    else:
                        if system_text and msg["role"] == "user":
                            merged_messages.append({"role": "user", "content": f"دستورات:\n{system_text}\n\n{msg['content']}"})
                            system_text = ""
                        else: merged_messages.append(msg)
                resp = groq_client.chat.completions.create(model=model, messages=merged_messages, temperature=max(0.5, temperature), max_completion_tokens=max_tokens, reasoning_effort="low", reasoning_format="hidden")
            else:
                resp = groq_client.chat.completions.create(model=model, messages=messages, temperature=temperature, max_tokens=max_tokens)
            
            raw = strip_think_tags(resp.choices[0].message.content.strip())
            if raw: return raw
        except Exception as ex: print(f"⚠️ مدل {model} خطا داد: {str(ex)[:100]}")
    return None

def score_sentiment_ai(news_text, calendar_events=None):
    if not HAS_GROQ: return 0, 0, "هوش مصنوعی در دسترس نیست"
    try:
        messages = [
            {"role": "system", "content": f"{ECON_RULES}\n\nخروجی فقط JSON: {{'bull': عدد, 'bear': عدد, 'reason': 'دلیل کوتاه'}}"},
            {"role": "user", "content": f"اخبار:\n{news_text[:3000]}"},
        ]
        raw = call_groq(messages, temperature=0.15, max_tokens=250)
        s, e = raw.find("{"), raw.rfind("}") + 1
        if s != -1 and e > s:
            data = json.loads(raw[s:e])
            return min(15, int(data.get("bull", 0))), min(15, int(data.get("bear", 0))), clean_foreign_chars(data.get("reason", ""))
    except Exception: pass
    return 0, 0, "تحلیل ممکن نشد"

def get_direction(bull, bear):
    diff = bull - bear
    if (bull + bear) <= 4: return "خنثی", "پایین"
    if diff >= 5: return "صعودی", "بالا"
    if diff >= 3: return "صعودی", "متوسط"
    if diff <= -5: return "نزولی", "بالا"
    if diff <= -3: return "نزولی", "متوسط"
    return "خنثی", "پایین"

def ai_analyze_fa(news_text, calendar_events, bull, bear, direction, confidence, performance, market_assets=None, prev_reason=""):
    if not HAS_GROQ: return None
    try:
        cal_text = ""
        if calendar_events:
            for ev in calendar_events[:6]:
                day_lbl = "امروز" if ev.get("_today") else "فردا"
                cal_text += f"- [{day_lbl}] {country_fa(ev.get('country',''))}: {event_title_fa(ev)}\n"

        market_text = ""
        if market_assets:
            market_text = f"شاخص دلار (DXY): {market_assets.get('DXY (شاخص دلار)', 'نامشخص')} | بازده اوراق 10 ساله آمریکا: {market_assets.get('US10Y (اوراق 10 ساله)', 'نامشخص')}% | طلا: {market_assets.get('Gold (طلا)', 'نامشخص')}$"

        narrative = build_market_narrative(news_text[:1500] if isinstance(news_text, str) else "\n".join(news_text)[:1500])

        prompt = f"""تو تحلیل‌گر فاندامنتال حرفه‌ای و باتجربه یورو/دلار هستی.
{ECON_RULES}

قواعد سختگیرانه:
- تحلیل عمیق (۲۰۰ کلمه) و فقط فارسی.
- تکرار ممنوع.
- اگر جهت صعودی است، جمله نزولی ننویس.

روایت غالب فعلی بازار:
{narrative}

دلیل قبلی ربات (برای جلوگیری از تناقض در صحبت‌هایت، خصوصاً درباره ژئوپلیتیک):
{prev_reason if prev_reason else 'اطلاعات قبلی موجود نیست'}

بازارهای موازی:
{market_text if market_text else "نامشخص"}

ساختار تحلیل:
۱) چشم‌انداز کلی
۲) جریان پول هوشمند و واگرایی (با توجه به DXY و US10Y)
۳) عوامل مؤثر 
۴) چشم‌انداز کوتاه‌مدت 
۵) توصیه نهایی (فقط یک جمله متناسب با جهت)

اخبار:
{news_text[:2500]}
تقویم:
{cal_text if cal_text else "خبر مهمی نیست"}
جهت: {direction}
"""
        messages = [{"role": "system", "content": "فقط فارسی روان و تریدرپسند بنویس."}, {"role": "user", "content": prompt}]
        res = call_groq(messages, temperature=0.15, max_tokens=900)
        return clean_foreign_chars(res) if res else None
    except Exception: return None

# ==================================================================
# بخش ۱۱: ساخت پیام و تلگرام
# ==================================================================
def build_fundamental_brief(news_text, bull, bear, direction, confidence, reason,
                            calendar_events=None, performance=None,
                            view_changed=False, prev_dir=None, prev_reason="",
                            slot_label="تحلیل فاندامنتال", slot=None, market_assets=None):
    date_fa, date_short = get_date_fa()
    time_fa = get_time_fa()
    emoji = "🟢" if direction == "صعودی" else ("🔴" if direction == "نزولی" else "🟡")
    
    parts = [
        f"{emoji} {slot_label} یورو/دلار", "", f"{date_fa} - {time_fa} تهران", "",
        f"📐 جهت: {direction}", f"🔒 اطمینان: {confidence}",
        f"📊 امتیاز: صعودی {to_fa_digits(str(bull))} / نزولی {to_fa_digits(str(bear))}",
        f"💡 دلیل: {reason}", ""
    ]
    
    if market_assets:
        market_str = " | ".join([f"{k}: {v}" for k, v in market_assets.items()])
        parts.extend([f"🌐 بازارهای موازی: {to_fa_digits(market_str)}", ""])

    if view_changed and prev_dir:
        parts.extend([
            "━━━━━━━━━━━━━━", "🔄 تغییر دیدگاه ربات!",
            f"   قبلی: {prev_dir}", f"   جدید: {direction}",
            f"   دلیل قبلی: {prev_reason}", f"   دلیل تغییر: {reason}",
            "", "⚠️ جهت بازار عوض شده. با احتیاط!", ""
        ])

    ai = ai_analyze_fa(news_text, calendar_events, bull, bear, direction, confidence, performance, market_assets, prev_reason)
    if ai: parts.extend(["━━━━━━━━━━━━━━", "🤖 تحلیل (مبتنی بر روایت فعلی بازار):", "", ai, ""])

    if calendar_events:
        today_up, tomorrow_ev = [], []
        now_te = datetime.now(TEHRAN_TZ)
        for ev in calendar_events:
            if ev.get("_today") and (parse_event_dt(ev) or datetime.max.replace(tzinfo=TEHRAN_TZ)).astimezone(TEHRAN_TZ) > now_te: today_up.append(ev)
            elif ev.get("_tomorrow"): tomorrow_ev.append(ev)
        if today_up:
            parts.append("📅 اخبار پیش‌رو امروز:")
            parts.extend([f"  • {event_time_fa(ev)} | {country_fa(ev.get('country',''))} | {event_title_fa(ev)}" for ev in today_up[:3]])
        if tomorrow_ev:
            parts.extend(["", "📅 فردا:"])
            parts.extend([f"  • {event_time_fa(ev)} | {country_fa(ev.get('country',''))} | {event_title_fa(ev)}" for ev in tomorrow_ev[:3]])
        parts.append("")

    if performance: parts.extend([build_performance_view(performance), ""])
    parts.extend([get_motivation(direction=direction, slot=slot, view_changed=view_changed), "", f"@EURUSDFaBot | {date_short}"])
    
    return "\n".join(parts), ""

def send_text(text):
    if TELEGRAM_TOKEN.startswith("PUT_"):
        print(text)
        return True
    try: requests.post(f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage", data={"chat_id": CHAT_ID, "text": text[:4000], "disable_web_page_preview": True}, timeout=20)
    except Exception: pass
    return True

# ==================================================================
# بخش ۱۲: اجرا
# ==================================================================
def run_once(slot="manual"):
    if slot == "verify":
        verify_predictions()
        return

    verify_predictions()
    news = fetch_all_news()
    cal = get_today_events()
    bull, bear, reason = score_sentiment_ai("\n".join(news), calendar_events=cal)
    direction, confidence = get_direction(bull, bear)
    market_assets = get_market_assets()

    view_changed, prev_dir, prev_reason = check_view_change(direction, reason)
    perf_summary = verify_predictions()
    slot_label = SCHEDULES.get(slot, SCHEDULES["manual"])["label"]

    msg, voice = build_fundamental_brief(
        "\n".join(news), bull, bear, direction, confidence, reason,
        calendar_events=cal, performance=perf_summary,
        view_changed=view_changed, prev_dir=prev_dir, prev_reason=prev_reason,
        slot_label=slot_label, slot=slot, market_assets=market_assets
    )
    send_text(msg)
    save_view(direction, confidence, reason)
    if slot in ("morning", "us_preopen"):
        save_prediction(direction, confidence, slot, has_news=bool(cal))

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--slot", default="manual")
    args = parser.parse_args()
    run_once(args.slot)