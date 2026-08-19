#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
دستیار خبر فاندامنتال یورو/دلار – نسخه نهایی (ارتقا یافته برای تریدرها)
اضافه شدن: بازارهای موازی (DXY, طلا، اوراق)، روایت بازار، محاسبه دقیق انحراف داده‌ها، هشدارهای نقدینگی
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
SEND_VOICE = os.getenv("SEND_VOICE", "true").lower() == "true"

VOICE_NAME = os.getenv("VOICE_NAME", "fa-IR-DilaraNeural")
VOICE_RATE = os.getenv("VOICE_RATE", "-12%")
VOICE_PITCH = os.getenv("VOICE_PITCH", "+0Hz")

NEWS_IMPACT_LEVELS = os.getenv("NEWS_IMPACT", "High,Medium").split(",")

# 💡 روایت غالب بازار (خودکار ساخته می‌شود، یا اگر دستی تنظیم شد استفاده می‌شود)
CURRENT_NARRATIVE_OVERRIDE = os.getenv("MARKET_NARRATIVE", "")

def build_market_narrative(news_text):
    """ساخت خودکار روایت بازار با AI بر اساس اخبار روز"""
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

# ⭐ مدل‌های هوش مصنوعی (به ترتیب اولویت - همه رایگان)
AI_MODELS = [
    "openai/gpt-oss-120b",       # بهترین کیفیت رایگان - 120B پارامتر
    "moonshotai/kimi-k2-instruct", # Fallback اول - context بزرگ 262K
    "qwen/qwen3.6-27b",           # Fallback دوم - سریع و رایگان
]

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
- نفت گران = همیشه ضرر اروپا = همیشه نزولی یورو
- نفت ارزان = همیشه سود اروپا = همیشه صعودی یورو
- هیچ استثنایی وجود ندارد

۲. تورم آمریکا و نرخ بهره:
- تورم آمریکا در حال کاهش = فدرال رزرو نرخ را ثابت یا کاهش می‌دهد = دلار ضعیف = صعودی یورو
- تورم آمریکا در حال افزایش = فدرال رزرو نرخ را بالا می‌برد = دلار قوی = نزولی یورو

۳. بحران ژئوپلیتیک (قانون مطلق):
- جنگ، تنش، حمله = همیشه دلار پناهگاه امن = همیشه دلار قوی = همیشه نزولی یورو
- بحران حل شود = دلار ضعیف = صعودی یورو
- هیچ استثنایی وجود ندارد

۴. داده‌های اقتصادی آمریکا:
- داده قوی = دلار قوی = نزولی یورو
- داده ضعیف = دلار ضعیف = صعودی یورو

۵. داده‌های اقتصادی اروپا:
- داده قوی اروپا = یورو قوی = صعودی
- داده ضعیف اروپا = یورو ضعیف = نزولی

۶. بانک‌های مرکزی:
- فدرال رزرو سخت‌گیرانه = دلار قوی = نزولی یورو
- فدرال رزرو ملایم = دلار ضعیف = صعودی یورو
- بانک مرکزی اروپا سخت‌گیرانه = یورو قوی = صعودی
- بانک مرکزی اروپا ملایم = یورو ضعیف = نزولی

۷. شاخص‌ها:
- DXY بالا = نزولی یورو / بازده اوراق بالا = نزولی یورو / طلا بالا = صعودی یورو

۸. احساسات ریسک:
- ریسک‌پذیری = دلار ضعیف = صعودی یورو
- ریسک‌گریزی = دلار قوی = نزولی یورو

۹. قانون مطلق هم‌خوانی (بسیار مهم):
- توصیه نهایی حتماً باید با جهت تعیین‌شده هم‌خوان باشد
- اگر جهت صعودی است، مطلقاً نگوی بفروش یا از خرید خودداری کن
- اگر جهت نزولی است، مطلقاً نگوی بخر
- هیچ تناقضی مجاز نیست

۱۰. قانون مطلق عدم تکرار (بسیار مهم):
- هر نکته را فقط یک بار بگو
- جمله‌ها را تکرار نکن
- پاراگراف‌های تکراری نساز

۱۱. قانون پیش‌خور شدن (Priced In) و اوراق قرضه:
- اگر خبر مهمی برای دلار آمد اما بازده اوراق ۱۰ ساله (US10Y) در حال ریزش بود یا واکنش نشان نداد، یعنی خبر پیش‌خور شده است. در این حالت به جای سیگنال تهاجمی بگو: "خبر پیش‌خور شده و احتمال چرخش بازار (Sell the fact) وجود دارد."

۱۲. تشخیص فیک‌اوت (Fakeout) و واگرایی بین چارت و DXY:
- حالت طبیعی (روند سالم): اگر EUR/USD صعودی است، DXY باید نزولی باشد. اگر EUR/USD نزولی است، DXY باید صعودی باشد. در این حالت بگو "روند توسط شاخص دلار تایید می‌شود و واگرایی نداریم".
- حالت تله (فیک‌اوت): اگر هر دو (EUR/USD و DXY) با هم صعودی یا با هم نزولی هستند، این یک واگرایی و تله نقدینگی است. فقط در این حالت هشدار فیک‌اوت بده و بگو "روند فاقد پشتوانه پولی است".

