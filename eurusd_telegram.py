#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
دستیار خبر فاندامنتال یورو/دلار – نسخه نهایی
فقط فاندامنتال + خلاصه سخنرانی + واکنش سریع + batching هوشمند + پیام‌های انگیزشی

✅ قابلیت‌ها:
   1) همه اخبار مرتبط یورو/دلار را ارسال می‌کند
   2) سخنرانی‌های مهم را به فارسی خلاصه می‌کند
   3) با سرعت به داده‌ها واکنش نشان می‌دهد و تغییر دیدگاه را اطلاع می‌دهد
   4) اخبار پشت‌سرهم را با هم تحلیل می‌کند (batching)
   5) پیام‌های انگیزشی و روحیه‌بخش متناسب با وضعیت بازار

❌ حذف شده:
   - تحلیل تکنیکال
   - هشدار نوسان شدید
   - شاخص‌ها و جفت‌ارزهای مرتبط
   - کلمات انگلیسی در خروجی
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

SEEN_FILE = "seen_events.json"
PREDICTIONS_FILE = "predictions.json"
LAST_VIEW_FILE = "last_view.json"
BATCH_FILE = "news_batch.json"

TEHRAN_TZ = timezone(timedelta(hours=3, minutes=30))

SCHEDULES = {
    "morning": {"hour": 7, "minute": 30, "label": "🌅 تحلیل صبحگاهی"},
    "us_preopen": {"hour": 16, "minute": 0, "label": "🌆 قبل بازار آمریکا"},
    "evening": {"hour": 18, "minute": 0, "label": "🌙 جمع‌بندی روز"},
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

# کلمات کلیدی برای تشخیص سخنرانی (انگلیسی - چون اخبار انگلیسی‌اند)
SPEECH_INDICATORS = [
    "speech", "testimony", "statement", "press conference",
    "says", "speaks", "told", "warns", "urges", "remarks",
    "prepared text", "q&a", "qa", "questions",
]

# ==================================================================
# قوانین اقتصادی جامع EUR/USD — در همه پرامپت‌ها استفاده می‌شود
# این قوانین از اشتباهات منطقی هوش مصنوعی جلوگیری می‌کند
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
- پاراگراف‌های تکراری نساز"""

# 🔴 کلماتی که نشان‌دهنده خبر واقعاً فوری/مهم هستند (نه مقاله معمولی)
BREAKING_KEYWORDS = [
    # حرکات شدید قیمت
    "surges", "plunges", "plummets", "spikes", "jumps", "slides",
    "crashes", "soars", "tumbles", "slumps", "collapses", "skyrockets",
    "selloff", "sell-off", "rallies", "rally",
    "sharply lower", "sharply higher", "sharply down", "sharply up",
    "falls sharply", "rises sharply", "drops sharply", "dives", "nosedives",
    "tumbles after", "jumps after", "falls after", "rises after", "drops after",
    "slips", "dumps",
    # فوریت
    "breaking", "urgent", "shock", "unexpected", "surprise", "surprisingly",
    "crisis", "emergency", "alert", "just in",
    # بانک‌های مرکزی
    "cuts rates", "raises rates", "rate decision", "rate hike", "rate cut",
    "emergency cut", "emergency hike", "unexpected rate",
    # داده‌های اقتصادی
    "beats expectations", "misses expectations", "comes in", "actual",
    "surges past", "drops below", "cooler than", "hotter than",
    # ژئوپلیتیک
    "attack", "strikes", "sanctions", "invasion", "retaliation",
    "escalation", "ceasefire", "tariffs imposed", "trade war",
    # طلا/نفت
    "oil surges", "oil plunges", "oil crisis", "gold surges",
    "gold plummets", "crude crashes",
]

# کلماتی که نشان‌دهنده مقاله معمولی/تحلیلی هستند (نباید فوری حساب شوند)
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

# دیکشنری سخنرانان (انگلیسی → فارسی)
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

# ترجمه کشورها
COUNTRY_FA = {
    "USD": "آمریکا", "EUR": "یوروزون", "EMU": "یوروزون",
    "US": "آمریکا", "EU": "یوروزون",
}

# ترجمه عناوین خبری رایج
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
# بخش ۱: پیام‌های انگیزشی و روحیه‌بخش
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
    "✨ باد مال сторону — بادبان را تنظیم کن!",
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
    """انتخاب پیام انگیزشی متناسب با وضعیت"""
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
    """
    حذف کاراکترهای غیرفارسی و غیرانگلیسی (چینی، هندی، فرانسوی و...).
    فقط حروف فارسی، انگلیسی، اعداد، نقطه‌گذاری و ایموجی نگه می‌دارد.
    """
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


def translate_title(title):
    """ترجمه عنوان خبر به فارسی"""
    low = title.lower().strip()
    for eng, fa in TITLE_TRANSLATIONS.items():
        if eng in low:
            return fa
    return title


def to_fa_digits(text):
    """تبدیل ارقام انگلیسی به فارسی"""
    fa = "۰۱۲۳۴۵۶۷۸۹"
    for i, d in enumerate("0123456789"):
        text = text.replace(d, fa[i])
    return text


def get_date_fa():
    """تاریخ شمسی"""
    now = datetime.now(TEHRAN_TZ)
    if HAS_JALALI:
        jd = jdatetime.datetime.fromgregorian(datetime=now)
        return jd.strftime("%A %d %B %Y"), jd.strftime("%d %B")
    return now.strftime("%Y-%m-%d"), now.strftime("%d %b")


def get_time_fa():
    """زمان فعلی تهران"""
    now = datetime.now(TEHRAN_TZ)
    return to_fa_digits(now.strftime("%H:%M"))


def normalize_voice_text(text):
    """پاکسازی متن برای صوت"""
    text = str(text or "").strip()
    for ch in ["/", "|", "-", "_", "•", "📌", "📅", "📰", "⚖️",
               "🤖", "🔔", "🌅", "🌆", "🌙", "🟢", "🟡", "🔴",
               "🚨", "📊", "⏰", "🔄", "🎤", "💡", "✅", "❌", "⚪",
               "━", "💪", "📉", "📈", "💎", "🎯", "⚡", "🌟", "🏔️",
               "🔮", "🛡️", "🌈", "🚀", "✨", "🌊", "🧠", "🧘",
               "⏳", "☀️", "🌄", "🔭", "💫", "👤"]:
        text = text.replace(ch, " ")
    text = text.replace("ي", "ی").replace("ك", "ک")
    text = re.sub(r"\s+", " ", text).strip()
    return text


def is_relevant_news(text):
    """آیا خبر به یورو/دلار مربوط است؟"""
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
    """آیا خبر به سخنرانی/اظهارات مربوط است؟"""
    low = clean_html_text(text).lower()
    return any(k in low for k in SPEECH_INDICATORS)


def is_breaking_news(text):
    """
    آیا این خبر واقعاً فوری/مهم است؟
    فقط اخباری که کلمه فوری دارند و کلمه معمولی ندارند.
    این تابع ربات را از اسپم زدن جلوگیری می‌کند.
    """
    low = clean_html_text(text).lower()

    # اگر مقاله معمولی است → نه
    if any(k in low for k in ROUTINE_KEYWORDS):
        return False

    # اگر سخنرانی است → بله (مهم است)
    if is_speech_related(text):
        return True

    # اگر کلمه فوری دارد → بله
    if any(k in low for k in BREAKING_KEYWORDS):
        return True

    return False


def detect_speaker(text):
    """تشخیص سخنران از متن خبر (انگلیسی → فارسی)"""
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
# بخش ۴: قیمت + ATR
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
# بخش ۵: سیستم ردیابی دیدگاه + تغییر
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
    """بررسی: آیا دیدگاه ربات تغییر کرده؟"""
    prev = load_last_view()
    prev_dir = prev.get("direction")
    if prev_dir and prev_dir != new_direction and new_direction != "خنثی":
        return True, prev_dir, prev.get("reason", "")
    return False, prev_dir, ""


# ==================================================================
# بخش ۶: سیستم batching هوشمند
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
    save_batch(batch)


def should_wait_for_more_news():
    """آیا در ۲۵ دقیقه آینده خبر مهمی در راه است؟ اگر بله → صبر کن"""
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
    """
    ارزیابی پیش‌بینی‌ها — فقط بعد از ۲۴ ساعت.
    منطق: ۳۰ پیپ در جهت پیش‌بینی = درست، ۳۰ پیپ خلاف = اشتباه، کمتر = خنثی.
    """
    predictions = load_json(PREDICTIONS_FILE, {})
    if not predictions:
        return {"total": 0, "correct": 0, "wrong": 0, "neutral": 0, "accuracy": 0}

    current = get_eurusd_price()
    if not current:
        return None
    now = datetime.now(TEHRAN_TZ)
    threshold = 30.0  # آستانه ثابت ۳۰ پیپ
    changed = False

    for pid, pred in predictions.items():
        if pred.get("verified"):
            continue
        try:
            ptime = datetime.fromisoformat(pred["timestamp"])
            hours = (now - ptime).total_seconds() / 3600
            if hours < 24:
                continue
            old = pred.get("price_at_prediction", 0)
            if not old:
                continue
            change = round((current - old) * 10000, 1)
            d = pred.get("direction", "خنثی")

            # منطق جدید: ۳۰ پیپ ثابت
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
        return {"total": 0, "correct": 0, "wrong": 0, "neutral": 0, "accuracy": 0}
    correct = sum(1 for p in verified if p["result"] == "correct")
    return {
        "total": total, "correct": correct,
        "wrong": sum(1 for p in verified if p["result"] == "wrong"),
        "neutral": sum(1 for p in verified if p["result"] == "neutral"),
        "accuracy": round(correct / total * 100, 1),
    }


def build_performance_view(perf):
    if not perf or perf.get("total", 0) < 1:
        return "🎯 عملکرد ربات:\nهنوز داده کافی نیست."
    acc = perf["accuracy"]
    if acc >= 70:
        rating = "🟢 عالی"
    elif acc >= 55:
        rating = "🟡 خوب"
    elif acc >= 45:
        rating = "🟠 متوسط"
    else:
        rating = "🔴 در حال یادگیری"
    return (
        f"🎯 عملکرد ربات ({to_fa_digits(str(perf['total']))} پیش‌بینی):\n"
        f"{rating} دقت: {to_fa_digits(str(acc))}٪\n"
        f"✅ درست: {to_fa_digits(str(perf['correct']))} | "
        f"❌ اشتباه: {to_fa_digits(str(perf['wrong']))} | "
        f"⚪ خنثی: {to_fa_digits(str(perf['neutral']))}"
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
    """اثر احتمالی خبر به فارسی — با سناریوهای کامل"""
    title = (ev.get("title") or "").lower()
    country = (ev.get("country") or "").upper()
    if country == "USD" and any(k in title for k in ["cpi", "inflation", "pce"]):
        return "تورم بالاتر ← دلار قوی ← نزولی یورو\nتورم پایین‌تر ← دلار ضعیف ← صعودی یورو"
    if country == "USD" and any(k in title for k in ["nfp", "payroll", "employment"]):
        return "اشتغال قوی ← دلار قوی ← نزولی یورو\nاشتغال ضعیف ← دلار ضعیف ← صعودی یورو"
    if country == "USD" and any(k in title for k in ["jobless", "unemployment"]):
        return "بیکاری بالاتر ← دلار ضعیف ← صعودی یورو\nبیکاری پایین‌تر ← دلار قوی ← نزولی یورو"
    if country == "USD" and any(k in title for k in ["fomc", "fed", "powell", "warsh"]):
        return "لحن سخت‌گیرانه ← دلار قوی ← نزولی یورو\nلحن ملایم ← دلار ضعیف ← صعودی یورو"
    if country in ["EUR", "EMU"] and any(k in title for k in ["cpi", "inflation", "hicp"]):
        return "تورم بالاتر ← یورو قوی ← صعودی\nتورم پایین‌تر ← یورو ضعیف ← نزولی"
    if country in ["EUR", "EMU"] and any(k in title for k in ["ecb", "lagarde"]):
        return "لحن سخت‌گیرانه بانک مرکزی اروپا ← یورو قوی ← صعودی\nلحن ملایم ← یورو ضعیف ← نزولی"
    if any(k in title for k in ["retail sales", "retail"]):
        return "فروش قوی‌تر از انتظار ← مصرف قوی ← دلار قوی ← نزولی یورو\nفروش ضعیف‌تر ← دلار ضعیف ← صعودی یورو"
    if any(k in title for k in ["philly", "manufacturing", "ism", "pmi", "industrial"]):
        return "شاخص بالاتر از انتظار ← تولید قوی ← دلار قوی ← نزولی یورو\nشاخص پایین‌تر ← دلار ضعیف ← صعودی یورو"
    if any(k in title for k in ["gdp", "growth"]):
        return "رشد بالاتر ← دلار قوی ← نزولی یورو\nرشد پایین‌تر ← دلار ضعیف ← صعودی یورو"
    if any(k in title for k in ["consumer sentiment", "consumer confidence"]):
        return "اعتماد بالاتر ← مصرف قوی ← دلار قوی ← نزولی یورو\nاعتماد پایین‌تر ← دلار ضعیف ← صعودی یورو"
    if any(k in title for k in ["durable goods", "orders"]):
        return "سفارشات بالاتر ← دلار قوی ← نزولی یورو\nسفارشات پایین‌تر ← دلار ضعیف ← صعودی یورو"
    if any(k in title for k in ["housing", "home sales", "building"]):
        return "داده مسکن قوی ← دلار قوی ← نزولی یورو\nداده ضعیف ← دلار ضعیف ← صعودی یورو"
    if any(k in title for k in ["trade balance", "current account"]):
        return "تراز بهتر ← دلار قوی ← نزولی یورو\nتراز بدتر ← دلار ضعیف ← صعودی یورو"
    return "داده بهتر از انتظار ← دلار قوی ← نزولی یورو\nداده ضعیف‌تر از انتظار ← دلار ضعیف ← صعودی یورو"


def event_number(val):
    m = re.search(r"[-+]?\d+(?:\.\d+)?", str(val or "").replace(",", ""))
    return float(m.group()) if m else None


def released_impact_fa(ev):
    """اثر خبر منتشرشده"""
    title = (ev.get("title") or "").lower()
    country = (ev.get("country") or "").upper()
    actual = event_number(ev.get("actual"))
    forecast = event_number(ev.get("forecast"))
    if actual is None or forecast is None:
        return "داده واقعی/پیش‌بینی در دسترس نیست."
    if actual == forecast:
        return "عدد واقعی مطابق پیش‌بینی ← اثر خنثی."
    higher = actual > forecast
    if country == "USD" and any(k in title for k in ["jobless", "unemployment"]):
        return "بیکاری بالاتر از انتظار ← دلار ضعیف ← صعودی یورو." if higher else "بیکاری پایین‌تر ← دلار قوی ← نزولی یورو."
    if country == "USD":
        return "داده آمریکا قوی‌تر از انتظار ← دلار قوی ← نزولی یورو." if higher else "داده آمریکا ضعیف‌تر ← دلار ضعیف ← صعودی یورو."
    if country in ["EUR", "EMU"]:
        return "داده اروپا بهتر از انتظار ← یورو قوی ← صعودی." if higher else "داده اروپا ضعیف‌تر ← یورو ضعیف ← نزولی."
    return "اثر باید با واکنش بازار بررسی شود."


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
    """هشدار ۳۰ دقیقه قبل از خبر مهم"""
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
    """بررسی داده‌های اقتصادی منتشرشده"""
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
    """
    بررسی تیترهای فوری — فقط خبر واقعاً مهم.
    مقاله‌های معمولی (preview, wrap, analysis) نادیده گرفته می‌شوند.
    """
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
                    # ✅ فقط خبر فوری — نه مقاله معمولی
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
# بخش ۱۰: هوش مصنوعی
# ==================================================================
def score_sentiment_ai(news_text):
    """تحلیل احساسات با هوش مصنوعی"""
    if not HAS_GROQ:
        return 0, 0, "هوش مصنوعی در دسترس نیست"
    try:
        resp = groq_client.chat.completions.create(
            model="qwen/qwen3-32b",
            messages=[
                {"role": "system", "content": (
                    "تو تحلیل‌گر احساسات بازار یورو/دلار هستی. "
                    "اخبار را می‌خوانی و فقط یک JSON برمی‌گردانی.\n\n"
                    + ECON_RULES + "\n\n"
                    "قوانین امتیازدهی:\n"
                    "- خبر صعودی یورو (دلار ضعیف، کاهش نرخ، تورم پایین آمریکا) = bull\n"
                    "- خبر نزولی یورو (دلار قوی، افزایش نرخ، تورم بالا آمریکا) = bear\n"
                    "- کلمات نفی (not, unlikely) معنی را برعکس کن\n"
                    "- خبر خنثی = 0/0\n"
                    "- bull و bear بین 0 تا 15\n\n"
                    'خروجی فقط JSON: {"bull": عدد, "bear": عدد, "reason": "دلیل به فارسی"}'
                )},
                {"role": "user", "content": f"این اخبار را تحلیل کن:\n{news_text[:3000]}"},
            ],
            temperature=0.2, max_tokens=250,
        )
        raw = resp.choices[0].message.content.strip()
        s = raw.find("{")
        e = raw.rfind("}") + 1
        if s != -1 and e > s:
            data = json.loads(raw[s:e])
            bull = max(0, min(15, int(data.get("bull", 0))))
            bear = max(0, min(15, int(data.get("bear", 0))))
            reason = clean_foreign_chars(data.get("reason", ""))
            print(f"[احساسات] صعودی={bull} نزولی={bear} | {reason}")
            return bull, bear, reason
    except Exception as ex:
        print("خطا در تحلیل احساسات:", ex)
    return 0, 0, "تحلیل ممکن نشد"


def get_direction(bull, bear):
    """تعیین جهت فقط از فاندامنتال"""
    diff = bull - bear
    if diff >= 4:
        return "صعودی", "بالا"
    elif diff >= 2:
        return "صعودی", "متوسط"
    elif diff <= -4:
        return "نزولی", "بالا"
    elif diff <= -2:
        return "نزولی", "متوسط"
    else:
        return "خنثی", "پایین"


def summarize_speech_ai(speech_texts, speaker_name=""):
    """خلاصه سخنرانی به فارسی"""
    if not HAS_GROQ:
        return None
    try:
        combined = "\n".join(speech_texts)[:3000]
        resp = groq_client.chat.completions.create(
            model="qwen/qwen3-32b",
            messages=[
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
            ],
            temperature=0.3, max_tokens=500,
        )
        return clean_foreign_chars(resp.choices[0].message.content.strip())
    except Exception as ex:
        print("خطا در خلاصه سخنرانی:", ex)
        return None


def ai_analyze_fa(news_text, calendar_events, bull, bear, direction, confidence, performance):
    """تحلیل جامع فاندامنتال — کاملاً فارسی و عمیق"""
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

        prompt = f"""تو تحلیل‌گر فاندامنتال حرفه‌ای و باتجربه یورو/دلار هستی.
فقط بر اساس اخبار و داده‌های اقتصادی تحلیل کن. تکنیکال اصلاً نباید.

{ECON_RULES}

قواعد:
- تحلیل جامع و عمیق (۲۰۰ تا ۳۰۰ کلمه)
- فقط فارسی
- بدون کلمه انگلیسی
- جهت تحلیل باید با امتیاز هم‌خوانی داشته باشد

ساختار تحلیل (مثل یک گزارش حرفه‌ای):

۱) چشم‌انداز کلی (یک پاراگراف):
- وضعیت فعلی بازار یورو/دلار را توصیف کن
- مهم‌ترین عامل هدایت‌کننده بازار را مشخص کن

