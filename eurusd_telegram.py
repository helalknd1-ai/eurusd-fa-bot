#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
EUR/USD Complete Trading Assistant – Persian – Telegram
نسخه نهایی جامع: فاندامنتال + تکنیکال + سیستم امتیاز ترکیبی

✅ همه قابلیت‌ها:
   1) تحلیل فاندامنتال (اخبار + تقویم + احساسات با AI)
   2) تحلیل تکنیکال (RSI + EMA + MACD + Bollinger + حمایت/مقاومت)
   3) سیستم امتیاز ترکیبی (فاندامنتال ۴۰٪ + تکنیکال ۳۵٪ + تقویم ۱۵٪ + همبستگی ۱۰٪)
   4) سیگنال صبحگاهی به‌عنوان اندیکاتور تأیید
   5) یادگیری از خطا + آستانه پویای ATR + بررسی ۲۴ ساعته
   6) هشدار خبر + هشدار نوسان + گزارش هفتگی
   7) صوت فارسی + تاریخ شمسی
"""

import os
import re
import json
import math
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

# ---------- AI (Groq) ----------
try:
    from groq import Groq
    GROQ_API_KEY = os.getenv("GROQ_API_KEY", "")
    HAS_GROQ = bool(GROQ_API_KEY)
    if HAS_GROQ:
        groq_client = Groq(api_key=GROQ_API_KEY)
except Exception as e:
    HAS_GROQ = False
    print("Groq not available:", e)

# ---------- CONFIG ----------
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN", "PUT_YOURS")
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "PUT_YOURS")
SEND_VOICE = os.getenv("SEND_VOICE", "true").lower() == "true"

VOICE_NAME = os.getenv("VOICE_NAME", "fa-IR-DilaraNeural")
VOICE_RATE = os.getenv("VOICE_RATE", "-12%")
VOICE_PITCH = os.getenv("VOICE_PITCH", "+0Hz")

NEWS_IMPACT_LEVELS = os.getenv("NEWS_IMPACT", "High,Medium").split(",")

SEEN_FILE = "seen_events.json"
PREDICTIONS_FILE = "predictions.json"
PERFORMANCE_FILE = "performance.json"

TEHRAN_TZ = timezone(timedelta(hours=3, minutes=30))

SCHEDULES = {
    "morning": {"hour": 7, "minute": 30, "label": "🌅 صبح – تحلیل باز شدن اروپا"},
    "news_morning": {"hour": 7, "minute": 40, "label": "☕ صبح – آپدیت خبری"},
    "us_preopen": {"hour": 16, "minute": 0, "label": "🌆 قبل بازار آمریکا"},
    "evening": {"hour": 18, "minute": 0, "label": "🌙 عصر – جمع‌بندی روز"},
    "watch": {"hour": 0, "minute": 0, "label": "🔔 رصد اخبار فوری"},
    "manual": {"hour": 0, "minute": 0, "label": "🔧 اجرای دستی"},
    "weekly": {"hour": 20, "minute": 0, "label": "📊 گزارش هفتگی"},
    "verify": {"hour": 0, "minute": 0, "label": "🎯 بررسی دقت"},
}

SOURCES = {
    "bloomberg_rss": [
        "https://feeds.bloomberg.com/markets/news.rss",
        "https://feeds.bloomberg.com/economics/news.rss",
    ],
    "bloomberg_web": "https://www.bloomberg.com/markets/currencies",
    "fxstreet_rss": "https://www.fxstreet.com/news/forex/feed",
    "forexlive": "https://www.forexlive.com/feed/",
    "ecb_press": "https://www.ecb.europa.eu/rss/press.html",
    "fed_press": "https://www.federalreserve.gov/feeds/press_all.xml",
}

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/126.0 Safari/537.36"
    ),
    "Accept-Language": "en-US,en;q=0.9,fa;q=0.8",
}

# کلمات کلیدی (فقط fallback)
BULLISH = [
    "dovish fed", "fed cut", "fed pause", "soft us cpi",
    "cooling inflation", "weak nfp", "weak payrolls",
    "higher jobless claims", "lower treasury yields",
    "ecb hawkish", "eurozone inflation beats",
    "dollar weak", "dxy down", "dollar retreats",
    "oil falls", "yields drop", "risk on",
    "fed pivots", "rate cut expected",
    "euro rises", "euro gains", "eur strength",
]
BEARISH = [
    "hawkish fed", "fed hike", "hot us cpi", "strong nfp",
    "strong payrolls", "lower jobless claims",
    "higher treasury yields", "ecb dovish",
    "eurozone inflation misses", "dollar strong", "dxy up",
    "oil prices", "oil jumps", "oil rises",
    "middle east", "iran strikes", "geopolitical tension",
    "yields rise", "yields highest", "rate hikes",
    "inflation risk", "hawkish expected",
    "euro falls", "euro weakens", "eur weakness",
    "risk off", "safe haven",
]


# ==================================================================
# بخش ۱: HELPERS
# ==================================================================
def clean_html_text(text):
    try:
        return BeautifulSoup(str(text), "html.parser").get_text(" ", strip=True)
    except Exception:
        return str(text or "").strip()


def is_relevant_news(text):
    low = clean_html_text(text).lower()
    direct_terms = ["eur/usd", "eurusd", "euro", "usd", "dollar",
                    "ecb", "fed", "fomc", "powell", "lagarde",
                    "eurozone", "treasury yields", "dxy"]
    macro_terms = ["inflation", "cpi", "pce", "nfp", "payroll",
                   "employment", "unemployment", "jobless claims",
                   "claims", "pmi", "gdp", "retail sales",
                   "interest rate", "rate cut", "rate hike", "yield"]
    region_terms = ["us", "u.s.", "united states", "america",
                    "euro area", "eurozone", "europe", "germany", "france"]
    geo_terms = ["iran", "hormuz", "war", "oil", "geopolitical", "risk-off", "risk off"]
    if any(k in low for k in direct_terms):
        return True
    if any(k in low for k in macro_terms) and any(k in low for k in region_terms):
        return True
    if any(k in low for k in geo_terms) and any(
        k in low for k in ["dollar", "euro", "fed", "ecb", "yield", "treasury", "risk"]
    ):
        return True
    return False


def normalize_voice_text(text):
    text = str(text or "").strip()
    replacements = {
        "EUR/USD": "یورو دلار", "EURUSD": "یورو دلار",
        "EUR": "یورو", "USD": "دلار",
        "ECB": "بانک مرکزی اروپا", "Fed": "فدرال رزرو",
        "FOMC": "کمیته فدرال رزرو",
        "CPI": "تورم مصرف کننده", "PCE": "تورم پی سی ای",
        "NFP": "اشتغال آمریکا", "PMI": "شاخص مدیران خرید",
        "GDP": "رشد اقتصادی", "DXY": "شاخص دلار",
        "ATR": "میانگین نوسان", "RSI": "آر اس آی",
        "MACD": "مک دی", "EMA": "میانگین متحرک",
        "High": "خیلی مهم", "Medium": "متوسط",
        "actual": "عدد واقعی", "forecast": "پیش بینی",
        "manual": "اجرای دستی", "watch": "خبر فوری",
    }
    for old, new in replacements.items():
        text = text.replace(old, new)
    for ch in ["/", "|", "-", "_", "•", "📌", "📅", "📰", "⚖️",
               "🤖", "🔔", "🌅", "☕", "🌆", "🌙", "🟢", "🟡", "🔴",
               "🚨", "📊", "⏰", "💹", "🌍", "🕒", "🎯", "✅", "❌", "⚪",
               "📏", "🛢️", "🥇", "📈", "📉", "💡", "━", "💪"]:
        text = text.replace(ch, " ")
    text = text.replace("ي", "ی").replace("ك", "ک")
    text = re.sub(r"\s+", " ", text).strip()
    return text


# ==================================================================
# بخش ۲: FILE MANAGEMENT
# ==================================================================
def load_json_file(filepath, default=None):
    try:
        if os.path.exists(filepath):
            with open(filepath, "r", encoding="utf-8") as f:
                return json.load(f)
    except Exception as ex:
        print(f"Load {filepath} error:", ex)
    return default if default is not None else {}


def save_json_file(filepath, data):
    try:
        with open(filepath, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    except Exception as ex:
        print(f"Save {filepath} error:", ex)


def load_seen_events():
    data = load_json_file(SEEN_FILE, {})
    today = datetime.now(TEHRAN_TZ).strftime("%Y-%m-%d")
    return {k: v for k, v in data.items() if v.get("date", "").startswith(today)}


def save_seen_events(seen):
    save_json_file(SEEN_FILE, seen)


# ==================================================================
# بخش ۳: PRICE + ATR
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
        print("get_eurusd_price error:", ex)
    return None


def get_eurusd_atr(period=14):
    """محاسبه ATR بر حسب pip"""
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
        if len(highs) < period + 1:
            return None
        valid_data = [(h, l, c) for h, l, c in zip(highs, lows, closes)
                      if h is not None and l is not None and c is not None]
        if len(valid_data) < period + 1:
            return None
        true_ranges = []
        for i in range(1, len(valid_data)):
            high, low, close = valid_data[i]
            prev_close = valid_data[i - 1][2]
            tr = max(high - low, abs(high - prev_close), abs(low - prev_close))
            true_ranges.append(tr)
        atr = sum(true_ranges[-period:]) / period
        atr_pips = round(atr * 10000, 1)
        return atr_pips
    except Exception as ex:
        print(f"get_eurusd_atr error: {ex}")
        return None


# ==================================================================
# بخش ۴: تحلیل تکنیکال (RSI, EMA, MACD, Bollinger, S/R)
# ==================================================================

def fetch_eurusd_ohlc(period="6mo"):
    """دریافت داده OHLC (Open, High, Low, Close) برای تکنیکال"""
    try:
        url = "https://query1.finance.yahoo.com/v8/finance/chart/EURUSD=X"
        params = {"range": period, "interval": "1d"}
        r = requests.get(url, params=params, headers=HEADERS, timeout=10)
        if r.status_code != 200:
            return None
        data = r.json()
        result = data.get("chart", {}).get("result", [])
        if not result:
            return None
        quotes = result[0].get("indicators", {}).get("quote", [{}])[0]
        timestamps = result[0].get("timestamp", [])
        closes = [c for c in quotes.get("close", []) if c is not None]
        highs = [h for h in quotes.get("high", []) if h is not None]
        lows = [l for l in quotes.get("low", []) if l is not None]
        opens = [o for o in quotes.get("open", []) if o is not None]
        if len(closes) < 50:
            return None
        return {"close": closes, "high": highs, "low": lows, "open": opens}
    except Exception as ex:
        print(f"fetch_eurusd_ohlc error: {ex}")
        return None


def calc_ema(values, period):
    """محاسبه میانگین متحرک نمایی (EMA)"""
    if len(values) < period:
        return None
    multiplier = 2 / (period + 1)
    ema = sum(values[:period]) / period
    for i in range(period, len(values)):
        ema = (values[i] - ema) * multiplier + ema
    return round(ema, 5)


def calc_rsi(closes, period=14):
    """محاسبه RSI"""
    if len(closes) < period + 1:
        return None
    gains = []
    losses = []
    for i in range(1, len(closes)):
        diff = closes[i] - closes[i - 1]
        gains.append(max(0, diff))
        losses.append(max(0, -diff))
    avg_gain = sum(gains[:period]) / period
    avg_loss = sum(losses[:period]) / period
    for i in range(period, len(gains)):
        avg_gain = (avg_gain * (period - 1) + gains[i]) / period
        avg_loss = (avg_loss * (period - 1) + losses[i]) / period
    if avg_loss == 0:
        return 100.0
    rs = avg_gain / avg_loss
    rsi = 100 - (100 / (1 + rs))
    return round(rsi, 1)


def calc_macd(closes):
    """محاسبه MACD"""
    if len(closes) < 35:
        return None, None, None
    ema12 = closes[0]
    ema26 = closes[0]
    mult12 = 2 / 13
    mult26 = 2 / 27
    macd_line = None
    for i in range(1, len(closes)):
        ema12 = (closes[i] - ema12) * mult12 + ema12
        ema26 = (closes[i] - ema26) * mult26 + ema26
        macd_line = ema12 - ema26
    if macd_line is None:
        return None, None, None
    # Signal line (EMA 9 of MACD) - simplified
    signal_line = macd_line * 0.8
    histogram = macd_line - signal_line
    return round(macd_line * 10000, 1), round(signal_line * 10000, 1), round(histogram * 10000, 1)


def calc_bollinger(closes, period=20):
    """محاسبه Bollinger Bands"""
    if len(closes) < period:
        return None, None, None
    recent = closes[-period:]
    sma = sum(recent) / period
    variance = sum((x - sma) ** 2 for x in recent) / period
    std = math.sqrt(variance)
    upper = round((sma + 2 * std), 5)
    lower = round((sma - 2 * std), 5)
    middle = round(sma, 5)
    return upper, middle, lower


def find_support_resistance(highs, lows, lookback=20):
    """یافتن حمایت و مقاومت"""
    if len(highs) < lookback or len(lows) < lookback:
        return None, None
    resistance = round(max(highs[-lookback:]), 4)
    support = round(min(lows[-lookback:]), 4)
    return support, resistance


def get_technical_signals():
    """
    محاسبه همه سیگنال‌های تکنیکال + امتیاز تکنیکال.
    خروجی: dict با همه اندیکاتورها + tech_score (-10 تا +10)
    """
    ohlc = fetch_eurusd_ohlc("6mo")
    if not ohlc:
        return None

    closes = ohlc["close"]
    highs = ohlc["high"]
    lows = ohlc["low"]
    current = closes[-1]

    signals = {}
    tech_score = 0  # از -10 تا +10

    # --- EMA (روند) ---
    ema20 = calc_ema(closes, 20)
    ema50 = calc_ema(closes, 50)
    ema200 = calc_ema(closes, 200) if len(closes) >= 200 else None

    signals["ema20"] = ema20
    signals["ema50"] = ema50
    signals["ema200"] = ema200

    if ema20 and ema50:
        if ema20 > ema50:
            signals["trend"] = "صعودی"
            tech_score += 2
        else:
            signals["trend"] = "نزولی"
            tech_score -= 2

    if ema200 and current > ema200:
        tech_score += 1
    elif ema200 and current < ema200:
        tech_score -= 1

    # --- RSI ---
    rsi = calc_rsi(closes, 14)
    signals["rsi"] = rsi
    if rsi:
        if rsi >= 70:
            signals["rsi_status"] = "اشباع خرید 🔴"
            tech_score -= 2
        elif rsi <= 30:
            signals["rsi_status"] = "اشباع فروش 🟢"
            tech_score += 2
        elif rsi >= 55:
            signals["rsi_status"] = "قوی 🟢"
            tech_score += 1
        elif rsi <= 45:
            signals["rsi_status"] = "ضعیف 🔴"
            tech_score -= 1
        else:
            signals["rsi_status"] = "خنثی 🟡"

    # --- MACD ---
    macd_line, signal_line, histogram = calc_macd(closes)
    signals["macd"] = macd_line
    signals["macd_signal"] = signal_line
    if macd_line is not None and signal_line is not None:
        if macd_line > signal_line:
            signals["macd_status"] = "صعودی 🟢"
            tech_score += 2
        else:
            signals["macd_status"] = "نزولی 🔴"
            tech_score -= 2

    # --- Bollinger Bands ---
    bb_upper, bb_middle, bb_lower = calc_bollinger(closes, 20)
    signals["bb_upper"] = bb_upper
    signals["bb_middle"] = bb_middle
    signals["bb_lower"] = bb_lower
    if bb_upper and bb_lower:
        if current >= bb_upper:
            signals["bb_status"] = "نزدیک سقف 🔴"
            tech_score -= 1
        elif current <= bb_lower:
            signals["bb_status"] = "نزدیک کف 🟢"
            tech_score += 1
        else:
            signals["bb_status"] = "وسط باند 🟡"

    # --- حمایت و مقاومت ---
    support, resistance = find_support_resistance(highs, lows, 20)
    signals["support"] = support
    signals["resistance"] = resistance
    if support and resistance:
        signals["price_position"] = "نزدیک مقاومت" if (current > (support + resistance) / 2) else "نزدیک حمایت"

    # --- ATR ---
    atr = get_eurusd_atr(14)
    signals["atr"] = atr

    # --- قیمت فعلی ---
    signals["current_price"] = round(current, 5)

    # --- محدود کردن امتیاز ---
    tech_score = max(-10, min(10, tech_score))
    signals["tech_score"] = tech_score

    return signals


def build_technical_view(tech):
    """ساخت نمایش تکنیکال برای پیام تلگرام"""
    if not tech:
        return "📈 تحلیل تکنیکال: داده در دسترس نیست."

    lines = ["📈 تحلیل تکنیکال:"]

    # روند
    trend = tech.get("trend", "نامشخص")
    trend_emoji = "🟢" if trend == "صعودی" else "🔴"
    lines.append(f"• روند (EMA): {trend_emoji} {trend}")

    # RSI
    rsi = tech.get("rsi")
    if rsi:
        lines.append(f"• RSI: {rsi} {tech.get('rsi_status', '')}")

    # MACD
    macd_status = tech.get("macd_status", "")
    if macd_status:
        lines.append(f"• MACD: {macd_status}")

    # Bollinger
    bb_status = tech.get("bb_status", "")
    if bb_status:
        lines.append(f"• Bollinger: {bb_status}")

    # حمایت و مقاومت
    support = tech.get("support")
    resistance = tech.get("resistance")
    if support and resistance:
        lines.append(f"• حمایت: {support} | مقاومت: {resistance}")

    # قیمت فعلی
    price = tech.get("current_price")
    if price:
        lines.append(f"• قیمت فعلی: {price}")

    # ATR
    atr = tech.get("atr")
    if atr:
        lines.append(f"• ATR: {atr} pips")

    # امتیاز تکنیکال نهایی
    score = tech.get("tech_score", 0)
    if score >= 4:
        score_text = "🟢 تکنیکال: صعودی قوی"
    elif score >= 2:
        score_text = "🟢 تکنیکال: صعودی"
    elif score <= -4:
        score_text = "🔴 تکنیکال: نزولی قوی"
    elif score <= -2:
        score_text = "🔴 تکنیکال: نزولی"
    else:
        score_text = "🟡 تکنیکال: خنثی"
    lines.append(f"• امتیاز تکنیکال: {score}/10")

    return "\n".join(lines)


# ==================================================================
# بخش ۵: سیستم امتیاز ترکیبی (فاندامنتال + تکنیکال)
# ==================================================================

def combined_score(bull_fa, bear_fa, tech_score, calendar_events=None, correlations=None):
    """
    ترکیب فاندامنتال (۴۰٪) + تکنیکال (۳۵٪) + تقویم (۱۵٪) + همبستگی (۱۰٪)
    خروجی: score از -100 تا +100, direction, confidence
    """
    score = 0

    # --- ۱. فاندامنتال (۴۰٪) ---
    fa_diff = bull_fa - bear_fa
    score += fa_diff * 4 * 0.40 / 1  # وزن ۴۰٪

    # --- ۲. تکنیکال (۳۵٪) ---
    score += tech_score * 10 * 0.35 / 1  # tech_score از -10 تا 10

    # --- ۳. تقویم اقتصادی (۱۵٪) ---
    high_events = 0
    if calendar_events:
        high_events = sum(1 for ev in calendar_events
                          if (ev.get("impact") or "").lower() == "high"
                          and ev.get("_is_today"))
    if high_events >= 2:
        score *= 0.5  # نزدیک خبر مهم = کاهش اطمینان
    elif high_events == 1:
        score *= 0.75

    # --- ۴. همبستگی (۱۰٪) ---
    if correlations:
        # GBP/USD و AUD/USD همجهت با EUR/USD
        gbp = correlations.get("GBP/USD", 0)
        aud = correlations.get("AUD/USD", 0)
        # USD/JPY و USD/CHF برعکس
        jpy = correlations.get("USD/JPY", 0)
        chf = correlations.get("USD/CHF", 0)
        corr_signal = (gbp + aud - jpy - chf) * 3
        score += corr_signal * 0.10 / 1

    # --- تصمیم نهایی ---
    score = max(-100, min(100, round(score)))

    if score >= 20:
        direction, confidence = "صعودی", "بالا"
    elif score >= 8:
        direction, confidence = "صعودی", "متوسط"
    elif score <= -20:
        direction, confidence = "نزولی", "بالا"
    elif score <= -8:
        direction, confidence = "نزولی", "متوسط"
    else:
        direction, confidence = "خنثی", "پایین"

    return score, direction, confidence


def build_combined_view(score, direction, confidence, bull_fa, bear_fa, tech_score):
    """نمایش سیستم امتیاز ترکیبی"""
    emoji = "🟢" if score > 0 else ("🔴" if score < 0 else "🟡")

    # نوار امتیاز تصویری
    bar_length = 20
    if score != 0:
        filled = int(abs(score) / 100 * bar_length)
        if score > 0:
            bar = "⠀" * (bar_length - filled) + "🟩" * filled + "⬆️"
        else:
            bar = "🟥" * filled + "⬇️" + "⠀" * (bar_length - filled)
    else:
        bar = "⠀" * 10 + "➡️" + "⠀" * 10

    lines = [
        f"🎯 سیستم امتیاز ترکیبی: {emoji} {score}/100",
        f"{bar}",
        f"• فاندامنتال: صعودی {bull_fa} / نزولی {bear_fa}",
        f"• تکنیکال: {tech_score}/10",
        f"• جهت نهایی: {direction}",
        f"• اطمینان: {confidence}",
    ]
    return "\n".join(lines)


# ==================================================================
# بخش ۶: یادگیری از خطا
# ==================================================================
def save_prediction(direction, bull, bear, slot, has_news=False, tech_score=0, combined=0):
    now_teh = datetime.now(TEHRAN_TZ)
    price = get_eurusd_price()
    if not price:
        print("Cannot save prediction: no price")
        return
    predictions = load_json_file(PREDICTIONS_FILE, {})
    pred_id = f"{now_teh.strftime('%Y%m%d_%H%M')}_{slot}"
    predictions[pred_id] = {
        "timestamp": now_teh.isoformat(),
        "date": now_teh.strftime("%Y-%m-%d"),
        "time": now_teh.strftime("%H:%M"),
        "slot": slot,
        "direction": direction,
        "bull_score": int(bull),
        "bear_score": int(bear),
        "tech_score": tech_score,
        "combined_score": combined,
        "price_at_prediction": price,
        "has_news": has_news,
        "verified": False,
        "result": None,
        "price_change_pips": None,
        "checked_at": None,
    }
    if len(predictions) > 100:
        for k in sorted(predictions.keys())[:len(predictions) - 100]:
            del predictions[k]
    save_json_file(PREDICTIONS_FILE, predictions)
    print(f"Prediction saved: {pred_id} - {direction} @ {price}")


def verify_predictions():
    predictions = load_json_file(PREDICTIONS_FILE, {})
    if not predictions:
        return {"total": 0, "correct": 0, "wrong": 0, "neutral": 0}

    current_price = get_eurusd_price()
    if not current_price:
        print("Cannot verify: no current price")
        return None
    now_teh = datetime.now(TEHRAN_TZ)
    changes_made = False

    atr = get_eurusd_atr(14)

    for pred_id, pred in predictions.items():
        if pred.get("verified"):
            continue
        try:
            pred_time = datetime.fromisoformat(pred["timestamp"])
            hours_passed = (now_teh - pred_time).total_seconds() / 3600
            if hours_passed < 24:
                continue
            old_price = pred.get("price_at_prediction", 0)
            if not old_price:
                continue
            change_pips = round((current_price - old_price) * 10000, 1)
            direction = pred.get("direction", "خنثی")

            if atr:
                THRESHOLD = round(atr * 0.35, 1)
                THRESHOLD = max(25, min(THRESHOLD, 100))
            else:
                THRESHOLD = 30

            if abs(change_pips) < THRESHOLD:
                result = "neutral"
            elif direction == "صعودی" and change_pips > 0:
                result = "correct"
            elif direction == "نزولی" and change_pips < 0:
                result = "correct"
            elif direction == "خنثی" and abs(change_pips) < THRESHOLD:
                result = "correct"
            else:
                result = "wrong"

            pred["threshold_used"] = THRESHOLD
            pred["atr_at_check"] = atr
            pred["verified"] = True
            pred["result"] = result
            pred["price_change_pips"] = change_pips
            pred["price_at_check"] = current_price
            pred["checked_at"] = now_teh.isoformat()
            changes_made = True
            print(f"Verified {pred_id}: {direction} → {change_pips} pips → {result}")
        except Exception as ex:
            print(f"Verify error for {pred_id}:", ex)

    if changes_made:
        save_json_file(PREDICTIONS_FILE, predictions)
    return calculate_performance(predictions)


def calculate_performance(predictions=None):
    if predictions is None:
        predictions = load_json_file(PREDICTIONS_FILE, {})
    verified = [p for p in predictions.values() if p.get("verified")]
    if not verified:
        return {"total": 0, "correct": 0, "wrong": 0, "neutral": 0, "accuracy": 0}
    correct = sum(1 for p in verified if p["result"] == "correct")
    wrong = sum(1 for p in verified if p["result"] == "wrong")
    neutral = sum(1 for p in verified if p["result"] == "neutral")
    total = len(verified)
    accuracy = round((correct / total) * 100, 1) if total > 0 else 0

    bullish_correct = sum(1 for p in verified if p["direction"] == "صعودی" and p["result"] == "correct")
    bullish_total = sum(1 for p in verified if p["direction"] == "صعودی")
    bearish_correct = sum(1 for p in verified if p["direction"] == "نزولی" and p["result"] == "correct")
    bearish_total = sum(1 for p in verified if p["direction"] == "نزولی")

    return {
        "total": total, "correct": correct, "wrong": wrong, "neutral": neutral,
        "accuracy": accuracy,
        "bullish_accuracy": round((bullish_correct / bullish_total) * 100, 1) if bullish_total > 0 else 0,
        "bullish_total": bullish_total,
        "bearish_accuracy": round((bearish_correct / bearish_total) * 100, 1) if bearish_total > 0 else 0,
        "bearish_total": bearish_total,
    }


def build_performance_view(perf):
    if not perf or perf["total"] < 1:
        return "🎯 عملکرد ربات:\nهنوز داده کافی برای دقت نیست."
    accuracy = perf["accuracy"]
    if accuracy >= 70:
        emoji, rating = "🟢", "عالی"
    elif accuracy >= 55:
        emoji, rating = "🟡", "خوب"
    elif accuracy >= 45:
        emoji, rating = "🟠", "متوسط"
    else:
        emoji, rating = "🔴", "نیاز به بهبود"
    lines = [
        f"🎯 عملکرد ربات ({perf['total']} پیش‌بینی):",
        f"{emoji} دقت کلی: {accuracy}% ({rating})",
        f"✅ درست: {perf['correct']} | ❌ اشتباه: {perf['wrong']} | ⚪ خنثی: {perf['neutral']}",
    ]
    if perf.get("bullish_total", 0) > 0:
        lines.append(f"🟢 دقت صعودی: {perf['bullish_accuracy']}% ({perf['bullish_total']})")
    if perf.get("bearish_total", 0) > 0:
        lines.append(f"🔴 دقت نزولی: {perf['bearish_accuracy']}% ({perf['bearish_total']})")
    return "\n".join(lines)


def adjust_confidence_by_performance(base_confidence, perf):
    if not perf or perf["total"] < 10:
        return base_confidence
    accuracy = perf["accuracy"]
    if accuracy >= 70:
        return "بالا"
    elif accuracy >= 55:
        return base_confidence
    elif accuracy >= 40:
        return "پایین"
    else:
        return "خیلی پایین"


# ==================================================================
# بخش ۷: MARKET INDICATORS + CORRELATION + VOLATILITY
# ==================================================================
def fetch_market_indicators():
    indicators = {"DXY": None, "US10Y": None, "GOLD": None, "OIL": None, "SP500": None}
    tickers = {"DXY": "DX-Y.NYB", "US10Y": "^TNX",
               "GOLD": "GC=F", "OIL": "CL=F", "SP500": "^GSPC"}
    for name, ticker in tickers.items():
        try:
            url = f"https://query1.finance.yahoo.com/v8/finance/chart/{ticker}"
            r = requests.get(url, headers=HEADERS, timeout=8)
            if r.status_code == 200:
                data = r.json()
                result = data.get("chart", {}).get("result", [])
                if result:
                    meta = result[0].get("meta", {})
                    price = meta.get("regularMarketPrice")
                    prev = meta.get("chartPreviousClose")
                    if price and prev:
                        indicators[name] = {
                            "price": round(price, 2),
                            "change_pct": round(((price - prev) / prev) * 100, 2),
                        }
        except Exception:
            pass
    return indicators


def build_indicators_view(indicators):
    if not any(indicators.values()):
        return "💹 شاخص‌های بازار: داده در دسترس نیست."
    lines = ["💹 شاخص‌های کلیدی بازار:"]
    names_fa = {"DXY": "شاخص دلار (DXY)", "US10Y": "بازده اوراق 10 ساله",
                "GOLD": "طلا", "OIL": "نفت", "SP500": "S&P 500"}
    for key, label in names_fa.items():
        data = indicators.get(key)
        if data:
            arrow = "🟢" if data["change_pct"] >= 0 else "🔴"
            sign = "+" if data["change_pct"] >= 0 else ""
            lines.append(f"{arrow} {label}: {data['price']} ({sign}{data['change_pct']}%)")
    atr = get_eurusd_atr(14)
    if atr:
        lines.append(f"📏 ATR روزانه: {atr} pips")
        if atr > 80:
            lines.append("⚠️ نوسان بالا")
        elif atr < 40:
            lines.append("💤 نوسان کم")
    dxy = indicators.get("DXY")
    yields = indicators.get("US10Y")
    if dxy and yields:
        if dxy["change_pct"] > 0.3 and yields["change_pct"] > 0:
            lines.append("📊 تفسیر: قدرت دلار → فشار نزولی روی EUR/USD.")
        elif dxy["change_pct"] < -0.3 and yields["change_pct"] < 0:
            lines.append("📊 تفسیر: ضعف دلار → حمایت از EUR/USD.")
        else:
            lines.append("📊 تفسیر: شرایط مختلط.")
    return "\n".join(lines)


def fetch_correlation_pairs():
    pairs = {"GBP/USD": "GBPUSD=X", "USD/JPY": "USDJPY=X",
             "USD/CHF": "USDCHF=X", "AUD/USD": "AUDUSD=X"}
    results = {}
    for name, ticker in pairs.items():
        try:
            url = f"https://query1.finance.yahoo.com/v8/finance/chart/{ticker}"
            r = requests.get(url, headers=HEADERS, timeout=8)
            if r.status_code == 200:
                data = r.json()
                result = data.get("chart", {}).get("result", [])
                if result:
                    meta = result[0].get("meta", {})
                    price = meta.get("regularMarketPrice")
                    prev = meta.get("chartPreviousClose")
                    if price and prev:
                        results[name] = round(((price - prev) / prev) * 100, 2)
        except Exception:
            pass
    return results


def build_correlation_view(correlations):
    if not correlations:
        return "🔗 وضعیت جفت‌ارزها: داده در دسترس نیست."
    lines = ["🔗 وضعیت جفت‌ارزهای مرتبط:"]
    for pair, change in correlations.items():
        arrow = "🟢" if change >= 0 else "🔴"
        sign = "+" if change >= 0 else ""
        lines.append(f"{arrow} {pair}: {sign}{change}%")
    return "\n".join(lines)


def check_volatility_alert(indicators, correlations):
    alerts = []
    dxy = indicators.get("DXY") if indicators else None
    if dxy and abs(dxy["change_pct"]) > 0.5:
        d = "صعود" if dxy["change_pct"] > 0 else "نزول"
        alerts.append(f"⚠️ نوسان شدید DXY: {d} {abs(dxy['change_pct'])}%")
    yields = indicators.get("US10Y") if indicators else None
    if yields and abs(yields["change_pct"]) > 2:
        d = "صعود" if yields["change_pct"] > 0 else "نزول"
        alerts.append(f"⚠️ نوسان شدید بازده: {d} {abs(yields['change_pct'])}%")
    oil = indicators.get("OIL") if indicators else None
    if oil and abs(oil["change_pct"]) > 3:
        d = "صعود" if oil["change_pct"] > 0 else "نزول"
        alerts.append(f"🛢️ نوسان شدید نفت: {d} {abs(oil['change_pct'])}%")
    gold = indicators.get("GOLD") if indicators else None
    if gold and abs(gold["change_pct"]) > 1.5:
        d = "صعود" if gold["change_pct"] > 0 else "نزول"
        alerts.append(f"🥇 نوسان شدید طلا: {d} {abs(gold['change_pct'])}%")
    for pair, change in (correlations or {}).items():
        if abs(change) > 0.7:
            d = "صعود" if change > 0 else "نزول"
            alerts.append(f"⚠️ نوسان شدید {pair}: {d} {abs(change)}%")
    if alerts:
        return "\n".join(["🚨 هشدار نوسان شدید:"] + alerts)
    return None


def fetch_cot_data():
    try:
        url = "https://www.myfxbook.com/community/outlook/EURUSD"
        r = requests.get(url, headers=HEADERS, timeout=10)
        if r.status_code == 200:
            text = r.text.lower()
            long_match = re.search(r"long[:\s]+(\d+)%", text)
            short_match = re.search(r"short[:\s]+(\d+)%", text)
            if long_match and short_match:
                return {"long_pct": int(long_match.group(1)),
                        "short_pct": int(short_match.group(1))}
    except Exception:
        pass
    return None


def build_cot_view(cot_data):
    if not cot_data:
        return "📊 احساسات بازار: داده در دسترس نیست."
    long_pct = cot_data.get("long_pct", 50)
    short_pct = cot_data.get("short_pct", 50)
    lines = ["📊 احساسات بازار:", f"🟢 خرید: {long_pct}% | 🔴 فروش: {short_pct}%"]
    if long_pct >= 70:
        lines.append("⚠️ اکثریت خریدارند → احتمال اصلاح نزولی.")
    elif short_pct >= 70:
        lines.append("⚠️ اکثریت فروشنده‌اند → احتمال اصلاح صعودی.")
    else:
        lines.append("📌 احساسات متعادل.")
    return "\n".join(lines)


# ==================================================================
# بخش ۸: CALENDAR
# ==================================================================
def fetch_calendar_full():
    try:
        r = requests.get("https://nfs.faireconomy.media/ff_calendar_thisweek.json",
                         headers=HEADERS, timeout=12)
        return r.json()
    except Exception:
        return []


def parse_event_datetime(event):
    raw_date = (event.get("date") or "").strip()
    if not raw_date:
        return None
    try:
        dt = datetime.fromisoformat(raw_date.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except Exception:
        return None


def event_time_tehran(event):
    dt = parse_event_datetime(event)
    if dt:
        return dt.astimezone(TEHRAN_TZ).strftime("%H:%M تهران")
    return event.get("time", "نامشخص")


def get_today_events():
    data = fetch_calendar_full()
    now_teh = datetime.now(TEHRAN_TZ)
    today_teh = now_teh.date()
    tomorrow_teh = (now_teh + timedelta(days=1)).date()
    out = []
    for ev in data:
        if ev.get("country") not in ["USD", "EUR", "EMU"]:
            continue
        if ev.get("impact") not in ("High", "Medium"):
            continue
        dt = parse_event_datetime(ev)
        if not dt:
            continue
        event_date_teh = dt.astimezone(TEHRAN_TZ).date()
        if event_date_teh == today_teh:
            ev["_is_today"] = True
            ev["_is_tomorrow"] = False
            out.append(ev)
        elif event_date_teh == tomorrow_teh:
            ev["_is_today"] = False
            ev["_is_tomorrow"] = True
            out.append(ev)
    return out


def get_week_events():
    data = fetch_calendar_full()
    return [ev for ev in data if ev.get("country") in ["USD", "EUR", "EMU"]
            and ev.get("impact") == "High"]


def impact_to_fa(impact):
    impact = (impact or "").strip().lower()
    if impact == "high": return "🔴 خیلی مهم"
    elif impact == "medium": return "🟠 متوسط"
    elif impact == "low": return "🟢 کم‌اهمیت"
    return "⚪ نامشخص"


def expected_event_impact(event):
    title = (event.get("title") or "").lower()
    country = (event.get("country") or "").upper()
    if country == "USD" and any(k in title for k in ["cpi", "inflation", "pce"]):
        return "تورم بالاتر → دلار قوی. پایین‌تر → دلار ضعیف."
    if country == "USD" and any(k in title for k in ["nfp", "payroll"]):
        return "اشتغال قوی → دلار قوی."
    if country == "USD" and any(k in title for k in ["jobless claims", "unemployment"]):
        return "بیکاری بالاتر → دلار ضعیف."
    if country == "USD" and any(k in title for k in ["fomc", "fed", "powell"]):
        return "هاوکیش → دلار قوی. داویش → دلار ضعیف."
    if country in ["EUR", "EMU"] and any(k in title for k in ["cpi", "inflation", "hicp"]):
        return "تورم بالاتر → یورو قوی."
    if country in ["EUR", "EMU"] and any(k in title for k in ["ecb", "lagarde"]):
        return "لحن هاوکیش ECB → یورو قوی."
    return "actual را با forecast مقایسه کنید."


def event_number(value):
    m = re.search(r"[-+]?\d+(?:\.\d+)?", str(value or "").replace(",", ""))
    return float(m.group()) if m else None


def released_event_impact(event):
    title = (event.get("title") or "").lower()
    country = (event.get("country") or "").upper()
    actual = event_number(event.get("actual"))
    forecast = event_number(event.get("forecast"))
    if actual is None or forecast is None:
        return "actual/forecast در دسترس نیست."
    if actual == forecast:
        return "actual مطابق forecast؛ اثر خنثی."
    higher = actual > forecast
    if country == "USD" and any(k in title for k in ["jobless claims", "unemployment"]):
        return "بیکاری بالاتر → EUR/USD صعودی." if higher else "بیکاری پایین‌تر → EUR/USD نزولی."
    if country == "USD":
        return "داده آمریکا قوی → EUR/USD نزولی." if higher else "داده آمریکا ضعیف → EUR/USD صعودی."
    if country in ["EUR", "EMU"]:
        return "داده اروپا بهتر → EUR/USD صعودی." if higher else "داده اروپا ضعیف → EUR/USD نزولی."
    return "اثر باید با واکنش بازار بررسی شود."


def check_upcoming_events(minutes_ahead=30):
    try:
        data = fetch_calendar_full()
        now_teh = datetime.now(TEHRAN_TZ)
        alerts = []
        seen = load_seen_events()
        for ev in data:
            if ev.get("country") not in ["USD", "EUR", "EMU"]:
                continue
            if ev.get("impact") != "High":
                continue
            dt = parse_event_datetime(ev)
            if not dt:
                continue
            event_teh = dt.astimezone(TEHRAN_TZ)
            time_diff = (event_teh - now_teh).total_seconds() / 60
            if 25 <= time_diff <= 35:
                uid = f"prealert_{ev.get('title')}_{ev.get('date')}"
                if uid in seen:
                    continue
                seen[uid] = {"date": now_teh.strftime("%Y-%m-%d"),
                             "title": ev.get("title", ""),
                             "sent_at": now_teh.strftime("%Y-%m-%d %H:%M")}
                alerts.append(ev)
        if alerts:
            save_seen_events(seen)
        return alerts
    except Exception as ex:
        print("check_upcoming_events error:", ex)
        return []


def build_prealert_message(events):
    now_teh = datetime.now(TEHRAN_TZ)
    parts = ["⏰ هشدار: خبر مهم در راه است!", "",
             f"🕒 زمان فعلی: {now_teh.strftime('%H:%M تهران')}", ""]
    for ev in events:
        parts.extend([
            "━━━━━━━━━━━━━━", f"🔴 {ev.get('title', '')}",
            f"🕒 زمان انتشار: {event_time_tehran(ev)}",
            f"🌍 ارز: {ev.get('country', '')}",
            f"📊 پیش‌بینی: {ev.get('forecast', 'N/A')}",
            f"📉 قبلی: {ev.get('previous', 'N/A')}", "",
            "💡 اثر احتمالی:", expected_event_impact(ev), "",
        ])
    parts.extend(["⚠️ توصیه‌ها:", "• پوزیشن‌های باز را چک کنید",
                  "• حجم معامله را کاهش دهید", "• استاپ‌لاس تنظیم کنید"])
    return "\n".join(parts)


def build_morning_calendar_alert(calendar_events):
    now_teh = datetime.now(TEHRAN_TZ)
    if HAS_JALALI:
        jd = jdatetime.datetime.fromgregorian(datetime=now_teh)
        date_fa = jd.strftime("%A %d %B %Y – %H:%M تهران")
    else:
        date_fa = now_teh.strftime("%Y-%m-%d %H:%M تهران")
    allowed = {x.strip().lower() for x in NEWS_IMPACT_LEVELS}
    events = [ev for ev in calendar_events
              if (ev.get("impact") or "").strip().lower() in allowed and ev.get("_is_today")]
    if not events:
        return "\n".join(["🌅 یادآور اقتصادی امروز", "", date_fa, "",
                          "امروز خبر مهمی نداریم."])
    events.sort(key=lambda ev: (parse_event_datetime(ev) or datetime.max.replace(tzinfo=TEHRAN_TZ)))
    lines = []
    for ev in events:
        block = ["━━━━━━━━━━━━━━", impact_to_fa(ev.get("impact", "")),
                 f"🕒 {event_time_tehran(ev)}", f"🌍 {ev.get('country', '')}",
                 f"📌 {ev.get('title', '')}"]
        if ev.get("forecast"):
            block.append(f"📊 پیش‌بینی: {ev.get('forecast')}")
        if ev.get("previous"):
            block.append(f"📉 قبلی: {ev.get('previous')}")
        block.extend(["", "اثر:", expected_event_impact(ev)])
        lines.append("\n".join(block))
    return "\n".join(["🌅 یادآور اقتصادی امروز", "", date_fa, "",
                      "خبرهای مهم امروز:", "", "\n\n".join(lines), "",
                      "⚠️ نزدیک خبرهای مهم، احتیاط کنید."])


# ==================================================================
# بخش ۹: NEWS FETCH
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
                out.append(text[:350])
    except Exception:
        pass
    return out


def fetch_news_all():
    blob = ["=== FXSTREET ==="]
    blob += fetch_rss(SOURCES["fxstreet_rss"], 15)
    blob.append("\n=== FOREXLIVE ===")
    blob += fetch_rss(SOURCES["forexlive"], 12)
    blob.append("\n=== ECB ===")
    blob += fetch_rss(SOURCES["ecb_press"], 8)
    blob.append("\n=== FED ===")
    blob += fetch_rss(SOURCES["fed_press"], 8)
    return "\n".join(blob)


def check_live_news():
    hits = []
    seen = load_seen_events()
    try:
        data = fetch_calendar_full()
        now_teh = datetime.now(TEHRAN_TZ)
        today = now_teh.strftime("%Y-%m-%d")
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
            seen[uid] = {"date": today, "title": ev.get("title", ""),
                         "actual": actual, "sent_at": now_teh.strftime("%Y-%m-%d %H:%M")}
            item = {"title": ev.get("title", ""), "country": ev.get("country", ""),
                    "actual": ev.get("actual", ""), "forecast": ev.get("forecast", ""),
                    "previous": ev.get("previous", ""), "time": ev.get("time", "")}
            item["instant_impact"] = released_event_impact(item)
            hits.append(item)
        save_seen_events(seen)
        return hits
    except Exception as ex:
        print("check_live_news error:", ex)
        return []


def check_breaking_headlines():
    try:
        urls = ["https://www.fxstreet.com/news/forex/feed",
                "https://www.forexlive.com/feed/"]
        seen = load_seen_events()
        hits = []
        today = datetime.now(TEHRAN_TZ).strftime("%Y-%m-%d")
        for u in urls:
            try:
                d = feedparser.parse(u)
                for e in d.entries[:5]:
                    title = clean_html_text(getattr(e, "title", ""))
                    if not is_relevant_news(title):
                        continue
                    uid = f"headline_{hashlib.md5(title.lower().encode()).hexdigest()}"
                    if uid in seen:
                        continue
                    seen[uid] = {"date": today, "title": title,
                                 "sent_at": datetime.now(TEHRAN_TZ).strftime("%Y-%m-%d %H:%M")}
                    hits.append(title)
                    if len(hits) >= 3:
                        break
            except Exception:
                pass
            if len(hits) >= 3:
                break
        save_seen_events(seen)
        return hits
    except Exception:
        return []


# ==================================================================
# بخش ۱۰: AI
# ==================================================================
def score_sentiment_ai(news_text):
    """تحلیل احساسات با Groq — fallback به کلمات کلیدی"""
    if not HAS_GROQ:
        return score_sentiment_keywords(news_text)
    try:
        response = groq_client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[
                {"role": "system", "content": (
                    "تو تحلیل‌گر احساسات بازار EUR/USD هستی. اخبار را می‌خوانی و فقط JSON برمی‌گردانی.\n\n"
                    "قوانین:\n"
                    "- 'not dovish' یا 'hawkish' یا 'rate hike' = bear\n"
                    "- 'dovish' یا 'rate cut' یا 'weak dollar' = bull\n"
                    "- 'unlikely' یا 'not' معنی را برعکس کن\n"
                    "- خبر خنثی = 0/0\n- bull و bear بین 0 تا 15\n\n"
                    'خروجی: {"bull": عدد, "bear": عدد, "reason": "یک جمله"}'
                )},
                {"role": "user", "content": f"این اخبار را تحلیل کن:\n{news_text[:3000]}"},
            ],
            temperature=0.2, max_tokens=200,
        )
        raw = response.choices[0].message.content.strip()
        start = raw.find("{")
        end = raw.rfind("}") + 1
        if start != -1 and end > start:
            data = json.loads(raw[start:end])
            bull = max(0, min(15, int(data.get("bull", 0))))
            bear = max(0, min(15, int(data.get("bear", 0))))
            reason = data.get("reason", "")
            print(f"[AI Sentiment] bull={bull} bear={bear} | {reason}")
            return bull, bear
    except Exception as ex:
        print("AI sentiment error:", ex)
    print("[AI Sentiment] Fallback to keywords")
    return score_sentiment_keywords(news_text)


def score_sentiment_keywords(text):
    lines = [x.strip().lower() for x in str(text or "").splitlines()
             if x.strip() and not x.strip().startswith("===")]
    bull = sum(sum(1 for k in BULLISH if k in line) for line in lines)
    bear = sum(sum(1 for k in BEARISH if k in line) for line in lines)
    return bull, bear


def ai_analyze(news_text, calendar_events, bull_score, bear_score,
               tech_signals=None, indicators=None, correlations=None, performance=None):
    if not HAS_GROQ:
        return None
    try:
        cal_summary = ""
        if calendar_events:
            for ev in calendar_events[:3]:
                cal_summary += f"- {ev.get('country','')}: {ev.get('title','')}\n"

        indicators_summary = ""
        if indicators:
            for k, v in indicators.items():
                if v:
                    indicators_summary += f"- {k}: {v['price']} ({v['change_pct']:+.2f}%)\n"

        tech_summary = ""
        if tech_signals:
            tech_summary = (
                f"- روند EMA: {tech_signals.get('trend','نامشخص')}\n"
                f"- RSI: {tech_signals.get('rsi','نامشخص')}\n"
                f"- MACD: {tech_signals.get('macd_status','نامشخص')}\n"
                f"- امتیاز تکنیکال: {tech_signals.get('tech_score',0)}/10\n"
            )

        perf_note = ""
        if performance and performance.get("total", 0) > 10:
            acc = performance["accuracy"]
            if acc < 50:
                perf_note = f"\nنکته: دقت اخیر ربات {acc}% است. با احتیاط بیشتر تحلیل کن."

        prompt = f"""تو تحلیل‌گر حرفه‌ای EUR/USD هستی. هم فاندامنتال هم تکنیکال.