۱۳. قانون انحراف صفر (Zero Deviation):
- اگر داده‌های اقتصادی دقیقاً مشابه پیش‌بینی (Forecast) منتشر شدند، مارکت از قبل آن را پیش‌خور کرده است. به این داده‌ها وزن حرکتی نده و هشدار تله نقدینگی بده."""

BREAKING_KEYWORDS = [
    "surges", "plunges", "plummets", "spikes", "jumps", "slides",
    "crashes", "soars", "tumbles", "slumps", "collapses", "skyrockets",
    "selloff", "sell-off", "rallies", "rally",
    "sharply lower", "sharply higher", "sharply down", "sharply up",
    "falls sharply", "rises sharply", "drops sharply", "dives", "nosedives",
    "tumbles after", "jumps after", "falls after", "rises after", "drops after",
    "slips", "dumps",
    "breaking", "urgent", "shock", "unexpected", "surprise", "surprisingly",
    "crisis", "emergency", "alert", "just in",
    "cuts rates", "raises rates", "rate decision", "rate hike", "rate cut",
    "emergency cut", "emergency hike", "unexpected rate",
    "beats expectations", "misses expectations", "comes in", "actual",
    "surges past", "drops below", "cooler than", "hotter than",
    "attack", "strikes", "sanctions", "invasion", "retaliation",
    "escalation", "ceasefire", "tariffs imposed", "trade war",
    "oil surges", "oil plunges", "oil crisis", "gold surges",
    "gold plummets", "crude crashes",
]

ROUTINE_KEYWORDS = [
    "preview", "outlook", "wrap", "recap", "what to expect",
    "weekly", "monthly", "analysis", "digest", "roundup",
    "calendar", "schedule", "watch list", "watchlist",
    "five things", "things to know", "markets consolidation",
    "consolidate", "range", "quiet", "calm", "stable",
    "ahead of", "waiting for", "preparing for", "eyes on",
    "technical analysis", "chart of the day", "weekly preview",
    "month ahead", "week ahead", "forecast for",
]

SPEAKERS = {
    "powell": "پاول (رئیس فدرال رزرو)",
    "warsh": "وارش (رئیس فدرال رزرو)",
    "waller": "والر (عضو فدرال رزرو)",
    "williams": "ویلیامز (رئیس فدرال رزرو نیویورک)",
    "brainard": "برینارد (فدرال رزرو)",
    "mester": "مستر (فدرال رزرو)",
    "bostic": "بوستیک (فدرال رزرو)",
    "barkin": "بارکین (فدرال رزرو)",
    "bowman": "بومن (فدرال رزرو)",
    "lagarde": "لاگارد (رئیس بانک مرکزی اروپا)",
    "schnabel": "اشناببل (بانک مرکزی اروپا)",
    "lane": "لین (بانک مرکزی اروپا)",
    "nagel": "ناگل (بانک مرکزی آلمان)",
    "holzmann": "هولتسمان (بانک مرکزی اروپا)",
    "villeroy": "ویلروی (بانک مرکزی فرانسه)",
    "stournaras": "ستورناراس (بانک مرکزی اروپا)",
    "muller": "مولر (بانک مرکزی اروپا)",
    "kazimir": "کازیمیر (بانک مرکزی اروپا)",
    "centeno": "سنتنو (بانک مرکزی اروپا)",
    "repuis": "روپویس (بانک مرکزی اروپا)",
    "macklem": "مک‌لم (بانک مرکزی کانادا)",
    "bailey": "بیلی (بانک مرکزی انگلستان)",
    "ueda": "اودا (بانک مرکزی ژاپن)",
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
    "core ppi m/m": "تورم تولیدکننده هسته‌ای (ماهانه)",
    "core ppi y/y": "تورم تولیدکننده هسته‌ای (سالانه)",
    "ppi m/m": "تورم تولیدکننده (ماهانه)",
    "ppi y/y": "تورم تولیدکننده (سالانه)",
    "nonfarm payrolls": "اشتغال غیرکشاورزی",
    "non-farm payrolls": "اشتغال غیرکشاورزی",
    "nfp": "اشتغال غیرکشاورزی",
    "unemployment rate": "نرخ بیکاری",
    "initial jobless claims": "ادعای اولیه بیکاری",
    "continuing jobless claims": "ادعای مستمر بیکاری",
    "unemployment claims": "ادعای بیکاری",
    "jobless claims": "ادعای بیکاری",
    "gdp": "رشد اقتصادی",
    "gdp growth": "رشد اقتصادی",
    "retail sales": "فروش خرده‌فروشی",
    "retail sales m/m": "فروش خرده‌فروشی (ماهانه)",
    "interest rate": "نرخ بهره",
    "rate decision": "تصمیم نرخ بهره",
    "fed chairman": "رئیس فدرال رزرو",
    "fed chair": "رئیس فدرال رزرو",
    "fomc": "کمیته باز بازار فدرال رزرو",
    "fomc statement": "بیانیه کمیته فدرال رزرو",
    "fomc minutes": "صورتجلسه فدرال رزرو",
    "fomc member": "عضو کمیته فدرال رزرو",
    "press conference": "کنفرانس مطبوعاتی",
    "testimony": "شهادت کنگره",
    "consumer confidence": "اعتماد مصرف‌کننده",
    "ism manufacturing": "شاخص مدیران خرید صنایع",
    "ism services": "شاخص مدیران خرید خدمات",
    "pmi manufacturing": "شاخص مدیران خرید تولید",
    "pmi services": "شاخص مدیران خرید خدمات",
    "durable goods": "کالاهای بادوام",
    "building permits": "مجوزهای ساختمانی",
    "existing home sales": "فروش خانه‌های موجود",
    "new home sales": "فروش خانه‌های جدید",
    "trade balance": "تراز تجاری",
    "current account": "حساب جاری",
    "consumer price index": "شاخص قیمت مصرف‌کننده",
    "producer price index": "شاخص قیمت تولیدکننده",
}

# ==================================================================
# بخش ۱: پیام‌های انگیزشی
# ==================================================================

MOTIVATIONAL_GENERAL = [
    "💎 معامله‌گر حرفه‌ای با صبر و نظم سود می‌کند.",
    "🎯 مدیریت ریسک، کلید بقای شما در بازار است.",
    "💪 هر معامله، فرصتی برای یادگیری است.",
    "🧠 احساسات را کنار بگذار، منطق را دنبال کن.",
    "⚡ بازار همیشه فرصت جدید می‌سازد — صبور باش.",
    "🌟 موفقیت در تکرار معامله‌های درست است، نه شانس.",
    "🏔️ بهترین معامله‌گران روزهای سختی هم داشته‌اند.",
    "🔮 تحلیل درست + مدیریت سرمایه = موفقیت پایدار.",
    "🛡️ حفظ سرمایه مهم‌تر از سود کردن است.",
    "🌈 بعد از هر اصلاح، فرصت جدیدی متولد می‌شود.",
]

MOTIVATIONAL_BULLISH = [
    "🟢 روند صعودی به‌کنار، فرصت خوبی در راه است!",
    "📈 بازار با توست — با اطمینان گام بردار.",
    "✨ باد موافق است — بادبان را تنظیم کن!",
    "🚀 صبر در صعود، کلید سود بزرگ است.",
]

MOTIVATIONAL_BEARISH = [
    "🔴 بازار نزولی هم فرصت دارد — فقط هوشمندانه باش.",
    "⚡ در نزول، کنترل ریسک دو برابر مهم می‌شود.",
    "🌊 نزول موقت است، ولی آمادگی همیشگی.",
    "💪 معامله‌گر قوی، در نزول هم آرامش خود را حفظ می‌کند.",
]

MOTIVATIONAL_NEUTRAL = [
    "🟡 بازار نامشخص است — صبر هم یک استراتژی است.",
    "⏳ انتظار هوشمندانه، بهتر از ورود عجولانه است.",
    "🧘 نفس عمیق بکش — بازار خودش جهت را نشان می‌دهد.",
    "🎯 بهترین معامله، گاهی هیچ معامله‌ای نیست.",
]

MOTIVATION_VIEW_CHANGE = [
    "🔄 بازار جهت عوض کرده — انعطاف‌پذیر باش!",
    "⚡ تغییر سریع دیدگاه، نشانه هوشمندی است نه ضعف.",
    "🌊 سوار بر موج جدید شو!",
]

MOTIVATION_MORNING = [
    "🌅 صبح پرانرژی و پرسود برایت آرزو می‌کنم!",
    "☀️ روز جدید، فرصت‌های تازه. آماده‌ای؟",
    "🌄 معامله‌گر موفق، روزش را با تحلیل شروع می‌کند.",
]

MOTIVATION_EVENING = [
    "🌙 چه روزی! هر معامله، یک درس بود.",
    "🔭 امروز را جمع‌بندی کن و فردا قوی‌تر برگرد.",
    "💫 استراحت کن — بازار فردا هم باز است.",
]

def get_motivation(direction=None, slot=None, view_changed=False):
    if view_changed:
        return random.choice(MOTIVATION_VIEW_CHANGE)
    if slot == "morning":
        return random.choice(MOTIVATION_MORNING)
    if slot == "evening":
        return random.choice(MOTIVATION_EVENING)
    if direction == "صعودی":
        return random.choice(MOTIVATIONAL_BULLISH)
    elif direction == "نزولی":
        return random.choice(MOTIVATIONAL_BEARISH)
    elif direction == "خنثی":
        return random.choice(MOTIVATIONAL_NEUTRAL)
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
    if not text:
        return ""
    result = []
    for ch in str(text):
        code = ord(ch)
        if 0x0600 <= code <= 0x06FF:
            result.append(ch)
        elif 0x0041 <= code <= 0x007A:
            result.append(ch)
        elif code in (32, 46, 44, 45, 47, 58, 59, 33, 63, 40, 41, 37, 43):
            result.append(ch)
        elif 0x06F0 <= code <= 0x06F9:
            result.append(ch)
        elif 0x0030 <= code <= 0x0039:
            result.append(ch)
        elif code >= 0x1F000:
            result.append(ch)
        elif ch == "\n":
            result.append(ch)
        else:
            result.append(" ")
    text = "".join(result)
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()

def strip_think_tags(text):
    if not text:
        return ""
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
        text = text.replace(d, fa[i])
    return text

WEEKDAYS_FA = {
    "Monday": "دوشنبه",
    "Tuesday": "سه‌شنبه",
    "Wednesday": "چهارشنبه",
    "Thursday": "پنج‌شنبه",
    "Friday": "جمعه",
    "Saturday": "شنبه",
    "Sunday": "یکشنبه"
}

def get_date_fa():
    now = datetime.now(TEHRAN_TZ)
    wd_en = now.strftime("%A")
    wd_fa = WEEKDAYS_FA.get(wd_en, wd_en)
    if HAS_JALALI:
        jd = jdatetime.datetime.fromgregorian(datetime=now)
        day = jd.strftime("%d")
        month_en = jd.strftime("%B")
        year = jd.strftime("%Y")
        return f"{wd_fa} {day} {month_en} {year}", f"{day} {month_en}"
    return f"{wd_fa} {now.strftime('%Y-%m-%d')}", f"{now.strftime('%d %b')}"

def get_time_fa():
    now = datetime.now(TEHRAN_TZ)
    return to_fa_digits(now.strftime("%H:%M"))

def normalize_voice_text(text):
    text = str(text or "").strip()
    for ch in ["/", "|", "-", "_", "•", "📌", "📅", "📰", "⚖️",
               "🤖", "🔔", "🌅", "🌆", "🌙", "🟢", "🟡", "🔴",
               "🚨", "📊", "⏰", "🔄", "🎤", "💡", "✅", "❌", "⚪",
               "━", "💪", "📉", "📈", "💎", "🎯", "⚡", "🌟", "🏔️",
               "🔮", "🛡️", "🌈", "🚀", "✨", "🌊", "🧠", "🧘",
               "⏳", "☀️", "🌄", "🔭", "💫", "👤", "🌐"]:
        text = text.replace(ch, " ")
    text = text.replace("ي", "ی").replace("ك", "ک")
    text = re.sub(r"\s+", " ", text).strip()
    return text

def is_relevant_news(text):
    low = clean_html_text(text).lower()
    direct = ["eur/usd", "eurusd", "euro", "usd", "dollar",
              "ecb", "fed", "fomc", "powell", "lagarde", "warsh",
              "eurozone", "treasury yields", "dxy"]
    macro = ["inflation", "cpi", "pce", "nfp", "payroll",
             "employment", "unemployment", "jobless claims",
             "pmi", "gdp", "retail sales",
             "interest rate", "rate cut", "rate hike", "yield"]
    region = ["us", "u.s.", "united states", "america",
              "euro area", "eurozone", "europe", "germany", "france"]
    geo = ["iran", "hormuz", "war", "oil", "geopolitical", "tariff"]

    if any(k in low for k in direct):
        return True
    if any(k in low for k in macro) and any(k in low for k in region):
        return True
    if any(k in low for k in geo) and any(
        k in low for k in ["dollar", "euro", "fed", "ecb", "yield", "risk"]
    ):
        return True
    return False

def is_speech_related(text):
    low = clean_html_text(text).lower()
    return any(k in low for k in SPEECH_INDICATORS)

def is_breaking_news(text):
    low = clean_html_text(text).lower()
    if any(k in low for k in ROUTINE_KEYWORDS):
        return False
    if is_speech_related(text):
        return True
    if any(k in low for k in BREAKING_KEYWORDS):
        return True
    return False

def detect_speaker(text):
    low = clean_html_text(text).lower()
    for eng, fa in SPEAKERS.items():
        if eng in low:
            return fa
    return ""

# ==================================================================
# بخش ۳: مدیریت فایل
# ==================================================================
def load_json(filepath, default=None):
    try:
        if os.path.exists(filepath):
            with open(filepath, "r", encoding="utf-8") as f:
                return json.load(f)
    except Exception as ex:
        print(f"خطا در خواندن {filepath}:", ex)
    return default if default is not None else {}

def save_json(filepath, data):
    try:
        with open(filepath, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    except Exception as ex:
        print(f"خطا در نوشتن {filepath}:", ex)

def load_seen():
    data = load_json(SEEN_FILE, {})
    today = datetime.now(TEHRAN_TZ).strftime("%Y-%m-%d")
    return {k: v for k, v in data.items() if v.get("date", "").startswith(today)}

def save_seen(seen):
    save_json(SEEN_FILE, seen)

# ==================================================================
# بخش ۴: قیمت + ATR + بازارهای موازی
# ==================================================================
def get_eurusd_price():
    try:
        url = "https://query1.finance.yahoo.com/v8/finance/chart/EURUSD=X"
        r = requests.get(url, headers=HEADERS, timeout=8)
        if r.status_code == 200:
            data = r.json()
            result = data.get("chart", {}).get("result", [])
            if result:
                meta = result[0].get("meta", {})
                price = meta.get("regularMarketPrice")
                if price:
                    return round(price, 5)
    except Exception as ex:
        print("خطا در دریافت قیمت:", ex)
    return None

def get_market_assets():
    """دریافت قیمت لحظه‌ای بازارهای موازی و وضعیت روزانه یورو/دلار"""
    assets = {"DXY (شاخص دلار)": "DX-Y.NYB", "US10Y (اوراق 10 ساله)": "^TNX", "Gold (طلا)": "GC=F"}
    results = {}
    for name, ticker in assets.items():
        try:
            url = f"https://query1.finance.yahoo.com/v8/finance/chart/{ticker}"
            r = requests.get(url, headers=HEADERS, timeout=5)
            if r.status_code == 200:
                data = r.json()
                price = data.get("chart", {}).get("result", [])[0].get("meta", {}).get("regularMarketPrice")
                if price:
                    results[name] = round(price, 3)
        except Exception:
            pass
            
    # استخراج وضعیت چارت امروز یورو/دلار (تشخیص کندل روزانه)
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
    except Exception:
        pass
        
    return results


def get_eurusd_atr(period=14):
    try:
        url = "https://query1.finance.yahoo.com/v8/finance/chart/EURUSD=X"
        params = {"range": "1mo", "interval": "1d"}
        r = requests.get(url, params=params, headers=HEADERS, timeout=10)
        if r.status_code != 200:
            return None
        data = r.json()
        result = data.get("chart", {}).get("result", [])
        if not result:
            return None
        quotes = result[0].get("indicators", {}).get("quote", [{}])[0]
        highs = quotes.get("high", [])
        lows = quotes.get("low", [])
        closes = quotes.get("close", [])
        valid = [(h, l, c) for h, l, c in zip(highs, lows, closes)
                 if h is not None and l is not None and c is not None]
        if len(valid) < period + 1:
            return None
        trs = []
        for i in range(1, len(valid)):
            h, l, c = valid[i]
            pc = valid[i - 1][2]
            trs.append(max(h - l, abs(h - pc), abs(l - pc)))
        return round(sum(trs[-period:]) / period * 10000, 1)
    except Exception:
        return None    

# ==================================================================
# بخش ۵: سیستم ردیابی دیدگاه
# ==================================================================
def load_last_view():
    return load_json(LAST_VIEW_FILE, {
        "direction": None, "confidence": None,
        "reason": None, "timestamp": None
    })

def save_view(direction, confidence, reason):
    now = datetime.now(TEHRAN_TZ)
    save_json(LAST_VIEW_FILE, {
        "direction": direction,
        "confidence": confidence,
        "reason": reason,
        "timestamp": now.isoformat(),
    })

def check_view_change(new_direction, new_reason):
    prev = load_last_view()
    prev_dir = prev.get("direction")
    if prev_dir and prev_dir != new_direction and new_direction != "خنثی":
        return True, prev_dir, prev.get("reason", "")
    return False, prev_dir, ""

# ==================================================================
# بخش ۶: سیستم batching
# ==================================================================
def load_batch():
    return load_json(BATCH_FILE, {"items": [], "first_time": None, "last_time": None})

def save_batch(batch):
    save_json(BATCH_FILE, batch)

def clear_batch():
    save_json(BATCH_FILE, {"items": [], "first_time": None, "last_time": None})

def add_to_batch(news_text):
    batch = load_batch()
    now_iso = datetime.now(TEHRAN_TZ).isoformat()
    if not batch.get("items"):
        batch["first_time"] = now_iso
    batch["items"].append(news_text[:500])
    batch["last_time"] = now_iso
    save_json(batch)

def should_wait_for_more_news():
    try:
        data = fetch_calendar()
        now = datetime.now(TEHRAN_TZ)
        for ev in data:
            if ev.get("country") not in ["USD", "EUR", "EMU"]:
                continue
            if ev.get("impact") != "High":
                continue
            dt = parse_event_dt(ev)
            if not dt:
                continue
            diff = (dt.astimezone(TEHRAN_TZ) - now).total_seconds() / 60
            if 0 < diff <= 25:
                return True, ev.get("title", "")
        return False, None
    except Exception:
        return False, None

# ==================================================================
# بخش ۷: یادگیری از خطا
# ==================================================================
def save_prediction(direction, confidence, slot, has_news=False):
    price = get_eurusd_price()
    if not price:
        print("قیمت دریافت نشد — پیش‌بینی ذخیره نشد")
        return
    predictions = load_json(PREDICTIONS_FILE, {})
    now = datetime.now(TEHRAN_TZ)
    today = now.strftime("%Y%m%d")
    
    # جلوگیری از ثبت پیش‌بینی تکراری در یک روز برای یک slot
    existing_today = [k for k in predictions.keys() if k.startswith(today) and k.endswith(f"_{slot}")]
    if existing_today:
        print(f"⚠️ پیش‌بینی امروز برای {slot} قبلاً ثبت شده ({existing_today[0]}) — رد شد")
        return
    
    pid = f"{now.strftime('%Y%m%d_%H%M')}_{slot}"
    predictions[pid] = {
        "timestamp": now.isoformat(),
        "date": now.strftime("%Y-%m-%d"),
        "slot": slot,
        "direction": direction,
        "confidence": confidence,
        "price_at_prediction": price,
        "has_news": has_news,
        "verified": False,
        "result": None,
        "price_change_pips": None,
    }
    if len(predictions) > 100:
        for k in sorted(predictions.keys())[:len(predictions) - 100]:
            del predictions[k]
    save_json(PREDICTIONS_FILE, predictions)
    print(f"پیش‌بینی ذخیره شد: {pid} - {direction}")

def verify_predictions():
    predictions = load_json(PREDICTIONS_FILE, {})
    if not predictions:
        return {"total": 0, "decisive": 0, "correct": 0, "wrong": 0, "neutral": 0, "accuracy": 0}

    current = get_eurusd_price()
    if not current:
        return None
    now = datetime.now(TEHRAN_TZ)
    
    # آستانه پویا بر اساس ATR واقعی
    atr = get_eurusd_atr(14)
    if atr and atr > 0:
        # آستانه = 30% از ATR روزانه (پویا)
        threshold = round(atr * 0.3, 1)
        threshold = max(10.0, min(threshold, 35.0))  # حداقل 10، حداکثر 35
        print(f"📏 آستانه پویا: {threshold} پیپ (ATR14={atr})")
    else:
        threshold = 20.0
        print(f"📏 آستانه ثابت: {threshold} پیپ (ATR دریافت نشد)")
    
    changed = False

    for pid, pred in predictions.items():
        if pred.get("verified"):
            continue
        try:
            ptime = datetime.fromisoformat(pred["timestamp"])
            
            # --- منطق جدید ارزیابی درون‌روزی (Intraday) ---
            # تنظیم زمان هدف برای بررسی (ساعت ۲۱:۳۰ همان روز به وقت تهران)
            target_time = ptime.replace(hour=21, minute=30, second=0, microsecond=0)
            
            # اگر پیش‌بینی خودش بعد از ساعت ۲۱:۳۰ شب صادر شده باشد، بررسی آن می‌افتد برای ۲۱:۳۰ فردا
            if ptime >= target_time:
                target_time += timedelta(days=1)
            
            # اگر هنوز به ساعت ۲۱:۳۰ نرسیده‌ایم، از این پیش‌بینی رد شو و بعدا بررسی کن
            if now < target_time:
                continue
            # ----------------------------------------------
            
            old = pred.get("price_at_prediction", 0)
            if not old:
                continue
            change = round((current - old) * 10000, 1)
            d = pred.get("direction", "خنثی")

            if abs(change) < threshold:
                result = "neutral"
            elif d == "صعودی" and change > 0:
                result = "correct"
            elif d == "نزولی" and change < 0:
                result = "correct"
            elif d == "خنثی" and abs(change) < threshold:
                result = "correct"
            else:
                result = "wrong"

            pred["verified"] = True
            pred["result"] = result
            pred["price_change_pips"] = change
            pred["price_at_check"] = current
            pred["threshold_used"] = threshold
            changed = True
        except Exception:
            pass

    if changed:
        save_json(PREDICTIONS_FILE, predictions)
    return calculate_perf_from_json(predictions)

def calculate_perf_from_json(predictions=None):
    if predictions is None:
        predictions = load_json(PREDICTIONS_FILE, {})
    verified = [p for p in predictions.values() if p.get("verified")]
    total = len(verified)
    
    if total == 0:
        return {"total": 0, "decisive": 0, "correct": 0, "wrong": 0, "neutral": 0, "accuracy": 0}
        
    correct = sum(1 for p in verified if p["result"] == "correct")
    wrong = sum(1 for p in verified if p["result"] == "wrong")
    neutral = sum(1 for p in verified if p["result"] == "neutral")
    
    decisive = correct + wrong
    accuracy = round(correct / decisive * 100, 1) if decisive > 0 else 0
    
    return {
        "total": total, 
        "decisive": decisive, 
        "correct": correct,
        "wrong": wrong, 
        "neutral": neutral, 
        "accuracy": accuracy,
    }

def build_performance_view(perf):
    if not perf or perf.get("total", 0) < 1:
        return "🎯 عملکرد ربات:\nهنوز داده کافی نیست."
        
    acc = perf.get("accuracy", 0)
    correct = perf.get("correct", 0)
    wrong = perf.get("wrong", 0)
    neutral = perf.get("neutral", 0)
    decisive = perf.get("decisive", correct + wrong)
    total = perf.get("total", 0)
    
    if decisive == 0:
        return (f"🎯 عملکرد ربات ({to_fa_digits(str(total))} پیش‌بینی):\n"
                f"⏳ هنوز پیش‌بینی قطعی نداریم — بازار کمتر از ۲۰ پیپ حرکت کرده.\n"
                f"⚪ خنثی: {to_fa_digits(str(neutral))}")
                
    if acc >= 70:
        rating = "🟢 عالی"
    elif acc >= 55:
        rating = "🟡 خوب"
    elif acc >= 45:
        rating = "🟠 متوسط"
    else:
        rating = "🔴 در حال یادگیری"
        
    return (
        f"🎯 عملکرد ربات ({to_fa_digits(str(total))} پیش‌بینی):\n"
        f"{rating} دقت: {to_fa_digits(str(acc))}٪ (مبتنی بر {to_fa_digits(str(decisive))} سیگنال قطعی)\n"
        f"✅ درست: {to_fa_digits(str(correct))} | "
        f"❌ اشتباه: {to_fa_digits(str(wrong))} | "
        f"⚪ خنثی: {to_fa_digits(str(neutral))}"
    )
# ==================================================================
# بخش ۸: تقویم اقتصادی
# ==================================================================
def fetch_calendar():
    try:
        r = requests.get("https://nfs.faireconomy.media/ff_calendar_thisweek.json",
                         headers=HEADERS, timeout=12)
        return r.json()
    except Exception:
        return []

def parse_event_dt(ev):
    raw = (ev.get("date") or "").strip()
    if not raw:
        return None
    try:
        dt = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except Exception:
        return None

def event_time_fa(ev):
    dt = parse_event_dt(ev)
    if dt:
        return to_fa_digits(dt.astimezone(TEHRAN_TZ).strftime("%H:%M"))
    return to_fa_digits(ev.get("time", "نامشخص"))

def impact_fa(impact):
    impact = (impact or "").strip().lower()
    if impact == "high": return "🔴 خیلی مهم"
    elif impact == "medium": return "🟠 متوسط"
    elif impact == "low": return "🟢 کم"
    return "⚪ نامشخص"

def country_fa(country):
    return COUNTRY_FA.get((country or "").upper(), country or "")

def event_title_fa(ev):
    return translate_title(ev.get("title", ""))

def expected_impact_fa(ev):
    title = (ev.get("title") or "").lower()
    country = (ev.get("country") or "").upper()
    is_us = country in ("USD", "US")
    is_eu = country in ("EUR", "EMU", "EU")

    if any(k in title for k in ["cpi", "inflation", "pce", "hicp"]):
        if is_us:
            return "تورم بالاتر ← دلار قوی ← نزولی یورو\nتورم پایین‌تر ← دلار ضعیف ← صعودی یورو"
        else:
            return "تورم بالاتر اروپا ← بانک مرکزی سخت‌گیر ← یورو قوی ← صعودی\nتورم پایین‌تر ← یورو ضعیف ← نزولی"
    if any(k in title for k in ["nfp", "payroll", "nonfarm", "non-farm"]):
        return "اشتغال قوی ← دلار قوی ← نزولی یورو\nاشتغال ضعیف ← دلار ضعیف ← صعودی یورو"
    if any(k in title for k in ["jobless", "unemployment"]):
        if is_us:
            return "بیکاری بالاتر ← دلار ضعیف ← صعودی یورو\nبیکاری پایین‌تر ← دلار قوی ← نزولی یورو"
        else:
            return "بیکاری بالاتر اروپا ← یورو ضعیف ← نزولی\nبیکاری پایین‌تر ← یورو قوی ← صعودی"
    if any(k in title for k in ["fomc", "fed", "powell", "warsh"]):
        return "لحن سخت‌گیرانه ← دلار قوی ← نزولی یورو\nلحن ملایم ← دلار ضعیف ← صعودی یورو"
    if any(k in title for k in ["ecb", "lagarde", "refinancing", "monetary policy"]):
        return "لحن سخت‌گیرانه بانک مرکزی اروپا ← یورو قوی ← صعودی\nلحن ملایم ← یورو ضعیف ← نزولی"
    if any(k in title for k in ["philly", "manufacturing", "ism", "pmi", "industrial", "services pmi"]):
        if is_eu:
            return "شاخص بالاتر از انتظار ← اقتصاد اروپا قوی ← یورو قوی ← صعودی\nشاخص پایین‌تر ← یورو ضعیف ← نزولی"
        else:
            return "شاخص بالاتر از انتظار ← اقتصاد آمریکا قوی ← دلار قوی ← نزولی یورو\nشاخص پایین‌تر ← دلار ضعیف ← صعودی یورو"
    if any(k in title for k in ["retail sales", "retail"]):
        if is_eu:
            return "فروش قوی‌تر اروپا ← یورو قوی ← صعودی\nفروش ضعیف‌تر ← یورو ضعیف ← نزولی"
        else:
            return "فروش قوی‌تر ← مصرف قوی ← دلار قوی ← نزولی یورو\nفروش ضعیف‌تر ← دلار ضعیف ← صعودی یورو"
    if any(k in title for k in ["gdp", "growth"]):
        if is_eu:
            return "رشد بالاتر اروپا ← یورو قوی ← صعودی\nرشد پایین‌تر ← یورو ضعیف ← نزولی"
        else:
            return "رشد بالاتر ← دلار قوی ← نزولی یورو\nرشد پایین‌تر ← دلار ضعیف ← صعودی یورو"
    if any(k in title for k in ["consumer sentiment", "consumer confidence"]):
        if is_eu:
            return "اعتماد بالاتر اروپا ← یورو قوی ← صعودی\nاعتماد پایین‌تر ← یورو ضعیف ← نزولی"
        else:
            return "اعتماد بالاتر ← دلار قوی ← نزولی یورو\nاعتماد پایین‌تر ← دلار ضعیف ← صعودی یورو"
    if any(k in title for k in ["durable goods", "orders"]):
        if is_eu:
            return "سفارشات بالاتر اروپا ← یورو قوی ← صعودی\nسفارشات پایین‌تر ← یورو ضعیف ← نزولی"
        else:
            return "سفارشات بالاتر ← دلار قوی ← نزولی یورو\nسفارشات پایین‌تر ← دلار ضعیف ← صعودی یورو"
    if any(k in title for k in ["housing", "home sales", "building"]):
        if is_eu:
            return "داده مسکن قوی اروپا ← یورو قوی ← صعودی\nداده ضعیف ← یورو ضعیف ← نزولی"
        else:
            return "داده مسکن قوی ← دلار قوی ← نزولی یورو\nداده ضعیف ← دلار ضعیف ← صعودی یورو"
    if any(k in title for k in ["trade balance", "current account"]):
        if is_eu:
            return "تراز بهتر اروپا ← یورو قوی ← صعودی\nتراز بدتر ← یورو ضعیف ← نزولی"
        else:
            return "تراز بهتر ← دلار قوی ← نزولی یورو\nتراز بدتر ← دلار ضعیف ← صعودی یورو"
    if any(k in title for k in ["trump", "president"]):
        return "بسته به محتوا:\nهاوکیش (تعرفه/سخت‌گیر) ← دلار قوی ← نزولی یورو\nداویش (ملایم) ← دلار ضعیف ← صعودی یورو"
    if is_eu:
        return "داده بهتر از انتظار اروپا ← یورو قوی ← صعودی\nداده ضعیف‌تر ← یورو ضعیف ← نزولی"
    return "داده بهتر از انتظار ← دلار قوی ← نزولی یورو\nداده ضعیف‌تر از انتظار ← دلار ضعیف ← صعودی یورو"

def event_number(val):
    m = re.search(r"[-+]?\d+(?:\.\d+)?", str(val or "").replace(",", ""))
    return float(m.group()) if m else None

def released_impact_fa(ev):
    title = (ev.get("title") or "").lower()
    country = (ev.get("country") or "").upper()
    actual = event_number(ev.get("actual"))
    forecast = event_number(ev.get("forecast"))
    if actual is None or forecast is None:
        return "داده واقعی/پیش‌بینی در دسترس نیست."
        
    # محاسبه انحراف (Deviation)
    diff = round(actual - forecast, 2)
    diff_text = f"انحراف از پیش‌بینی: {diff:+} | "
    
    if actual == forecast:
        return diff_text + "عدد واقعی مطابق پیش‌بینی ← اثر خنثی."
        
    higher = actual > forecast
    if country == "USD" and any(k in title for k in ["jobless", "unemployment"]):
        return diff_text + ("بیکاری بالاتر از انتظار ← دلار ضعیف ← صعودی یورو." if higher else "بیکاری پایین‌تر ← دلار قوی ← نزولی یورو.")
    if country == "USD":
        return diff_text + ("داده آمریکا قوی‌تر از انتظار ← دلار قوی ← نزولی یورو." if higher else "داده آمریکا ضعیف‌تر ← دلار ضعیف ← صعودی یورو.")
    if country in ["EUR", "EMU"]:
        return diff_text + ("داده اروپا بهتر از انتظار ← یورو قوی ← صعودی." if higher else "داده اروپا ضعیف‌تر ← یورو ضعیف ← نزولی.")
    return diff_text + "اثر باید با واکنش بازار بررسی شود."

def get_today_events():
    data = fetch_calendar()
    now = datetime.now(TEHRAN_TZ)
    today = now.date()
    tomorrow = (now + timedelta(days=1)).date()
    out = []
    for ev in data:
        if ev.get("country") not in ["USD", "EUR", "EMU"]:
            continue
        if ev.get("impact") not in ("High", "Medium"):
            continue
        dt = parse_event_dt(ev)
        if not dt:
            continue
        d = dt.astimezone(TEHRAN_TZ).date()
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
    data = fetch_calendar()
    return [ev for ev in data if ev.get("country") in ["USD", "EUR", "EMU"]
            and ev.get("impact") == "High"]

def check_upcoming_events():
    try:
        data = fetch_calendar()
        now = datetime.now(TEHRAN_TZ)
        alerts = []
        seen = load_seen()
        for ev in data:
            if ev.get("country") not in ["USD", "EUR", "EMU"]:
                continue
            if ev.get("impact") != "High":
                continue
            dt = parse_event_dt(ev)
            if not dt:
                continue
            diff = (dt.astimezone(TEHRAN_TZ) - now).total_seconds() / 60
            if 25 <= diff <= 35:
                uid = f"pre_{ev.get('title')}_{ev.get('date')}"
                if uid in seen:
                    continue
                seen[uid] = {"date": now.strftime("%Y-%m-%d"), "sent_at": now.strftime("%H:%M")}
                alerts.append(ev)
        if alerts:
            save_seen(seen)
        return alerts
    except Exception as ex:
        print("خطا در بررسی اخبار پیش‌رو:", ex)
        return []
                
# ==================================================================
# بخش ۹: دریافت اخبار
# ==================================================================
def fetch_rss(url, n=15):
    out = []
    try:
        d = feedparser.parse(url)
        for e in d.entries[:n]:
            title = clean_html_text(getattr(e, "title", ""))
            summary = clean_html_text(getattr(e, "summary", ""))
            text = f"{title}. {summary}".strip()
            if is_relevant_news(text):
                out.append(text[:400])
    except Exception:
        pass
    return out

def fetch_all_news():
    items = []
    items += fetch_rss(SOURCES["fxstreet_rss"], 15)
    items += fetch_rss(SOURCES["forexlive"], 12)
    items += fetch_rss(SOURCES["ecb_press"], 8)
    items += fetch_rss(SOURCES["fed_press"], 8)
    items += fetch_rss(SOURCES["investing"], 10)
    seen = set()
    uniq = []
    for x in items:
        key = x.strip().lower()[:100]
        if key not in seen:
            seen.add(key)
            uniq.append(x)
    return uniq[:40]

def check_live_news():
    hits = []
    seen = load_seen()
    try:
        data = fetch_calendar()
        now = datetime.now(TEHRAN_TZ)
        today = now.strftime("%Y-%m-%d")
        for ev in data:
            if ev.get("country") not in ["USD", "EUR", "EMU"]:
                continue
            if ev.get("impact") not in ("High", "Medium"):
                continue
            if ev.get("date", "")[:10] != today:
                continue
            actual = (ev.get("actual") or "").strip()
            if not actual:
                continue
            uid = f"{ev.get('title')}_{ev.get('date')}_{ev.get('time')}"
            if uid in seen:
                continue
            seen[uid] = {"date": today, "title": ev.get("title", ""), "actual": actual}
            item = {
                "title": ev.get("title", ""),
                "country": ev.get("country", ""),
                "actual": ev.get("actual", ""),
                "forecast": ev.get("forecast", ""),
                "previous": ev.get("previous", ""),
            }
            item["impact_text"] = released_impact_fa(item)
            hits.append(item)
        save_seen(seen)
        return hits
    except Exception as ex:
        print("خطا در بررسی اخبار زنده:", ex)
        return []

def check_breaking_headlines():
    try:
        urls = [SOURCES["fxstreet_rss"], SOURCES["forexlive"]]
        seen = load_seen()
        hits = []
        today = datetime.now(TEHRAN_TZ).strftime("%Y-%m-%d")
        for u in urls:
            try:
                d = feedparser.parse(u)
                for e in d.entries[:8]:
                    title = clean_html_text(getattr(e, "title", ""))
                    if not is_relevant_news(title):
                        continue
                    if not is_breaking_news(title):
                        continue
                    uid = f"hl_{hashlib.md5(title.lower().encode()).hexdigest()}"
                    if uid in seen:
                        continue
                    seen[uid] = {"date": today, "title": title}
                    hits.append(title)
                    if len(hits) >= 3:
                        break
            except Exception:
                pass
            if len(hits) >= 3:
                break
        save_seen(seen)
        return hits
    except Exception:
        return []

# ==================================================================
# بخش ۱۰: هوش مصنوعی (با سیستم Fallback)
# ==================================================================
def call_groq(messages, temperature, max_tokens):
    import time
    errors = []
    for model in AI_MODELS:
        try:
            print(f"🤖 تلاش با مدل: {model}")
            resp = groq_client.chat.completions.create(
                model=model,
                messages=messages,
                temperature=temperature,
                max_tokens=max_tokens,
            )
            raw = resp.choices[0].message.content.strip()
            raw = strip_think_tags(raw)
            if raw:
                print(f"✅ مدل {model} موفق بود")
                return raw
            else:
                print(f"⚠️ مدل {model} خروجی خالی داد")
                continue
        except Exception as ex:
            err_msg = str(ex)[:200]
            errors.append(f"{model}: {err_msg}")
            print(f"⚠️ مدل {model} خطا داد: {err_msg}")
            # اگر rate limit خورد، کمی صبر کن
            if "rate_limit" in err_msg.lower() or "429" in err_msg:
                print("⏳ صبر ۵ ثانیه برای rate limit...")
                time.sleep(5)
            continue
    print(f"❌ همه مدل‌ها خطا دادند: {' | '.join(errors)}")
    return None

def calculate_news_weight(calendar_events=None):
    """محاسبه وزن اخبار بر اساس تقویم اقتصادی"""
    if not calendar_events:
        return 1.0, "بدون خبر مهم"
    
    high_count = sum(1 for ev in calendar_events 
                     if ev.get("impact") == "High" and ev.get("_today"))
    medium_count = sum(1 for ev in calendar_events 
                       if ev.get("impact") == "Medium" and ev.get("_today"))
    
    # اخبار با داده واقعی (منتشر شده) وزن بیشتری دارند
    released_count = sum(1 for ev in calendar_events 
                        if ev.get("actual") and ev.get("_today"))
    
    if high_count >= 2 or released_count >= 1:
        return 1.5, "چند خبر خیلی مهم"
    elif high_count == 1:
        return 1.3, "یک خبر مهم"
    elif medium_count >= 2:
        return 1.1, "اخبار متوسط"
    else:
        return 0.7, "بدون خبر مهم — سیگنال ضعیف‌تر"

def score_sentiment_ai(news_text, calendar_events=None):
    if not HAS_GROQ:
        return 0, 0, "هوش مصنوعی در دسترس نیست"
    try:
        messages = [
            {"role": "system", "content": (
                "تو تحلیل‌گر احساسات بازار یورو/دلار هستی. "
                "اخبار را می‌خوانی و فقط یک JSON برمی‌گردانی.\n\n"
                + ECON_RULES + "\n\n"
                "قوانین امتیازدهی:\n"
                "- خبر صعودی یورو (دلار ضعیف، کاهش نرخ، تورم پایین آمریکا) = bull\n"
                "- خبر نزولی یورو (دلار قوی، افزایش نرخ، تورم بالا آمریکا) = bear\n"
                "- کلمات نفی (not, unlikely) معنی را برعکس کن\n"
                "- خبر خنثی = 0/0\n"
                "- bull و bear بین 0 تا 15\n"
                "- اگر اخبار مختلط هستند، هم bull و هم bear عدد بده (مثلاً bull=6 bear=5)\n"
                "- وقتی خبر خاصی نیست، امتیازها را نزدیک هم بده (مثلاً bull=3 bear=3) نه اینکه یکی را خیلی بالا ببری\n"
                "- دلیل را کوتاه، دقیق و بدون تکرار بنویس (حداکثر ۲ جمله)\n\n"
                'خروجی فقط JSON: {"bull": عدد, "bear": عدد, "reason": "دلیل به فارسی"}'
            )},
            {"role": "user", "content": f"این اخبار را تحلیل کن:\n{news_text[:3000]}"},
        ]
        raw = call_groq(messages, temperature=0.15, max_tokens=250)
        if not raw:
            return 0, 0, "تحلیل ممکن نشد"
        s = raw.find("{")
        e = raw.rfind("}") + 1
        if s != -1 and e > s:
            data = json.loads(raw[s:e])
            bull = max(0, min(15, int(data.get("bull", 0))))
            bear = max(0, min(15, int(data.get("bear", 0))))
            reason = clean_foreign_chars(data.get("reason", ""))
            
            # اعمال وزن اخبار
            weight, weight_reason = calculate_news_weight(calendar_events)
            if weight != 1.0:
                bull = min(15, round(bull * weight))
                bear = min(15, round(bear * weight))
                print(f"[وزن‌دهی] ضریب={weight} ({weight_reason})")
            
            print(f"[احساسات] صعودی={bull} نزولی={bear} | {reason}")
            return bull, bear, reason
    except Exception as ex:
        print("خطا در تحلیل احساسات:", ex)
    return 0, 0, "تحلیل ممکن نشد"

def get_direction(bull, bear):
    diff = bull - bear
    total = bull + bear
    
    # بررسی دقت اخیر ربات برای تنظیم حساسیت
    perf = calculate_perf_from_json()
    accuracy = perf.get("accuracy", 100)
    decisive = perf.get("decisive", 0)
    
    # سیستم خنثی هوشمند: اگر دقت افت کرده، آستانه سخت‌تر شود
    if decisive >= 5 and accuracy < 40:
        # دقت خیلی پایین → خیلی محتاط
        min_diff_high = 7
        min_diff_medium = 5
        min_total = 6
        print(f"🛡️ حالت محتاط فعال (دقت={accuracy}٪) — آستانه‌های بالاتر")
    elif decisive >= 5 and accuracy < 55:
        # دقت متوسط → کمی محتاط‌تر
        min_diff_high = 6
        min_diff_medium = 4
        min_total = 5
        print(f"⚠️ حالت نیمه‌محتاط (دقت={accuracy}٪)")
    else:
        # دقت خوب یا داده کم → حالت عادی
        min_diff_high = 5
        min_diff_medium = 3
        min_total = 4
    
    # اگر مجموع امتیازها خیلی کم باشد → خنثی
    if total <= min_total:
        return "خنثی", "پایین"
    
    if diff >= min_diff_high:
        return "صعودی", "بالا"
    elif diff >= min_diff_medium:
        return "صعودی", "متوسط"
    elif diff <= -min_diff_high:
        return "نزولی", "بالا"
    elif diff <= -min_diff_medium:
        return "نزولی", "متوسط"
    else:
        return "خنثی", "پایین"

def summarize_speech_ai(speech_texts, speaker_name=""):
    if not HAS_GROQ:
        return None
    try:
        combined = "\n".join(speech_texts)[:3000]
        messages = [
            {"role": "system", "content": (
                "تو تحلیل‌گر اقتصادی حرفه‌ای هستی. متن سخنرانی یا اظهارات مقامات پولی را "
                "به فارسی روان و کوتاه خلاصه می‌کنی.\n\n"
                + ECON_RULES + "\n\n"
                "خروجی به این شکل:\n"
                "۱) سه تا پنج نکته کلیدی (هر کدام یک خط)\n"
                "۲) تأثیر بر یورو/دلار (صعودی/نزولی/خنثی) با دلیل منطقی\n\n"
                "مهم: همه چیز به فارسی باشد. کلمه انگلیسی نباشد."
            )},
            {"role": "user", "content": (
                f"این متن را خلاصه کن{' (سخنران: ' + speaker_name + ')' if speaker_name else ''}:\n{combined}"
            )},
        ]
        result = call_groq(messages, temperature=0.3, max_tokens=500)
        if result:
            return clean_foreign_chars(result)
        return None
    except Exception as ex:
        print("خطا در خلاصه سخنرانی:", ex)
        return None

def ai_analyze_fa(news_text, calendar_events, bull, bear, direction, confidence, performance, market_assets=None):
    if not HAS_GROQ:
        return None
    try:
        cal_text = ""
        if calendar_events:
            for ev in calendar_events[:4]:
                cal_text += f"- {country_fa(ev.get('country',''))}: {event_title_fa(ev)}\n"

        perf_note = ""
        if performance and performance.get("total", 0) >= 10:
            acc = performance["accuracy"]
            if acc < 50:
                perf_note = f"\nنکته: دقت اخیر ربات {acc}٪ است. با احتیاط تحلیل کن."
                
        market_text = ""
        if market_assets:
            market_text = f"شاخص دلار (DXY): {market_assets.get('DXY (شاخص دلار)', 'نامشخص')} | بازده اوراق 10 ساله آمریکا: {market_assets.get('US10Y (اوراق 10 ساله)', 'نامشخص')}% | طلا: {market_assets.get('Gold (طلا)', 'نامشخص')}$"

        # ساخت خودکار روایت بازار
        narrative = build_market_narrative(news_text[:1500] if isinstance(news_text, str) else "\n".join(news_text)[:1500])

        prompt = f"""تو تحلیل‌گر فاندامنتال حرفه‌ای و باتجربه یورو/دلار هستی.