۲) عوامل مؤثر (دو تا سه پاراگراف):
- هر عامل اقتصادی را با دلیل و منطق توضیح بده
- علت و معلول را واضح بگو
- به داده‌های اقتصادی، اخبار بانک مرکزی، ژئوپلیتیک اشاره کن

۳) نبض احساسات بازار (یک خط):
- آیا بازار ریسک‌پذیر است یا ریسک‌گریز؟
- دلار تقویت می‌شود یا ضعیف می‌شود؟

۴) چشم‌انداز کوتاه‌مدت (یک پاراگراف):
- بازار امروز به چه چیزی چشم دوخته است؟
- چه رویدادی می‌تواند جهت را تغییر دهد؟

۵) توصیه نهایی (یک خط):
- اقدام عملی معامله‌گر

اخبار:
{news_text[:2500]}

تقویم اقتصادی:
{cal_text if cal_text else "خبر مهمی نیست"}

امتیاز احساسات: صعودی={bull} | نزولی={bear}
جهت تعیین‌شده: {direction} | اطمینان: {confidence}
{perf_note}

مهم: تحلیل باید عمیق، منطقی و حرفه‌ای باشد. علت و معلول اقتصادی را دقیق بگو."""

        resp = groq_client.chat.completions.create(
            model="qwen/qwen3-32b",
            messages=[{"role": "system", "content": "تو تحلیل‌گر فاندامنتال حرفه‌ای فارکس هستی. فقط فارسی. تحلیل‌هایت عمیق و دقیق هستند. هیچ کلمه انگلیسی، چینی یا زبان دیگر استفاده نکن."},
                      {"role": "user", "content": prompt}],
            temperature=0.4, max_tokens=800,
        )
        result = resp.choices[0].message.content.strip()
        return clean_foreign_chars(result)
    except Exception as ex:
        print("خطا در تحلیل هوش مصنوعی:", ex)
        return None


# ==================================================================
# بخش ۱۱: ساخت پیام
# ==================================================================
def build_calendar_alert(events):
    """پیام یادآور اخبار امروز"""
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
    """هشدار ۳۰ دقیقه قبل از خبر"""
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
        "• حد ضرر تنظیم کنید",
        "",
        get_motivation(direction="خنثی"),
    ])
    return "\n".join(parts)


def build_data_release_msg(hits):
    """پیام انتشار داده اقتصادی"""
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
            f"💡 اثر: {h.get('impact_text', '')}",
            "",
        ])
    parts.append(get_motivation())
    return "\n".join(parts)


def build_speech_summary(speech_texts, speaker=""):
    """پیام خلاصه سخنرانی"""
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
                            slot_label="تحلیل فاندامنتال", slot=None):
    """پیام تحلیل جامع فاندامنتال — کاملاً فارسی"""
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

    # --- هشدار تغییر دیدگاه ---
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

    # --- تحلیل هوش مصنوعی ---
    ai = ai_analyze_fa(news_text, calendar_events, bull, bear, direction, confidence, performance)
    if ai:
        parts.extend(["━━━━━━━━━━━━━━", "🤖 تحلیل:", "", ai, ""])

    # --- تقویم امروز/فردا (فقط اخبار آینده) ---
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

    # --- عملکرد ---
    if performance and performance.get("total", 0) >= 1:
        parts.append(build_performance_view(performance))
        parts.append("")

    # --- پیام انگیزشی ---
    parts.append(get_motivation(direction=direction, slot=slot, view_changed=view_changed))
    parts.append("")
    parts.append(f"@EURUSDFaBot | {date_short}")

    msg = "\n".join(parts)

    # --- متن صوتی ---
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
    bull, bear, reason = score_sentiment_ai("\n".join(news))
    direction, confidence = get_direction(bull, bear)
    performance = verify_predictions()

    parts = ["📊 گزارش هفتگی یورو/دلار", "", date_fa, "", "━━━━━━━━━━━━━━"]
    if performance and performance.get("total", 0) > 0:
        parts.extend([build_performance_view(performance), ""])
    parts.extend([
        f"📐 جهت هفته: {direction}",
        f"🔒 اطمینان: {confidence}",
        f"📊 امتیاز: صعودی {to_fa_digits(str(bull))} / نزولی {to_fa_digits(str(bear))}",
        f"💡 دلیل: {reason}",
        "",
    ])
    ai = ai_analyze_fa(news, week_events, bull, bear, direction, confidence, performance)
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
        # --- هشدار پیش از خبر ---
        try:
            upcoming = check_upcoming_events()
            if upcoming:
                send_text(build_prealert(upcoming))
                if SEND_VOICE:
                    send_voice("هشدار: خبر مهم در راه است.")
        except Exception as e:
            print("خطای هشدار:", e)

    if slot == "watch":
        # --- رصد اخبار فوری ---
        print("[رصد] بررسی...")
        try:
            verify_predictions()
            hits = check_live_news()
            headlines = check_breaking_headlines() if not hits else []

            if not hits and not headlines:
                print("[رصد] خبر جدیدی نیست.")
                return

            # --- تشخیص: آیا این سخنرانی است؟ ---
            all_new_text = ""
            if hits:
                for h in hits:
                    all_new_text += f"{h.get('title','')} {h.get('actual','')} {h.get('impact_text','')}\n"
            if headlines:
                all_new_text += "\n".join(headlines)

            speaker = detect_speaker(all_new_text)
            is_speech = is_speech_related(all_new_text) or bool(speaker)

            # --- ۱. اگر داده اقتصادی منتشر شده → پیام داده ---
            if hits:
                send_text(build_data_release_msg(hits))
                if SEND_VOICE:
                    send_voice("داده اقتصادی جدید منتشر شد.")

            # --- ۲. batching: آیا باید صبر کنیم؟ ---
            wait, next_title = should_wait_for_more_news()
            if wait:
                print(f"[رصد] خبر '{next_title}' در راه است → صبر می‌کنیم")
                add_to_batch(all_new_text)
                return

            # --- ۳. خبرهای batch شده را اضافه کن ---
            batch = load_batch()
            if batch.get("items"):
                all_new_text = "\n".join(batch["items"]) + "\n" + all_new_text
                clear_batch()

            # --- ۴. دریافت همه اخبار + تحلیل ---
            news = fetch_all_news()
            full_news = all_new_text + "\n" + "\n".join(news)

            # --- ۵. تحلیل احساسات ---
            bull, bear, reason = score_sentiment_ai(full_news)
            direction, confidence = get_direction(bull, bear)

            # --- ۶. بررسی تغییر دیدگاه ---
            view_changed, prev_dir, prev_reason = check_view_change(direction, reason)

            # --- ۷. تقویم + عملکرد ---
            cal = get_today_events()
            perf_summary = verify_predictions()

            # --- ۸. ساخت پیام ---
            msg, voice = build_fundamental_brief(
                full_news, bull, bear, direction, confidence, reason,
                calendar_events=cal, performance=perf_summary,
                view_changed=view_changed, prev_dir=prev_dir, prev_reason=prev_reason,
                slot_label="🔔 تحلیل خبر فوری", slot="watch",
            )
            send_text(msg)

            # --- ۹. خلاصه سخنرانی (اگر هست) ---
            if is_speech:
                try:
                    speech_msg = build_speech_summary([all_new_text] + headlines, speaker)
                    if speech_msg:
                        send_text(speech_msg)
                        if SEND_VOICE:
                            send_voice("خلاصه اظهارات مقام پولی آماده است.")
                except Exception as ex:
                    print("خطای خلاصه سخنرانی:", ex)

            # --- ۱۰. ذخیره (فقط دیدگاه، نه پیش‌بینی رسمی) ---
            # در طول روز فقط دیدگاه ذخیره می‌شود. پیش‌بینی رسمی فقط صبح ثبت می‌شود.
            save_view(direction, confidence, reason)

            if SEND_VOICE:
                send_voice(voice)

        except Exception as e:
            print("خطای رصد:", e)
        return

    # --- اسلات‌های عادی (morning, us_preopen, evening, manual) ---
    print(f"[{slot}] در حال دریافت...")
    verify_predictions()

    news = fetch_all_news()
    cal = get_today_events()
    bull, bear, reason = score_sentiment_ai("\n".join(news))
    direction, confidence = get_direction(bull, bear)

    view_changed, prev_dir, prev_reason = check_view_change(direction, reason)
    perf_summary = verify_predictions()

    slot_label = SCHEDULES.get(slot, SCHEDULES["manual"])["label"]

    # --- پیام تقویم صبحگاهی ---
    if slot == "morning":
        try:
            send_text(build_calendar_alert(cal))
        except Exception as ex:
            print("خطای تقویم صبحگاهی:", ex)

    msg, voice = build_fundamental_brief(
        "\n".join(news), bull, bear, direction, confidence, reason,
        calendar_events=cal, performance=perf_summary,
        view_changed=view_changed, prev_dir=prev_dir, prev_reason=prev_reason,
        slot_label=slot_label, slot=slot,
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