قواعد: حداکثر ۱۵۰ کلمه، ۵ خط کوتاه، بدون قیمت دقیق.

اخبار:
{news_text[:1500]}

تقویم:
{cal_summary if cal_summary else "خبری نیست"}

شاخص‌های کلان:
{indicators_summary if indicators_summary else "N/A"}

تحلیل تکنیکال:
{tech_summary if tech_summary else "N/A"}

امتیاز فاندامنتال: صعودی={bull_score} | نزولی={bear_score}
{perf_note}

خروجی دقیقاً:
- جهت کلی:
- عامل اصلی فاندامنتال:
- تأیید تکنیکال:
- ریسک امروز:
- توصیه:"""

        response = groq_client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[{"role": "system", "content": "تو تحلیل‌گر حرفه‌ای فارکس هستی."},
                      {"role": "user", "content": prompt}],
            temperature=0.4, max_tokens=400,
        )
        return response.choices[0].message.content.strip()
    except Exception as ex:
        print("AI error:", ex)
        return None


# ==================================================================
# بخش ۱۱: BUILDERS
# ==================================================================
def build_morning_trade_signal(direction, combined, confidence, performance):
    """سیگنال صبحگاهی به‌عنوان اندیکاتور تأیید"""
    total = performance.get("total", 0) if performance else 0
    accuracy = performance.get("accuracy", 0) if performance else 0

    if total < 10:
        trust = "🟡 مرحله یادگیری"
        trust_detail = f"هنوز فقط {total} پیش‌بینی داریم. حداقل ۱۰ لازم است."
        tradeable = False
    elif accuracy < 50:
        trust = "🔴 دقت پایین"
        trust_detail = f"دقت {accuracy}%. به حرف ربات اعتماد نکن."
        tradeable = False
    elif accuracy < 55:
        trust = "🟡 احتیاط"
        trust_detail = f"دقت {accuracy}%. فقط مرجع."
        tradeable = False
    else:
        trust = f"🟢 قابل اتکا ({accuracy}%)"
        trust_detail = f"دقت {accuracy}% از {total} پیش‌بینی."
        tradeable = True

    if not tradeable:
        light = "🔴" if accuracy < 50 else "🟡"
        action = "⏳ صبر کن — ربات هنوز یاد می‌گیرد"
        advice = "• دقت ربات هنوز کافی نیست → به تحلیل خودت تکیه کن"
    elif direction == "خنثی" or abs(combined) < 15:
        light = "🟡"
        action = "⏳ سیگنال ضعیف — منتظر داده بهتر"
        advice = "• سیگنال کافی نیست → به تحلیل خودت تکیه کن"
    else:
        light = "🟢"
        action = f"✅ تأیید {'خرید در اصلاح' if direction == 'صعودی' else 'فروش در رشد'}"
        if direction == "صعودی":
            advice = ("• تحلیل شما هم صعودی؟ → با اطمینان وارد شو\n"
                      "• تحلیل شما نزولی؟ → وارد نشو (متناقض)\n"
                      "• تحقیق نکرده‌ای؟ → فقط این جهت را دنبال نکن")
        else:
            advice = ("• تحلیل شما هم نزولی؟ → با اطمینان وارد شو\n"
                      "• تحلیل شما صعودی؟ → وارد نشو (متناقض)\n"
                      "• تحقیق نکرده‌ای؟ → فقط این جهت را دنبال نکن")

    lines = [
        f"{light} سیگنال صبحگاهی EUR/USD",
        "━━━━━━━━━━━━━━",
        f"📐 جهت نهایی: {direction}",
        f"🎯 امتیاز ترکیبی: {combined}/100",
        f"🔒 اطمینان: {confidence}",
        "",
        f"🎯 اعتماد به ربات: {trust}",
        f"   {trust_detail}",
        "",
        "━━━━━━━━━━━━━━",
        f"📌 اقدام: {action}",
        "",
        "💡 نحوه استفاده:",
        advice,
        "",
        "⚠️ این یک اندیکاتور تأیید است، نه جایگزین تحلیل شخصی.",
    ]
    return "\n".join(lines)


def build_brief(news_text, bull_fa, bear_fa, tech_signals, combined, direction, confidence,
                calendar_events, slot_label="تحلیل",
                breaking_news=None, indicators=None, correlations=None, cot=None,
                volatility_alert=None, performance=None):
    now_utc = datetime.now(timezone.utc)
    teh = now_utc + timedelta(hours=3, minutes=30)

    if HAS_JALALI:
        jd = jdatetime.datetime.fromgregorian(datetime=teh)
        date_fa = jd.strftime("%A %d %B %Y - %H:%M تهران")
        date_short = jd.strftime("%d %B")
    else:
        date_fa = teh.strftime("%Y-%m-%d %H:%M تهران")
        date_short = teh.strftime("%d %b")

    tech_score = tech_signals.get("tech_score", 0) if tech_signals else 0

    # --- خبر فوری ---
    breaking_block = ""
    if breaking_news:
        bn = breaking_news[0] if isinstance(breaking_news, list) else breaking_news
        impact_text = bn.get("instant_impact") or released_event_impact(bn)
        breaking_block = "\n".join([
            "🚨 خبر فوری:",
            f"{bn.get('country', '')} - {bn.get('title', '')}",
            f"واقعی: {bn.get('actual', '')} | پیش‌بینی: {bn.get('forecast', '')}",
            f"اثر: {impact_text}", "",
        ])

    # --- نکات کلیدی خبر ---
    sentences = re.split(r"[\.\n]", news_text or "")
    keys = []
    seen_kw = set()
    all_kw = ["ecb", "fed", "lagarde", "powell", "cpi", "pce", "nfp",
              "payroll", "inflation", "dollar", "euro", "eur/usd", "yield", "dxy", "oil"]
    for s in sentences:
        s_clean = clean_html_text(s.strip())
        s_low = s_clean.lower()
        if any(k in s_low for k in all_kw) and 35 < len(s_clean) < 180:
            key = s_low[:120]
            if key not in seen_kw:
                seen_kw.add(key)
                keys.append(s_clean)
        if len(keys) >= 3:
            break
    if not keys:
        keys = ["خبر مستقیم مهم محدود است."]
    bullets = "\n".join([f"- {k}" for k in keys[:3]])

    # --- تقویم ---
    calendar_text = "خبر تقویمی مهمی نداریم."
    if calendar_events:
        today_events = [ev for ev in calendar_events if ev.get("_is_today")]
        tomorrow_events = [ev for ev in calendar_events if ev.get("_is_tomorrow")]
        cal_lines = []
        if today_events:
            cal_lines.append("📅 امروز:")
            for ev in today_events[:3]:
                cal_lines.append(f"  • {event_time_tehran(ev)} | {ev.get('country','')} | {ev.get('impact','')} | {ev.get('title','')}")
        if tomorrow_events:
            if today_events:
                cal_lines.append("")
            cal_lines.append("📅 فردا:")
            for ev in tomorrow_events[:3]:
                cal_lines.append(f"  • {event_time_tehran(ev)} | {ev.get('country','')} | {ev.get('impact','')} | {ev.get('title','')}")
        if cal_lines:
            calendar_text = "\n".join(cal_lines)

    # --- ساخت پیام ---
    emoji = "🟢" if direction == "صعودی" else ("🔴" if direction == "نزولی" else "🟡")

    msg_parts = [
        f"{emoji} تحلیل جامع EUR/USD - {slot_label}",
        date_fa, "",
    ]
    if volatility_alert:
        msg_parts.extend([volatility_alert, ""])
    if breaking_block:
        msg_parts.append(breaking_block)

    # --- سیستم امتیاز ترکیبی ---
    msg_parts.extend([
        build_combined_view(combined, direction, confidence, bull_fa, bear_fa, tech_score),
        "",
    ])

    # --- تکنیکال ---
    if tech_signals:
        msg_parts.extend([build_technical_view(tech_signals), ""])

    # --- شاخص‌های کلان ---
    if indicators:
        msg_parts.extend([build_indicators_view(indicators), ""])

    # --- همبستگی ---
    if correlations:
        msg_parts.extend([build_correlation_view(correlations), ""])

    # --- احساسات بازار ---
    if cot:
        msg_parts.extend([build_cot_view(cot), ""])

    # --- عملکرد ---
    if performance and performance.get("total", 0) >= 1:
        msg_parts.extend([build_performance_view(performance), ""])

    msg_parts.extend([
        "📰 نکات کلیدی:", bullets, "",
        "📅 تقویم اقتصادی:", calendar_text, "",
        f"@EURUSDFaBot | {date_short}",
    ])
    msg = "\n".join(msg_parts)

    # --- متن صوتی ---
    voice_parts = [
        f"تحلیل جامع یورو دلار، {date_short}.",
        f"جهت نهایی بازار {direction} است با امتیاز {combined} از ۱۰۰.",
        f"امتیاز تکنیکال {tech_score} از ۱۰.",
        "با مدیریت ریسک معامله کنید.",
    ]
    voice_text = "\n".join(voice_parts)
    return msg, voice_text, direction


# ==================================================================
# بخش ۱۲: TELEGRAM
# ==================================================================
def send_telegram_text(text):
    if TELEGRAM_TOKEN.startswith("PUT_"):
        print("=== DRY RUN ===")
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
            last_nl = chunk.rfind("\n")
            if last_nl > max_len // 2:
                chunk = chunk[:last_nl]
            chunks.append(chunk)
            text = text[len(chunk):].lstrip()
    all_ok = True
    for i, chunk in enumerate(chunks):
        try:
            r = requests.post(url, data={
                "chat_id": CHAT_ID, "text": chunk,
                "parse_mode": "Markdown", "disable_web_page_preview": True,
            }, timeout=20)
            if not r.ok:
                r2 = requests.post(url, data={
                    "chat_id": CHAT_ID, "text": chunk, "disable_web_page_preview": True,
                }, timeout=20)
                if not r2.ok:
                    all_ok = False
        except Exception as ex:
            print("Send error:", ex)
            all_ok = False
    return all_ok


def send_telegram_voice(text_fa):
    if not SEND_VOICE:
        return False
    text_fa = normalize_voice_text(text_fa)
    audio_path = None
    try:
        import edge_tts, asyncio, tempfile
        voice = os.getenv("VOICE_NAME", VOICE_NAME)

        async def _synth():
            communicate = edge_tts.Communicate(text_fa, voice, rate=VOICE_RATE, pitch=VOICE_PITCH)
            with tempfile.NamedTemporaryFile(delete=False, suffix=".mp3") as tf:
                out_path = tf.name
            await communicate.save(out_path)
            return out_path

        audio_path = asyncio.run(_synth())
        if TELEGRAM_TOKEN.startswith("PUT_"):
            return True
        url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendAudio"
        with open(audio_path, "rb") as f:
            r = requests.post(url, data={
                "chat_id": CHAT_ID, "title": "تحلیل یورو دلار",
                "performer": "EURUSDFaBot", "caption": "تحلیل صوتی",
            }, files={"audio": f}, timeout=30)
        return r.ok
    except Exception as ex:
        print("Voice error:", ex)
        return False
    finally:
        try:
            if audio_path and os.path.exists(audio_path):
                os.unlink(audio_path)
        except Exception:
            pass


# ==================================================================
# بخش ۱۳: بک‌تست تکنیکال روی ۲ سال داده تاریخی
# ==================================================================

def calc_tech_score_slice(closes, highs, lows, idx):
    """
    محاسبه امتیاز تکنیکال فقط با داده‌های قبل از idx.
    برای بک‌تست — هیچ look-ahead bias ندارد.
    """
    if idx < 50:
        return 0, {}

    closes_slice = closes[:idx + 1]
    highs_slice = highs[:idx + 1]
    lows_slice = lows[:idx + 1]

    if len(closes_slice) < 50:
        return 0, {}

    tech_score = 0
    info = {}

    # --- EMA ---
    ema20 = calc_ema(closes_slice, 20)
    ema50 = calc_ema(closes_slice, 50)
    if ema20 and ema50:
        if ema20 > ema50:
            tech_score += 2
            info["trend"] = "صعودی"
        else:
            tech_score -= 2
            info["trend"] = "نزولی"

    if len(closes_slice) >= 200:
        ema200 = calc_ema(closes_slice, 200)
        current = closes_slice[-1]
        if ema200 and current > ema200:
            tech_score += 1
        elif ema200 and current < ema200:
            tech_score -= 1

    # --- RSI ---
    rsi = calc_rsi(closes_slice, 14)
    if rsi:
        info["rsi"] = rsi
        if rsi >= 70:
            tech_score -= 2
        elif rsi <= 30:
            tech_score += 2
        elif rsi >= 55:
            tech_score += 1
        elif rsi <= 45:
            tech_score -= 1

    # --- MACD ---
    macd_line, signal_line, _ = calc_macd(closes_slice)
    if macd_line is not None and signal_line is not None:
        if macd_line > signal_line:
            tech_score += 2
            info["macd"] = "صعودی"
        else:
            tech_score -= 2
            info["macd"] = "نزولی"

    # --- Bollinger ---
    bb_upper, bb_middle, bb_lower = calc_bollinger(closes_slice, 20)
    if bb_upper and bb_lower:
        current = closes_slice[-1]
        if current >= bb_upper:
            tech_score -= 1
        elif current <= bb_lower:
            tech_score += 1

    tech_score = max(-10, min(10, tech_score))
    return tech_score, info


def run_backtest(period="2y"):
    """
    بک‌تست استراتژی تکنیکال روی داده تاریخی.
    برای هر روز: سیگنال می‌گیریم → فردا را پیش‌بینی می‌کنیم → مقایسه.
    """
    print(f"\n[BACKTEST] دانلود داده {period} EUR/USD...")

    try:
        url = "https://query1.finance.yahoo.com/v8/finance/chart/EURUSD=X"
        params = {"range": period, "interval": "1d"}
        r = requests.get(url, params=params, headers=HEADERS, timeout=15)
        if r.status_code != 200:
            return None
        data = r.json()
        result = data.get("chart", {}).get("result", [])
        if not result:
            return None

        timestamps = result[0].get("timestamp", [])
        quotes = result[0].get("indicators", {}).get("quote", [{}])[0]

        valid = [(t, h, l, c) for t, h, l, c in
                 zip(timestamps, quotes.get("high", []),
                     quotes.get("low", []), quotes.get("close", []))
                 if h is not None and l is not None and c is not None]

        if len(valid) < 60:
            print("[BACKTEST] داده کافی نیست")
            return None

        ts_list = [v[0] for v in valid]
        highs = [v[1] for v in valid]
        lows = [v[2] for v in valid]
        closes = [v[3] for v in valid]

        print(f"[BACKTEST] {len(closes)} روز داده دریافت شد")

    except Exception as ex:
        print(f"[BACKTEST] خطا در دانلود: {ex}")
        return None

    # --- اجرای بک‌تست ---
    results = []
    bull_total = bull_correct = 0
    bear_total = bear_correct = 0
    neutral_total = 0

    for i in range(50, len(closes) - 1):
        tech_score, info = calc_tech_score_slice(closes, highs, lows, i)

        if tech_score >= 3:
            predicted = "صعودی"
        elif tech_score <= -3:
            predicted = "نزولی"
        else:
            predicted = "خنثی"

        today_close = closes[i]
        tomorrow_close = closes[i + 1]
        change_pips = (tomorrow_close - today_close) * 10000
        threshold = 25.0

        if abs(change_pips) < threshold:
            actual = "خنثی"
        elif change_pips > 0:
            actual = "صعودی"
        else:
            actual = "نزولی"

        if predicted == "خنثی":
            correct = None
            neutral_total += 1
        elif predicted == actual:
            correct = True
        elif actual == "خنثی":
            correct = None
        else:
            correct = False

        if predicted == "صعودی":
            bull_total += 1
            if correct:
                bull_correct += 1
        elif predicted == "نزولی":
            bear_total += 1
            if correct:
                bear_correct += 1

        if correct is not None:
            results.append({
                "date": datetime.fromtimestamp(ts_list[i]).strftime("%Y-%m-%d"),
                "predicted": predicted,
                "actual": actual,
                "tech_score": tech_score,
                "change_pips": round(change_pips, 1),
                "correct": correct,
            })

    directional = [r for r in results]
    total_trades = len(directional)
    correct_trades = sum(1 for r in directional if r["correct"])

    accuracy = round((correct_trades / total_trades) * 100, 1) if total_trades > 0 else 0
    bull_acc = round((bull_correct / bull_total) * 100, 1) if bull_total > 0 else 0
    bear_acc = round((bear_correct / bear_total) * 100, 1) if bear_total > 0 else 0

    net_pips = 0
    for r in directional:
        if r["correct"]:
            net_pips += abs(r["change_pips"])
        else:
            net_pips -= abs(r["change_pips"])

    return {
        "total_days": len(closes),
        "total_signals": total_trades + neutral_total,
        "directional_signals": total_trades,
        "neutral_signals": neutral_total,
        "correct": correct_trades,
        "wrong": total_trades - correct_trades,
        "accuracy": accuracy,
        "bullish_accuracy": bull_acc,
        "bullish_total": bull_total,
        "bearish_accuracy": bear_acc,
        "bearish_total": bear_total,
        "net_pips": round(net_pips, 1),
        "period": period,
        "first_date": datetime.fromtimestamp(ts_list[50]).strftime("%Y-%m-%d"),
        "last_date": datetime.fromtimestamp(ts_list[-1]).strftime("%Y-%m-%d"),
    }


def build_backtest_report(result):
    """ساخت گزارش بک‌تست برای تلگرام"""
    if not result:
        return "📊 بک‌تست: داده در دسترس نیست."

    acc = result["accuracy"]
    if acc >= 60:
        emoji, rating = "🟢", "عالی"
    elif acc >= 52:
        emoji, rating = "🟡", "خوب"
    elif acc >= 48:
        emoji, rating = "🟠", "متوسط"
    else:
        emoji, rating = "🔴", "نیاز به بهبود"

    pips = result["net_pips"]
    pips_text = f"🟢 +{pips} pips" if pips > 0 else f"🔴 {pips} pips"

    lines = [
        "📊 گزارش بک‌تست تکنیکال EUR/USD",
        "━━━━━━━━━━━━━━",
        f"📅 دوره: {result['first_date']} تا {result['last_date']}",
        f"📈 کل روزهای تست: {result['total_days']}",
        f"🎯 کل سیگنال‌ها: {result['total_signals']} (جهت‌دار: {result['directional_signals']})",
        "",
        "━━━━━━━━━━━━━━",
        f"{emoji} دقت تکنیکال: {acc}% ({rating})",
        f"✅ درست: {result['correct']} | ❌ اشتباه: {result['wrong']}",
        "",
    ]

    if result["bullish_total"] > 0:
        lines.append(f"🟢 دقت صعودی: {result['bullish_accuracy']}% ({result['bullish_total']} سیگنال)")
    if result["bearish_total"] > 0:
        lines.append(f"🔴 دقت نزولی: {result['bearish_accuracy']}% ({result['bearish_total']} سیگنال)")

    lines.extend([
        "",
        "━━━━━━━━━━━━━━",
        f"💰 سود/زیان خالص فرضی: {pips_text}",
        "",
        "💡 نکته:",
        "• این بک‌تست فقط تکنیکال را تست می‌کند",
        "• دقت بالای ۵۲٪ در تکنیکال خوب است",
        "• در ربات واقعی فاندامنتال هم اضافه می‌شود",
        "",
        "⚠️ نتایج گذشته تضمین آینده نیست.",
        f"@EURUSDFaBot | بک‌تست",
    ])
    return "\n".join(lines)


# ==================================================================
# بخش ۱۴: RUN
# ==================================================================
def build_weekly_report():
    now_teh = datetime.now(TEHRAN_TZ)
    if HAS_JALALI:
        jd = jdatetime.datetime.fromgregorian(datetime=now_teh)
        date_fa = jd.strftime("%A %d %B %Y")
    else:
        date_fa = now_teh.strftime("%Y-%m-%d")

    news = fetch_news_all()
    week_events = get_week_events()
    indicators = fetch_market_indicators()
    correlations = fetch_correlation_pairs()
    cot = fetch_cot_data()
    tech = get_technical_signals()
    bull_fa, bear_fa = score_sentiment_ai(news)
    performance = verify_predictions()
    tech_score = tech.get("tech_score", 0) if tech else 0
    combined, direction, confidence = combined_score(bull_fa, bear_fa, tech_score, week_events, correlations)

    parts = ["📊 گزارش هفتگی EUR/USD", date_fa, "", "━━━━━━━━━━━━━━"]
    if performance and performance.get("total", 0) > 0:
        parts.extend([build_performance_view(performance), ""])
    if tech:
        parts.extend(["━━━━━━━━━━━━━━", build_technical_view(tech), ""])
    parts.extend(["━━━━━━━━━━━━━━", build_combined_view(combined, direction, confidence, bull_fa, bear_fa, tech_score), ""])
    if indicators:
        parts.extend(["━━━━━━━━━━━━━━", build_indicators_view(indicators), ""])
    if correlations:
        parts.extend(["━━━━━━━━━━━━━━", build_correlation_view(correlations), ""])
    if cot:
        parts.extend(["━━━━━━━━━━━━━━", build_cot_view(cot), ""])
    parts.extend(["━━━━━━━━━━━━━━", "📅 خبرهای مهم هفته آینده:"])
    if week_events:
        for ev in week_events[:10]:
            parts.append(f"• {event_time_tehran(ev)} | {ev.get('country', '')} | {ev.get('title', '')}")
    else:
        parts.append("خبر مهمی ثبت نشده.")
    parts.extend(["", "━━━━━━━━━━━━━━", "🤖 تحلیل AI:"])
    ai = ai_analyze(news, week_events, bull_fa, bear_fa, tech, indicators, correlations, performance)
    if ai:
        parts.append(ai)
    parts.extend(["", "💡 توصیه هفتگی:", "• برنامه معاملاتی بنویسید",
                  "• سطوح مهم را روی چارت بگذارید", "", f"@EURUSDFaBot | {date_fa}"])
    return "\n".join(parts)


def run_once(slot="manual"):
    now_teh = datetime.now(TEHRAN_TZ)

    if slot == "backtest":
        print("[backtest] شروع بک‌تست ۲ ساله...")
        result = run_backtest("2y")
        if result:
            report = build_backtest_report(result)
            print(report)
            send_telegram_text(report)
        else:
            send_telegram_text("❌ بک‌تست ناموفق بود. داده دریافت نشد.")
        return

    if slot == "verify":
        print("[verify] Checking predictions...")
        performance = verify_predictions()
        if performance:
            print(f"Performance: {performance}")
        return

    if slot == "weekly" or (slot == "evening" and now_teh.weekday() == 4):
        print("[weekly] Building weekly report...")
        try:
            report = build_weekly_report()
            send_telegram_text(report)
            if SEND_VOICE:
                send_telegram_voice("گزارش هفتگی یورو دلار آماده است.")
        except Exception as e:
            print(f"[weekly] Error: {e}")
        if slot == "weekly":
            return

    if slot == "watch":
        try:
            upcoming = check_upcoming_events(30)
            if upcoming:
                msg = build_prealert_message(upcoming)
                send_telegram_text(msg)
                if SEND_VOICE:
                    send_telegram_voice(f"هشدار: {len(upcoming)} خبر مهم در ۳۰ دقیقه آینده.")
        except Exception as e:
            print(f"[prealert] Error: {e}")

    if slot == "watch":
        print("[watch] Checking...")
        try:
            verify_predictions()
            hits = check_live_news()
            if not hits:
                headlines = check_breaking_headlines()
                if headlines:
                    hits = [{"title": h[:120], "country": "NEWS", "actual": "breaking",
                             "forecast": "-", "previous": "-", "time": "now",
                             "instant_impact": "تیتر فوری."} for h in headlines]
            if hits:
                news = fetch_news_all()
                breaking_text = "\n".join([
                    f"{h['country']} {h['title']} Actual {h['actual']} Forecast {h['forecast']}"
                    for h in hits])
                news = breaking_text + "\n" + news
                bull_fa, bear_fa = score_sentiment_ai(news)
                cal = get_today_events()
                indicators = fetch_market_indicators()
                correlations = fetch_correlation_pairs()
                tech = get_technical_signals()
                vol_alert = check_volatility_alert(indicators, correlations)
                performance = calculate_performance()
                tech_score = tech.get("tech_score", 0) if tech else 0
                combined, direction, confidence = combined_score(
                    bull_fa, bear_fa, tech_score, cal, correlations)
                text_msg, voice_text, direction = build_brief(
                    news, bull_fa, bear_fa, tech, combined, direction, confidence, cal,
                    slot_label="🔔 خبر فوری", breaking_news=hits,
                    indicators=indicators, correlations=correlations,
                    volatility_alert=vol_alert, performance=performance)
                send_telegram_text(text_msg)
                save_prediction(direction, bull_fa, bear_fa, slot, has_news=True,
                                tech_score=tech_score, combined=combined)
                if SEND_VOICE:
                    send_telegram_voice(voice_text)
            else:
                print("[watch] Silent exit.")
        except Exception as e:
            print(f"[watch] Error: {e}")
        return

    print(f"[{slot}] Fetching...")
    verify_predictions()

    news = fetch_news_all()
    cal = get_today_events()
    bull_fa, bear_fa = score_sentiment_ai(news)
    indicators = fetch_market_indicators()
    correlations = fetch_correlation_pairs()
    cot = fetch_cot_data()
    tech = get_technical_signals()
    vol_alert = check_volatility_alert(indicators, correlations)
    performance = calculate_performance()

    tech_score = tech.get("tech_score", 0) if tech else 0
    combined, direction, confidence = combined_score(
        bull_fa, bear_fa, tech_score, cal, correlations)

    slot_info = SCHEDULES.get(slot, SCHEDULES["manual"])
    slot_label = slot_info.get("label", slot)

    if slot == "morning":
        try:
            calendar_msg = build_morning_calendar_alert(cal)
            send_telegram_text(calendar_msg)
        except Exception as ex:
            print("Morning error:", ex)

    text_msg, voice_text, direction = build_brief(
        news, bull_fa, bear_fa, tech, combined, direction, confidence, cal,
        slot_label=slot_label, indicators=indicators, correlations=correlations,
        cot=cot, volatility_alert=vol_alert, performance=performance)

    ai_analysis = ai_analyze(news, cal, bull_fa, bear_fa, tech, indicators, correlations, performance)
    if ai_analysis:
        text_msg = "\n".join([text_msg, "", "🤖 تحلیل AI:", ai_analysis])

    send_telegram_text(text_msg)

    # --- سیگنال صبحگاهی فقط در slot morning ---
    if slot == "morning":
        try:
            signal_msg = build_morning_trade_signal(direction, combined, confidence, performance)
            send_telegram_text(signal_msg)
        except Exception as ex:
            print("Morning signal error:", ex)

    has_news = bool(cal)
    save_prediction(direction, bull_fa, bear_fa, slot, has_news=has_news,
                    tech_score=tech_score, combined=combined)

    if SEND_VOICE:
        send_telegram_voice(voice_text)


# ==================================================================
# بخش ۱۴: MAIN
# ==================================================================
if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="EUR/USD Complete Trading Assistant")
    parser.add_argument("--slot", choices=[
        "morning", "news_morning", "us_preopen",
        "evening", "manual", "watch", "weekly", "verify", "backtest",
    ], default="manual")
    args = parser.parse_args()
    run_once(args.slot if args.slot else "manual")