فقط بر اساس اخبار و داده‌های اقتصادی تحلیل کن. تکنیکال اصلاً نباید.

{ECON_RULES}

قواعد سختگیرانه نگارش (حتماً رعایت کن):
- تحلیل جامع و عمیق (۲۰۰ تا ۳۰۰ کلمه)
- فقط و فقط داده‌های آمریکا (USD) و منطقه یورو (EUR) را لحاظ کن
- فقط فارسی. جملات را کامل بنویس و از نظر گرامری (داشتن فعل و فاعل در انتهای جمله) ساختار زبان فارسی را دقیقاً رعایت کن
- بدون هیچ کلمه انگلیسی
- جهت تحلیل باید با امتیاز هم‌خوانی داشته باشد
- هر نکته را فقط یک بار بگو. اگر یک مطلب را در بخش ۱ گفتی، در بخش‌های بعدی تکرار نکن
- اگر اطمینان "بالا" است، در متن ننویس "با احتیاط" یا "ممکن است". قاطع باش
- اگر اطمینان "پایین" است، قاطعانه ننویس. احتمالی بنویس
- هر بخش باید اطلاعات متفاوت و جدیدی ارائه دهد. تکرار = شکست
- در بخش ۲ فقط اعداد واقعی بازارهای موازی را تحلیل کن، حدس نزن

روایت غالب فعلی بازار (خودکار تولید شده):
{narrative}

وضعیت لحظه‌ای بازارهای موازی و چارت (برای تشخیص فیک‌اوت و پیش‌خور شدن استفاده کن):
{market_text if market_text else "داده در دسترس نیست"}

ساختار تحلیل (هر بخش باید محتوای منحصربه‌فرد داشته باشد):

۱) چشم‌انداز کلی (۲-۳ جمله):
- فقط وضعیت فعلی بازار و دلیل اصلی حرکت امروز

۲) تحلیل جریان پول هوشمند و واگرایی (۳-۴ جمله، این بخش بسیار مهم است):
- با استفاده از اعداد واقعی DXY و US10Y بررسی کن:
  الف) آیا جهت EUR/USD با DXY هم‌خوان است؟ (قانون ۱۲)
  ب) آیا واکنش US10Y نشان‌دهنده پیش‌خور شدن خبر است؟ (قانون ۱۱)
  ج) نتیجه‌گیری: آیا روند سالم است یا تله نقدینگی وجود دارد؟

۳) عوامل مؤثر (۲-۳ جمله):
- فقط عواملی که در بخش ۱ و ۲ نگفتی. مثلاً: نفت، ژئوپلیتیک، داده‌های منتظره

۴) چشم‌انداز کوتاه‌مدت (۱-۲ جمله):
- بازار امروز دقیقاً منتظر چه رویداد یا داده‌ای است؟

۵) توصیه نهایی (فقط یک جمله کوتاه و قاطع):
- اقدام عملی معامله‌گر. باید با جهت تعیین‌شده هم‌خوان باشد

اخبار:
{news_text[:2500]}

تقویم اقتصادی:
{cal_text if cal_text else "خبر مهمی نیست"}

امتیاز احساسات: صعودی={bull} | نزولی={bear}
جهت تعیین‌شده: {direction} | اطمینان: {confidence}
{perf_note}

مهم: تحلیل باید عمیق، منطقی و بدون تکرار باشد. هر بخش نکته جدیدی بگوید."""

        messages = [
            {"role": "system", "content": (
                "تو تحلیل‌گر فاندامنتال حرفه‌ای فارکس هستی. فقط فارسی بنویس. "
                "هیچ کلمه انگلیسی، چینی یا زبان دیگر استفاده نکن. "
                "قوانین مطلق: "
                "۱) هر نکته را فقط یک بار بگو - تکرار ممنوع. "
                "۲) اگر در بخش قبلی چیزی گفتی، در بخش بعدی تکرارش نکن. "
                "۳) تحلیل باید سازگار باشد - اگر جهت صعودی است، هیچ جمله نزولی ننویس. "
                "۴) لحن باید با سطح اطمینان هم‌خوان باشد."
            )},
            {"role": "user", "content": prompt},
        ]
        result = call_groq(messages, temperature=0.15, max_tokens=900)
        if result:
            cleaned = clean_foreign_chars(result)
            cleaned = re.sub(r'(?i)\bcause\b', 'باعث', cleaned)
            return cleaned
        return None
    except Exception as ex:
        print("خطا در تحلیل هوش مصنوعی:", ex)
        return None

# ==================================================================
# بخش ۱۱: ساخت پیام
# ==================================================================
def build_calendar_alert(events):
    date_fa, _ = get_date_fa()
    time_fa = get_time_fa()
    today_events = [ev for ev in events if ev.get("_today")]
    if not today_events:
        return (f"🌅 یادآور اقتصادی\n\n{date_fa} - {time_fa} تهران\n\n"
                f"امروز خبر مهمی نداریم.\n\n"
                f"{get_motivation(slot='morning')}")

    today_events.sort(key=lambda ev: (parse_event_dt(ev) or datetime.max.replace(tzinfo=TEHRAN_TZ)))
    lines = [f"🌅 یادآور اقتصادی", "", f"{date_fa} - {time_fa} تهران", "", "خبرهای مهم امروز:", ""]
    for ev in today_events:
        lines.extend([
            "━━━━━━━━━━━━━━",
            impact_fa(ev.get("impact", "")),
            f"🕒 ساعت: {event_time_fa(ev)}",
            f"🌍 کشور: {country_fa(ev.get('country', ''))}",
            f"📌 {event_title_fa(ev)}",
        ])
        if ev.get("forecast"):
            lines.append(f"📊 پیش‌بینی: {to_fa_digits(str(ev.get('forecast')))}")
        if ev.get("previous"):
            lines.append(f"📉 قبلی: {to_fa_digits(str(ev.get('previous')))}")
        lines.extend(["", "💡 اثر:", expected_impact_fa(ev), ""])

    lines.append("⚠️ نزدیک اخبار مهم، با احتیاط معامله کنید.")
    lines.append("")
    lines.append(get_motivation(slot="morning"))
    return "\n".join(lines)

def build_prealert(events):
    time_fa = get_time_fa()
    parts = ["⏰ هشدار: خبر مهم در راه است!", "", f"🕒 زمان: {time_fa} تهران", ""]
    for ev in events:
        parts.extend([
            "━━━━━━━━━━━━━━",
            f"🔴 {event_title_fa(ev)}",
            f"🕒 انتشار: {event_time_fa(ev)}",
            f"🌍 کشور: {country_fa(ev.get('country', ''))}",
        ])
        if ev.get("forecast"):
            parts.append(f"📊 پیش‌بینی: {to_fa_digits(str(ev.get('forecast')))}")
        if ev.get("previous"):
            parts.append(f"📉 قبلی: {to_fa_digits(str(ev.get('previous')))}")
        parts.extend(["", "💡 اثر:", expected_impact_fa(ev), ""])
    parts.extend([
        "⚠️ توصیه‌ها:",
        "• حجم معامله را کاهش دهید",
        "• ⚠️ هشدار نقدینگی: اسپردها در لحظه خبر شدیداً واید می‌شوند.",
        "• حد ضرر تنظیم کنید",
        "",
        get_motivation(direction="خنثی"),
    ])
    return "\n".join(parts)

def build_data_release_msg(hits):
    date_fa, _ = get_date_fa()
    time_fa = get_time_fa()
    parts = [f"📊 داده اقتصادی منتشر شد", "", f"{date_fa} - {time_fa} تهران", ""]
    for h in hits:
        parts.extend([
            "━━━━━━━━━━━━━━",
            f"📌 {translate_title(h.get('title', ''))}",
            f"🌍 کشور: {country_fa(h.get('country', ''))}",
            f"✅ واقعی: {to_fa_digits(str(h.get('actual', '')))}",
            f"📊 پیش‌بینی: {to_fa_digits(str(h.get('forecast', '')))}",
            f"📉 قبلی: {to_fa_digits(str(h.get('previous', '')))}",
            "",
            f"💡 اثر: {to_fa_digits(h.get('impact_text', ''))}",
            "",
        ])
    parts.append("⚠️ **هشدار نقدینگی:** در ثانیه‌های اول انتشار خبر، اسپردها به شدت واید می‌شوند. برای ورود به معامله حداقل ۳ تا ۵ دقیقه صبر کنید تا بازار تثبیت شود.")
    parts.append("")
    parts.append(get_motivation())
    return "\n".join(parts)

def build_speech_summary(speech_texts, speaker=""):
    date_fa, _ = get_date_fa()
    time_fa = get_time_fa()
    summary = summarize_speech_ai(speech_texts, speaker)
    parts = [
        "🎤 خلاصه اظهارات مقام پولی",
        "",
        f"{date_fa} - {time_fa} تهران",
        "",
    ]
    if speaker:
        parts.append(f"👤 سخنران: {speaker}")
        parts.append("")
    if summary:
        parts.append(summary)
    else:
        parts.append("خلاصه‌سازی ممکن نشد.")
    parts.extend(["", get_motivation()])
    return "\n".join(parts)

def build_fundamental_brief(news_text, bull, bear, direction, confidence, reason,
                            calendar_events=None, performance=None,
                            view_changed=False, prev_dir=None, prev_reason="",
                            slot_label="تحلیل فاندامنتال", slot=None, market_assets=None):
    date_fa, date_short = get_date_fa()
    time_fa = get_time_fa()

    emoji = "🟢" if direction == "صعودی" else ("🔴" if direction == "نزولی" else "🟡")

    parts = [
        f"{emoji} {slot_label} یورو/دلار",
        "",
        f"{date_fa} - {time_fa} تهران",
        "",
        f"📐 جهت: {direction}",
        f"🔒 اطمینان: {confidence}",
        f"📊 امتیاز: صعودی {to_fa_digits(str(bull))} / نزولی {to_fa_digits(str(bear))}",
        f"💡 دلیل: {reason}",
        "",
    ]
    
    if market_assets:
        market_str = " | ".join([f"{k}: {v}" for k, v in market_assets.items()])
        parts.append(f"🌐 بازارهای موازی: {to_fa_digits(market_str)}")
        parts.append("")

    if view_changed and prev_dir:
        parts.extend([
            "━━━━━━━━━━━━━━",
            "🔄 تغییر دیدگاه ربات!",
            f"   قبلی: {prev_dir}",
            f"   جدید: {direction}",
        ])
        if prev_reason:
            parts.append(f"   دلیل قبلی: {prev_reason}")
        parts.append(f"   دلیل تغییر: {reason}")
        parts.append("")
        parts.append("⚠️ جهت بازار عوض شده. با احتیاط!")
        parts.append("")

    ai = ai_analyze_fa(news_text, calendar_events, bull, bear, direction, confidence, performance, market_assets)
    if ai:
        parts.extend(["━━━━━━━━━━━━━━", "🤖 تحلیل (مبتنی بر روایت فعلی بازار):", "", ai, ""])

    if calendar_events:
        now_te = datetime.now(TEHRAN_TZ)
        today_upcoming = []
        tomorrow_ev = []
        for ev in calendar_events:
            if ev.get("_today"):
                dt = parse_event_dt(ev)
                if dt and dt.astimezone(TEHRAN_TZ) > now_te:
                    today_upcoming.append(ev)
            elif ev.get("_tomorrow"):
                tomorrow_ev.append(ev)
        cal_lines = []
        if today_upcoming:
            cal_lines.append("📅 اخبار پیش‌رو امروز:")
            for ev in today_upcoming[:3]:
                cal_lines.append(f"  • {event_time_fa(ev)} | {country_fa(ev.get('country',''))} | {event_title_fa(ev)}")
        if tomorrow_ev:
            if today_upcoming:
                cal_lines.append("")
            cal_lines.append("📅 فردا:")
            for ev in tomorrow_ev[:3]:
                cal_lines.append(f"  • {event_time_fa(ev)} | {country_fa(ev.get('country',''))} | {event_title_fa(ev)}")
        if cal_lines:
            parts.extend(cal_lines)
            parts.append("")

    if performance and performance.get("total", 0) >= 1:
        parts.append(build_performance_view(performance))
        parts.append("")

    parts.append(get_motivation(direction=direction, slot=slot, view_changed=view_changed))
    parts.append("")
    parts.append(f"@EURUSDFaBot | {date_short}")

    msg = "\n".join(parts)

    voice_parts = [
        f"تحلیل فاندامنتال یورو دلار، {date_short}.",
        f"جهت: {direction}.",
    ]
    if view_changed:
        voice_parts.append(f"توجه: جهت بازار از {prev_dir} به {direction} تغییر کرد.")
    voice_parts.append("با مدیریت ریسک معامله کنید.")
    voice = "\n".join(voice_parts)

    return msg, voice
                                
# ==================================================================
# بخش ۱۲: تلگرام
# ==================================================================
def send_text(text):
    if TELEGRAM_TOKEN.startswith("PUT_"):
        print("=== اجرای تستی ===")
        print(text[:2000])
        return True
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    max_len = 4000
    if len(text) <= max_len:
        chunks = [text]
    else:
        chunks = []
        while text:
            chunk = text[:max_len]
            nl = chunk.rfind("\n")
            if nl > max_len // 2:
                chunk = chunk[:nl]
            chunks.append(chunk)
            text = text[len(chunk):].lstrip()
    for chunk in chunks:
        try:
            requests.post(url, data={
                "chat_id": CHAT_ID, "text": chunk,
                "disable_web_page_preview": True,
            }, timeout=20)
        except Exception as ex:
            print("خطا در ارسال:", ex)
    return True

def send_voice(text_fa):
    if not SEND_VOICE:
        return False
    text_fa = normalize_voice_text(text_fa)
    audio = None
    try:
        import edge_tts, asyncio, tempfile
        voice = os.getenv("VOICE_NAME", VOICE_NAME)

        async def _synth():
            comm = edge_tts.Communicate(text_fa, voice, rate=VOICE_RATE, pitch=VOICE_PITCH)
            with tempfile.NamedTemporaryFile(delete=False, suffix=".mp3") as tf:
                p = tf.name
            await comm.save(p)
            return p

        audio = asyncio.run(_synth())
        if TELEGRAM_TOKEN.startswith("PUT_"):
            return True
        url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendAudio"
        with open(audio, "rb") as f:
            requests.post(url, data={
                "chat_id": CHAT_ID, "title": "تحلیل یورو/دلار",
                "performer": "دستیار فاندامنتال", "caption": "تحلیل صوتی",
            }, files={"audio": f}, timeout=30)
        return True
    except Exception as ex:
        print("خطا در صوت:", ex)
        return False
    finally:
        try:
            if audio and os.path.exists(audio):
                os.unlink(audio)
        except Exception:
            pass
            
# ==================================================================
# بخش ۱۳: اجرا
# ==================================================================
def build_weekly_report():
    date_fa, _ = get_date_fa()
    news = fetch_all_news()
    week_events = get_week_events()
    market_assets = get_market_assets()
    cal = get_today_events()
    bull, bear, reason = score_sentiment_ai("\n".join(news), calendar_events=cal)
    direction, confidence = get_direction(bull, bear)
    performance = verify_predictions()

    parts = ["📊 گزارش هفتگی یورو/دلار", "", date_fa, "", "━━━━━━━━━━━━━━"]
    if performance and performance.get("total", 0) > 0:
        parts.extend([build_performance_view(performance), ""])
        
    if market_assets:
        market_str = " | ".join([f"{k}: {v}" for k, v in market_assets.items()])
        parts.extend([f"🌐 وضعیت پایانی بازارها:", to_fa_digits(market_str), ""])
        
    parts.extend([
        f"📐 جهت هفته: {direction}",
        f"🔒 اطمینان: {confidence}",
        f"📊 امتیاز: صعودی {to_fa_digits(str(bull))} / نزولی {to_fa_digits(str(bear))}",
        f"💡 دلیل: {reason}",
        "",
    ])
    ai = ai_analyze_fa(news, week_events, bull, bear, direction, confidence, performance, market_assets)
    if ai:
        parts.extend(["━━━━━━━━━━━━━━", "🤖 تحلیل:", "", ai, ""])
    parts.extend(["━━━━━━━━━━━━━━", "📅 خبرهای مهم هفته آینده:"])
    if week_events:
        for ev in week_events[:10]:
            parts.append(f"• {event_time_fa(ev)} | {country_fa(ev.get('country',''))} | {event_title_fa(ev)}")
    else:
        parts.append("خبر مهمی ثبت نشده.")
    parts.extend(["", get_motivation(), "", f"@EURUSDFaBot | {date_fa}"])
    return "\n".join(parts)

def run_once(slot="manual"):
    now = datetime.now(TEHRAN_TZ)

    if slot == "verify":
        perf = verify_predictions()
        if perf:
            print("عملکرد:", perf)
        return

    if slot == "weekly" or (slot == "evening" and now.weekday() == 4):
        try:
            report = build_weekly_report()
            send_text(report)
            if SEND_VOICE:
                send_voice("گزارش هفتگی یورو دلار آماده است.")
        except Exception as e:
            print("خطای گزارش هفتگی:", e)
        if slot == "weekly":
            return

    if slot == "watch":
        try:
            upcoming = check_upcoming_events()
            if upcoming:
                send_text(build_prealert(upcoming))
                if SEND_VOICE:
                    send_voice("هشدار: خبر مهم در راه است.")
        except Exception as e:
            print("خطای هشدار:", e)

    if slot == "watch":
        print("[رصد] بررسی...")
        try:
            verify_predictions()
            hits = check_live_news()
            headlines = check_breaking_headlines() if not hits else []

            if not hits and not headlines:
                print("[رصد] خبر جدیدی نیست.")
                return

            all_new_text = ""
            if hits:
                for h in hits:
                    all_new_text += f"{h.get('title','')} {h.get('actual','')} {h.get('impact_text','')}\n"
            if headlines:
                all_new_text += "\n".join(headlines)

            speaker = detect_speaker(all_new_text)
            is_speech = is_speech_related(all_new_text) or bool(speaker)

            if hits:
                send_text(build_data_release_msg(hits))
                if SEND_VOICE:
                    send_voice("داده اقتصادی جدید منتشر شد.")

            wait, next_title = should_wait_for_more_news()
            if wait:
                print(f"[رصد] خبر '{next_title}' در راه است → صبر می‌کنیم")
                add_to_batch(all_new_text)
                return

            batch = load_batch()
            if batch.get("items"):
                all_new_text = "\n".join(batch["items"]) + "\n" + all_new_text
                clear_batch()

            news = fetch_all_news()
            full_news = all_new_text + "\n" + "\n".join(news)

            cal = get_today_events()
            bull, bear, reason = score_sentiment_ai(full_news, calendar_events=cal)
            direction, confidence = get_direction(bull, bear)

            view_changed, prev_dir, prev_reason = check_view_change(direction, reason)
            perf_summary = verify_predictions()
            market_assets = get_market_assets()

            msg, voice = build_fundamental_brief(
                full_news, bull, bear, direction, confidence, reason,
                calendar_events=cal, performance=perf_summary,
                view_changed=view_changed, prev_dir=prev_dir, prev_reason=prev_reason,
                slot_label="🔔 تحلیل خبر فوری", slot="watch", market_assets=market_assets
            )
            send_text(msg)

            if is_speech:
                try:
                    speech_msg = build_speech_summary([all_new_text] + headlines, speaker)
                    if speech_msg:
                        send_text(speech_msg)
                        if SEND_VOICE:
                            send_voice("خلاصه اظهارات مقام پولی آماده است.")
                except Exception as ex:
                    print("خطای خلاصه سخنرانی:", ex)

            save_view(direction, confidence, reason)

            if SEND_VOICE:
                send_voice(voice)

        except Exception as e:
            print("خطای رصد:", e)
        return

    print(f"[{slot}] در حال دریافت...")
    verify_predictions()

    news = fetch_all_news()
    cal = get_today_events()
    bull, bear, reason = score_sentiment_ai("\n".join(news), calendar_events=cal)
    direction, confidence = get_direction(bull, bear)
    market_assets = get_market_assets()

    view_changed, prev_dir, prev_reason = check_view_change(direction, reason)
    perf_summary = verify_predictions()

    slot_label = SCHEDULES.get(slot, SCHEDULES["manual"])["label"]

    if slot == "morning":
        try:
            send_text(build_calendar_alert(cal))
        except Exception as ex:
            print("خطای تقویم صبحگاهی:", ex)

    msg, voice = build_fundamental_brief(
        "\n".join(news), bull, bear, direction, confidence, reason,
        calendar_events=cal, performance=perf_summary,
        view_changed=view_changed, prev_dir=prev_dir, prev_reason=prev_reason,
        slot_label=slot_label, slot=slot, market_assets=market_assets
    )
    send_text(msg)

    save_view(direction, confidence, reason)
    if slot == "morning":
        has_news = bool(cal)
        save_prediction(direction, confidence, slot, has_news=has_news)

    if SEND_VOICE:
        send_voice(voice)

# ==================================================================
# بخش ۱۴: اصلی
# ==================================================================
if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="دستیار خبر فاندامنتال یورو/دلار")
    parser.add_argument("--slot", choices=[
        "morning", "us_preopen", "evening",
        "manual", "watch", "weekly", "verify",
    ], default="manual")
    args = parser.parse_args()
    run_once(args.slot if args.slot else "manual")
