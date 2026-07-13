#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
EUR/USD Fundamental Brief – Persian – Telegram
نسخه اصلاح‌شده: sentiment با AI + آستانه ATR درست + باگ hash + ATR خارج حلقه

✅ تغییرات اعمال‌شده:
   1) score_sentiment_ai با Groq (fallback به کلمات کلیدی)
   2) آستانه پیش‌بینی: حداقل ۳۰٪ ATR (نه ۱۵ پیپ)
   3) باگ hash اصلاح شد (hashlib)
   4) ATR از حلقه بیرون آمد (یک بار محاسبه)
"""

import os
import re
import json
import time
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

# کلمات کلیدی (فقط به‌عنوان fallback اگر Groq نباشد)
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


# ---------- HELPERS ----------
def clean_html_text(text):
    try:
        return BeautifulSoup(str(text), "html.parser").get_text(" ", strip=True)
    except Exception:
        return str(text or "").strip()


def is_relevant_news(text):
    low = clean_html_text(text).lower()
    direct_terms = [
        "eur/usd", "eurusd", "euro", "usd", "dollar",
        "ecb", "fed", "fomc", "powell", "lagarde",
        "eurozone", "treasury yields", "dxy"
    ]
    macro_terms = [
        "inflation", "cpi", "pce", "nfp", "payroll",
        "employment", "unemployment", "jobless claims",
        "claims", "pmi", "gdp", "retail sales",
        "interest rate", "rate cut", "rate hike", "yield"
    ]
    region_terms = [
        "us", "u.s.", "united states", "america",
        "euro area", "eurozone", "europe", "germany", "france"
    ]
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
        "ATR": "میانگین نوسان",
        "COT": "گزارش کات", "High": "خیلی مهم",
        "Medium": "متوسط", "actual": "عدد واقعی",
        "forecast": "پیش بینی", "manual": "اجرای دستی",
        "watch": "خبر فوری",
    }
    for old, new in replacements.items():
        text = text.replace(old, new)
    for ch in ["/", "|", "-", "_", "•", "📌", "📅", "📰", "⚖️",
               "🤖", "🔔", "🌅", "☕", "🌆", "🌙", "🟢", "🟡", "🔴",
               "🚨", "📊", "⏰", "💹", "🌍", "🕒", "🎯", "✅", "❌", "⚪",
               "📏", "🛢️", "🥇"]:
        text = text.replace(ch, " ")
    text = text.replace("ي", "ی").replace("ك", "ک")
    text = re.sub(r"\s+", " ", text).strip()
    return text


# ---------- FILE MANAGEMENT ----------
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


# ---------- LEARNING FROM MISTAKES ----------
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
            prev_close = valid_data[i-1][2]
            tr = max(high - low, abs(high - prev_close), abs(low - prev_close))
            true_ranges.append(tr)
        recent_trs = true_ranges[-period:]
        atr = sum(recent_trs) / len(recent_trs)
        atr_pips = round(atr * 10000, 1)
        print(f"ATR ({period} days): {atr_pips} pips")
        return atr_pips
    except Exception as ex:
        print(f"get_eurusd_atr error: {ex}")
        return None


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


def save_prediction(direction, bull, bear, slot, has_news=False):
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
        "price_at_prediction": price,
        "has_news": has_news,
        "verified": False,
        "result": None,
        "price_change_pips": None,
        "checked_at": None,
    }
    if len(predictions) > 100:
        sorted_keys = sorted(predictions.keys())
        for k in sorted_keys[:len(predictions) - 100]:
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

    # ✅ اصلاح ۴: ATR یک بار خارج حلقه محاسبه می‌شود (نه برای هر پیش‌بینی)
    atr = get_eurusd_atr(14)
    if atr:
        print(f"Using ATR for all verifications: {atr} pips")

    for pred_id, pred in predictions.items():
        if pred.get("verified"):
            continue
        try:
            pred_time = datetime.fromisoformat(pred["timestamp"])
            hours_passed = (now_teh - pred_time).total_seconds() / 3600
            if hours_passed < 4 or hours_passed > 24:
                continue
            old_price = pred.get("price_at_prediction", 0)
            if not old_price:
                continue
            change_pips = round((current_price - old_price) * 10000, 1)
            direction = pred.get("direction", "خنثی")

            # ✅ اصلاح ۲: آستانه جدید — حداقل ۳۰٪ ATR (نه ۱۵ پیپ)
            if atr:
                base = atr * 0.30
                time_factor = 0.5 + 0.5 * min(hours_passed / 12, 1.0)
                THRESHOLD = round(base * time_factor, 1)
                THRESHOLD = max(20, min(THRESHOLD, 100))
                print(f"Dynamic threshold: {THRESHOLD} pips (ATR: {atr})")
            else:
                THRESHOLD = 30
                print(f"Default threshold: {THRESHOLD} pips")

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
    news_correct = sum(1 for p in verified if p.get("has_news") and p["result"] == "correct")
    news_total = sum(1 for p in verified if p.get("has_news"))

    return {
        "total": total, "correct": correct, "wrong": wrong, "neutral": neutral,
        "accuracy": accuracy,
        "bullish_accuracy": round((bullish_correct / bullish_total) * 100, 1) if bullish_total > 0 else 0,
        "bullish_total": bullish_total,
        "bearish_accuracy": round((bearish_correct / bearish_total) * 100, 1) if bearish_total > 0 else 0,
        "bearish_total": bearish_total,
        "news_accuracy": round((news_correct / news_total) * 100, 1) if news_total > 0 else 0,
        "news_total": news_total,
    }


def build_performance_view(perf):
    if not perf or perf["total"] < 1:
        return "🎯 عملکرد ربات:\nهنوز داده کافی برای دقت نیست."
    accuracy = perf["accuracy"]
    if accuracy >= 70:
        emoji = "🟢"
        rating = "عالی"
    elif accuracy >= 55:
        emoji = "🟡"
        rating = "خوب"
    elif accuracy >= 45:
        emoji = "🟠"
        rating = "متوسط"
    else:
        emoji = "🔴"
        rating = "نیاز به بهبود"
    lines = [
        f"🎯 عملکرد ربات ({perf['total']} پیش‌بینی):",
        f"{emoji} دقت کلی: {accuracy}% ({rating})",
        f"✅ درست: {perf['correct']} | ❌ اشتباه: {perf['wrong']} | ⚪ خنثی: {perf['neutral']}",
    ]
    if perf["bullish_total"] > 0:
        lines.append(f"🟢 دقت صعودی: {perf['bullish_accuracy']}% ({perf['bullish_total']} پیش‌بینی)")
    if perf["bearish_total"] > 0:
        lines.append(f"🔴 دقت نزولی: {perf['bearish_accuracy']}% ({perf['bearish_total']} پیش‌بینی)")
    if perf["news_total"] > 0:
        lines.append(f"📰 دقت در روزهای خبر: {perf['news_accuracy']}% ({perf['news_total']} پیش‌بینی)")
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


# ---------- MARKET INDICATORS ----------
def fetch_market_indicators():
    indicators = {"DXY": None, "US10Y": None, "GOLD": None, "OIL": None, "SP500": None}
    tickers = {
        "DXY": "DX-Y.NYB", "US10Y": "^TNX",
        "GOLD": "GC=F", "OIL": "CL=F", "SP500": "^GSPC",
    }
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
                        change_pct = ((price - prev) / prev) * 100
                        indicators[name] = {
                            "price": round(price, 2),
                            "change_pct": round(change_pct, 2),
                        }
        except Exception:
            pass
    return indicators


def build_indicators_view(indicators):
    if not any(indicators.values()):
        return "💹 شاخص‌های بازار: داده در دسترس نیست."
    lines = ["💹 شاخص‌های کلیدی بازار:"]
    names_fa = {
        "DXY": "شاخص دلار (DXY)",
        "US10Y": "بازده اوراق 10 ساله",
        "GOLD": "طلا",
        "OIL": "نفت",
        "SP500": "S&P 500",
    }
    for key, label in names_fa.items():
        data = indicators.get(key)
        if data:
            arrow = "🟢" if data["change_pct"] >= 0 else "🔴"
            sign = "+" if data["change_pct"] >= 0 else ""
            lines.append(f"{arrow} {label}: {data['price']} ({sign}{data['change_pct']}%)")

    atr = get_eurusd_atr(14)
    if atr:
        lines.append(f"📏 ATR روزانه EUR/USD: {atr} pips")
        if atr > 80:
            lines.append("⚠️ نوسان بالا - احتیاط بیشتر")
        elif atr < 40:
            lines.append("💤 نوسان کم - بازار آرام")

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


# ---------- COT / SENTIMENT ----------
def fetch_cot_data():
    try:
        url = "https://www.myfxbook.com/community/outlook/EURUSD"
        r = requests.get(url, headers=HEADERS, timeout=10)
        if r.status_code == 200:
            text = r.text.lower()
            long_match = re.search(r"long[:\s]+(\d+)%", text)
            short_match = re.search(r"short[:\s]+(\d+)%", text)
            if long_match and short_match:
                return {
                    "long_pct": int(long_match.group(1)),
                    "short_pct": int(short_match.group(1)),
                    "source": "MyFXBook",
                }
    except Exception:
        pass
    return None


def build_cot_view(cot_data):
    if not cot_data:
        return "📊 احساسات بازار: داده در دسترس نیست."
    long_pct = cot_data.get("long_pct", 50)
    short_pct = cot_data.get("short_pct", 50)
    lines = [
        "📊 احساسات بازار EUR/USD:",
        f"🟢 خرید: {long_pct}% | 🔴 فروش: {short_pct}%",
    ]
    if long_pct >= 70:
        lines.append("⚠️ اکثریت خریدارند → احتمال اصلاح نزولی.")
    elif short_pct >= 70:
        lines.append("⚠️ اکثریت فروشنده‌اند → احتمال اصلاح صعودی.")
    else:
        lines.append("📌 احساسات متعادل.")
    return "\n".join(lines)


# ---------- CORRELATION ----------
def fetch_correlation_pairs():
    pairs = {
        "GBP/USD": "GBPUSD=X", "USD/JPY": "USDJPY=X",
        "USD/CHF": "USDCHF=X", "AUD/USD": "AUDUSD=X",
    }
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
        return "🔗 همبستگی: داده در دسترس نیست."
    lines = ["🔗 وضعیت جفت‌ارزهای مرتبط:"]
    for pair, change in correlations.items():
        arrow = "🟢" if change >= 0 else "🔴"
        sign = "+" if change >= 0 else ""
        lines.append(f"{arrow} {pair}: {sign}{change}%")
    return "\n".join(lines)


# ---------- VOLATILITY ----------
def check_volatility_alert(indicators, correlations):
    alerts = []
    dxy = indicators.get("DXY") if indicators else None
    if dxy and abs(dxy["change_pct"]) > 0.5:
        direction = "صعود" if dxy["change_pct"] > 0 else "نزول"
        alerts.append(f"⚠️ نوسان شدید DXY: {direction} {abs(dxy['change_pct'])}%")

    yields = indicators.get("US10Y") if indicators else None
    if yields and abs(yields["change_pct"]) > 2:
        direction = "صعود" if yields["change_pct"] > 0 else "نزول"
        alerts.append(f"⚠️ نوسان شدید بازده: {direction} {abs(yields['change_pct'])}%")

    oil = indicators.get("OIL") if indicators else None
    if oil and abs(oil["change_pct"]) > 3:
        direction = "صعود" if oil["change_pct"] > 0 else "نزول"
        alerts.append(f"🛢️ نوسان شدید نفت: {direction} {abs(oil['change_pct'])}%")

    gold = indicators.get("GOLD") if indicators else None
    if gold and abs(gold["change_pct"]) > 1.5:
        direction = "صعود" if gold["change_pct"] > 0 else "نزول"
        alerts.append(f"🥇 نوسان شدید طلا: {direction} {abs(gold['change_pct'])}%")

    for pair, change in (correlations or {}).items():
        if abs(change) > 0.7:
            direction = "صعود" if change > 0 else "نزول"
            alerts.append(f"⚠️ نوسان شدید {pair}: {direction} {abs(change)}%")

    if alerts:
        return "\n".join(["🚨 هشدار نوسان شدید:"] + alerts)
    return None


# ---------- PRE-EVENT ALERT ----------
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
                seen[uid] = {
                    "date": now_teh.strftime("%Y-%m-%d"),
                    "title": ev.get("title", ""),
                    "sent_at": now_teh.strftime("%Y-%m-%d %H:%M"),
                }
                alerts.append(ev)
        if alerts:
            save_seen_events(seen)
        return alerts
    except Exception as ex:
        print("check_upcoming_events error:", ex)
        return []


def build_prealert_message(events):
    now_teh = datetime.now(TEHRAN_TZ)
    parts = [
        "⏰ هشدار: خبر مهم در راه است!",
        "",
        f"🕒 زمان فعلی: {now_teh.strftime('%H:%M تهران')}",
        "",
    ]
    for ev in events:
        parts.extend([
            "━━━━━━━━━━━━━━",
            f"🔴 {ev.get('title', '')}",
            f"🕒 زمان انتشار: {event_time_tehran(ev)}",
            f"🌍 ارز: {ev.get('country', '')}",
            f"📊 پیش‌بینی: {ev.get('forecast', 'N/A')}",
            f"📉 قبلی: {ev.get('previous', 'N/A')}",
            "",
            "💡 اثر احتمالی:",
            expected_event_impact(ev),
            "",
        ])
    parts.extend([
        "⚠️ توصیه‌ها:",
        "• پوزیشن‌های باز را چک کنید",
        "• حجم معامله را کاهش دهید",
        "• استاپ‌لاس تنظیم کنید",
    ])
    return "\n".join(parts)


# ---------- AI ----------
def ai_analyze(news_text, calendar_events, bull_score, bear_score,
               indicators=None, correlations=None, cot=None, performance=None):
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

        perf_note = ""
        if performance and performance.get("total", 0) > 10:
            acc = performance["accuracy"]
            if acc < 50:
                perf_note = f"\nنکته: دقت اخیر ربات {acc}% است. با احتیاط بیشتر تحلیل کن."

        prompt = f"""تو تحلیل‌گر حرفه‌ای EUR/USD هستی.
قواعد:
- حداکثر 150 کلمه
- 5 خط کوتاه
- بدون قیمت دقیق

اخبار:
{news_text[:1800]}

تقویم:
{cal_summary if cal_summary else "خبری نیست"}

شاخص‌ها:
{indicators_summary if indicators_summary else "N/A"}

امتیاز: صعودی={bull_score} | نزولی={bear_score}
{perf_note}

خروجی دقیقاً:
- جهت کلی:
- عامل اصلی:
- تأیید از شاخص‌ها:
- ریسک امروز:
- توصیه:
"""

        response = groq_client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[
                {"role": "system", "content": "تو تحلیل‌گر فاندامنتال حرفه‌ای فارکس هستی."},
                {"role": "user", "content": prompt}
            ],
            temperature=0.4,
            max_tokens=400,
        )
        return response.choices[0].message.content.strip()
    except Exception as ex:
        print("AI error:", ex)
        return None


# ==================================================================
# ✅ اصلاح ۱: SCORING — sentiment با هوش مصنوعی Groq
# ==================================================================

def score_sentiment_ai(news_text):
    """
    تحلیل احساسات واقعی با Groq — جایگزین کلمات کلیدی.
    مزایا: context را می‌فهمد، «not dovish» را اشتباه نمی‌گیرد.
    اگر Groq در دسترس نباشد، fallback به کلمات کلیدی برمی‌گردد.
    """
    if not HAS_GROQ:
        return score_sentiment_keywords(news_text)

    try:
        response = groq_client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[
                {
                    "role": "system",
                    "content": (
                        "تو تحلیل‌گر احساسات بازار EUR/USD هستی. "
                        "اخبار را می‌خوانی و فقط یک JSON برمی‌گردانی.\n\n"
                        "قوانین:\n"
                        "- 'not dovish' یا 'hawkish' یا 'rate hike' = نزول یورو = bear\n"
                        "- 'dovish' یا 'rate cut' یا 'weak dollar' = صعود یورو = bull\n"
                        "- 'unlikely' یا 'not' قبل از کلمه، معنی را برعکس کن\n"
                        "- خبر خنثی یا نامرتبط = 0/0\n"
                        "- bull و bear بین 0 تا 15\n\n"
                        "خروجی دقیقاً این فرمت:\n"
                        '{"bull": عدد, "bear": عدد, "reason": "یک جمله کوتاه"}'
                    ),
                },
                {
                    "role": "user",
                    "content": f"این اخبار را تحلیل کن:\n{news_text[:3000]}",
                },
            ],
            temperature=0.2,
            max_tokens=200,
        )

        raw = response.choices[0].message.content.strip()

        start = raw.find("{")
        end = raw.rfind("}") + 1
        if start != -1 and end > start:
            data = json.loads(raw[start:end])
            bull = int(data.get("bull", 0))
            bear = int(data.get("bear", 0))
            reason = data.get("reason", "")

            bull = max(0, min(15, bull))
            bear = max(0, min(15, bear))

            print(f"[AI Sentiment] bull={bull} bear={bear} | {reason}")
            return bull, bear

    except Exception as ex:
        print("AI sentiment error:", ex)

    print("[AI Sentiment] Fallback to keywords")
    return score_sentiment_keywords(news_text)


def score_sentiment_keywords(text):
    """روش قدیمی کلمات کلیدی — فقط fallback."""
    lines = [x.strip().lower() for x in str(text or "").splitlines()
             if x.strip() and not x.strip().startswith("===")]
    bull = 0
    bear = 0
    for line in lines:
        bull += sum(1 for k in BULLISH if k in line)
        bear += sum(1 for k in BEARISH if k in line)
    return bull, bear


# ---------- FETCH ----------
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


def fetch_bloomberg():
    texts = []
    for rss in SOURCES["bloomberg_rss"]:
        texts += fetch_rss(rss, 15)
    try:
        r = requests.get(SOURCES["bloomberg_web"], headers=HEADERS, timeout=12)
        if r.status_code == 200:
            soup = BeautifulSoup(r.text, "html.parser")
            for tag in soup.select("a, h3, h2")[:60]:
                t = clean_html_text(tag.get_text(strip=True))
                if 25 < len(t) < 220 and is_relevant_news(t):
                    texts.append(t)
    except Exception:
        pass
    seen = set()
    uniq = []
    for x in texts:
        key = x.strip().lower()
        if key not in seen:
            seen.add(key)
            uniq.append(x)
    return uniq[:30]


def fetch_news_all():
    blob = ["=== BLOOMBERG ==="]
    blob += fetch_bloomberg()
    blob.append("\n=== FXSTREET ===")
    blob += fetch_rss(SOURCES["fxstreet_rss"], 15)
    blob.append("\n=== FOREXLIVE ===")
    blob += fetch_rss(SOURCES["forexlive"], 12)
    blob.append("\n=== ECB ===")
    blob += fetch_rss(SOURCES["ecb_press"], 8)
    blob.append("\n=== FED ===")
    blob += fetch_rss(SOURCES["fed_press"], 8)
    return "\n".join(blob)


def fetch_calendar_full():
    try:
        r = requests.get(
            "https://nfs.faireconomy.media/ff_calendar_thisweek.json",
            headers=HEADERS, timeout=12,
        )
        return r.json()
    except Exception:
        return []


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
    out = []
    for ev in data:
        if (ev.get("country") in ["USD", "EUR", "EMU"]
                and ev.get("impact") == "High"):
            out.append(ev)
    return out


# ---------- CALENDAR HELPERS ----------
def impact_to_fa(impact):
    impact = (impact or "").strip().lower()
    if impact == "high": return "🔴 خیلی مهم"
    elif impact == "medium": return "🟠 متوسط مهم"
    elif impact == "low": return "🟢 کم‌اهمیت"
    return "⚪ نامشخص"


def parse_event_datetime(event):
    raw_date = (event.get("date") or "").strip()
    if not raw_date: return None
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
    return event.get("time", "زمان نامشخص")


def is_event_today_tehran(event):
    dt = parse_event_datetime(event)
    if not dt: return True
    return dt.astimezone(TEHRAN_TZ).date() == datetime.now(TEHRAN_TZ).date()


def expected_event_impact(event):
    title = (event.get("title") or "").lower()
    country = (event.get("country") or "").upper()
    if country == "USD" and any(k in title for k in ["cpi", "inflation", "pce"]):
        return "تورم بالاتر → دلار قوی. پایین‌تر → دلار ضعیف."
    if country == "USD" and any(k in title for k in ["nfp", "payroll"]):
        return "اشتغال قوی → دلار قوی. ضعیف → دلار ضعیف."
    if country == "USD" and any(k in title for k in ["jobless claims", "unemployment"]):
        return "بیکاری بالاتر → دلار ضعیف."
    if country == "USD" and any(k in title for k in ["fomc", "fed", "powell"]):
        return "هاوکیش → دلار قوی. داویش → دلار ضعیف."
    if country in ["EUR", "EMU"] and any(k in title for k in ["cpi", "inflation", "hicp"]):
        return "تورم بالاتر → ECB هاوکیش‌تر → یورو قوی."
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


# ---------- MORNING ALERT ----------
def build_morning_calendar_alert(calendar_events):
    now_teh = datetime.now(TEHRAN_TZ)
    if HAS_JALALI:
        jd = jdatetime.datetime.fromgregorian(datetime=now_teh)
        date_fa = jd.strftime("%A %d %B %Y – %H:%M تهران")
    else:
        date_fa = now_teh.strftime("%Y-%m-%d %H:%M تهران")

    allowed = {x.strip().lower() for x in NEWS_IMPACT_LEVELS}
    events = [ev for ev in calendar_events
              if (ev.get("impact") or "").strip().lower() in allowed
              and ev.get("_is_today")]

    if not events:
        return "\n".join([
            "🌅 یادآور اقتصادی امروز EUR/USD",
            "", date_fa, "",
            "امروز خبر High یا Medium مهمی نداریم.",
        ])

    events.sort(key=lambda ev: (parse_event_datetime(ev) or datetime.max.replace(tzinfo=TEHRAN_TZ)))
    lines = []
    for ev in events:
        block = [
            "━━━━━━━━━━━━━━",
            impact_to_fa(ev.get("impact", "")),
            f"🕒 {event_time_tehran(ev)}",
            f"🌍 {ev.get('country', '')}",
            f"📌 {ev.get('title', '')}",
        ]
        if ev.get("forecast"):
            block.append(f"📊 پیش‌بینی: {ev.get('forecast')}")
        if ev.get("previous"):
            block.append(f"📉 قبلی: {ev.get('previous')}")
        block.extend(["", "اثر:", expected_event_impact(ev)])
        lines.append("\n".join(block))

    return "\n".join([
        "🌅 یادآور اقتصادی امروز EUR/USD",
        "", date_fa, "",
        "خبرهای مهم امروز:", "",
        "\n\n".join(lines), "",
        "⚠️ نزدیک خبرهای مهم، احتیاط کنید.",
    ])


# ---------- WEEKLY REPORT ----------
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
    # ✅ اصلاح ۳: score_sentiment_ai به‌جای score_sentiment
    bull, bear = score_sentiment_ai(news)
    performance = verify_predictions()

    parts = [
        "📊 گزارش هفتگی EUR/USD",
        date_fa, "",
        "━━━━━━━━━━━━━━",
        "📰 جمع‌بندی هفته:",
        f"• امتیاز صعودی: {bull}",
        f"• امتیاز نزولی: {bear}",
        "",
    ]

    if performance and performance.get("total", 0) > 0:
        parts.extend(["━━━━━━━━━━━━━━", build_performance_view(performance), ""])

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
    ai = ai_analyze(news, week_events, bull, bear, indicators, correlations, cot, performance)
    if ai:
        parts.append(ai)

    parts.extend([
        "",
        "💡 توصیه هفتگی:",
        "• برنامه معاملاتی هفته را بنویسید",
        "• سطوح مهم را روی چارت بگذارید",
        "",
        f"@EURUSDFaBot | {date_fa}",
    ])
    return "\n".join(parts)


# ---------- LIVE NEWS ----------
def check_live_news():
    hits = []
    seen = load_seen_events()
    try:
        data = fetch_calendar_full()
        now_teh = datetime.now(TEHRAN_TZ)
        today = now_teh.strftime("%Y-%m-%d")
        for ev in data:
            if ev.get("country") not in ["USD", "EUR", "EMU"]: continue
            if ev.get("impact") not in ("High", "Medium"): continue
            if ev.get("date", "")[:10] != today: continue
            actual = (ev.get("actual") or "").strip()
            if not actual: continue
            uid = f"{ev.get('title')}_{ev.get('date')}_{ev.get('time')}"
            if uid in seen: continue
            seen[uid] = {
                "date": today, "title": ev.get("title", ""),
                "actual": actual,
                "sent_at": now_teh.strftime("%Y-%m-%d %H:%M"),
            }
            item = {
                "title": ev.get("title", ""), "country": ev.get("country", ""),
                "actual": ev.get("actual", ""), "forecast": ev.get("forecast", ""),
                "previous": ev.get("previous", ""), "time": ev.get("time", ""),
            }
            item["instant_impact"] = released_event_impact(item)
            hits.append(item)
        save_seen_events(seen)
        return hits
    except Exception as ex:
        print("check_live_news error:", ex)
        return []


def check_breaking_headlines():
    try:
        urls = [
            "https://www.fxstreet.com/news/forex/feed",
            "https://feeds.bloomberg.com/markets/news.rss",
            "https://www.forexlive.com/feed/",
        ]
        seen = load_seen_events()
        hits = []
        today = datetime.now(TEHRAN_TZ).strftime("%Y-%m-%d")
        for u in urls:
            try:
                d = feedparser.parse(u)
                for e in d.entries[:5]:
                    title = clean_html_text(getattr(e, "title", ""))
                    if not is_relevant_news(title): continue
                    # ✅ اصلاح ۳: باگ hash اصلاح شد
                    uid = f"headline_{hashlib.md5(title.lower().encode()).hexdigest()}"
                    if uid in seen: continue
                    seen[uid] = {
                        "date": today, "title": title,
                        "sent_at": datetime.now(TEHRAN_TZ).strftime("%Y-%m-%d %H:%M"),
                    }
                    hits.append(title)
                    if len(hits) >= 3: break
            except Exception: pass
            if len(hits) >= 3: break
        save_seen_events(seen)
        return hits
    except Exception:
        return []


# ---------- BUILDERS ----------
def build_timeframe_view(bull, bear, calendar_events=None, breaking_news=None):
    diff = int(bull) - int(bear)
    calendar_events = calendar_events or []
    today_events = [ev for ev in calendar_events if ev.get("_is_today")]
    high_events_today = [ev for ev in today_events if (ev.get("impact") or "").lower() == "high"]

    if breaking_news:
        instant = "بازار در حال واکنش به خبر تازه."
    elif diff >= 2:
        instant = "متمایل به صعود."
    elif diff <= -2:
        instant = "متمایل به نزول."
    else:
        instant = "خنثی."

    today_view = "خبرهای قرمز داریم." if high_events_today else "فشار خبری کم"

    if diff >= 4:
        long_term = "ضعف دلار → حمایت EUR/USD."
    elif diff <= -4:
        long_term = "قدرت دلار → فشار بر EUR/USD."
    else:
        long_term = "دید بلندمدت خنثی."

    return "\n".join([
        "📌 جمع‌بندی چندزمانه:",
        f"• لحظه‌ای: {instant}",
        f"• امروز: {today_view}",
        f"• بلندمدت: {long_term}",
    ])


def build_currency_strength(bull, bear, calendar_events=None, breaking_news=None):
    def clamp(x): return max(0, min(10, int(x)))
    eur_score = clamp(bull)
    usd_score = clamp(bear)
    calendar_events = calendar_events or []
    today_events = [ev for ev in calendar_events if ev.get("_is_today")]
    high_count = sum(1 for ev in today_events if (ev.get("impact") or "").lower() == "high")
    medium_count = sum(1 for ev in today_events if (ev.get("impact") or "").lower() == "medium")
    risk_level = "بالا" if high_count >= 1 else ("متوسط" if medium_count >= 1 else "پایین")
    if breaking_news:
        bn = breaking_news[0] if isinstance(breaking_news, list) else breaking_news
        impact_text = str(bn.get("instant_impact", ""))
        if "صعودی" in impact_text:
            eur_score = min(10, eur_score + 2)
        elif "نزولی" in impact_text:
            usd_score = min(10, usd_score + 2)
    diff = eur_score - usd_score
    if diff >= 3: result = "برتری با یورو."
    elif diff <= -3: result = "برتری با دلار."
    elif diff > 0: result = "یورو کمی برتری دارد."
    elif diff < 0: result = "دلار کمی برتری دارد."
    else: result = "قدرت برابر."
    return "\n".join([
        "⚖️ قدرت نسبی ارزها:",
        f"• EUR: {eur_score}/10",
        f"• USD: {usd_score}/10",
        f"• ریسک تقویم: {risk_level}",
        f"• جمع‌بندی: {result}",
    ])


def build_brief(news_text, bull, bear, calendar_events, slot_label="تحلیل",
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

    diff = int(bull) - int(bear)
    if diff >= 2:
        direction, bias, emoji, base_conf = "صعودی", "خرید در اصلاح", "🟢", "متوسط"
    elif diff <= -2:
        direction, bias, emoji, base_conf = "نزولی", "فروش در رشد", "🔴", "متوسط"
    else:
        direction, bias, emoji, base_conf = "خنثی", "انتظار داده مهم", "🟡", "پایین"

    conf = adjust_confidence_by_performance(base_conf, performance)

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

    sentences = re.split(r"[\.\n]", news_text or "")
    keys = []
    seen = set()
    all_kw = ["ecb", "fed", "lagarde", "powell", "cpi", "pce", "nfp",
              "payroll", "inflation", "dollar", "euro", "eur/usd", "yield", "dxy"]
    for s in sentences:
        s_clean = clean_html_text(s.strip())
        s_low = s_clean.lower()
        if any(k in s_low for k in all_kw) and 35 < len(s_clean) < 180:
            key = s_low[:120]
            if key not in seen:
                seen.add(key)
                keys.append(s_clean)
        if len(keys) >= 3: break

    if not keys:
        keys = ["خبر مستقیم مهم محدود است."]
    bullets = "\n".join([f"- {k}" for k in keys[:3]])

    calendar_text = "خبر تقویمی مهمی نداریم."
    if calendar_events:
        today_events = [ev for ev in calendar_events if ev.get("_is_today")]
        tomorrow_events = [ev for ev in calendar_events if ev.get("_is_tomorrow")]
        cal_lines = []
        if today_events:
            cal_lines.append("📅 امروز:")
            for ev in today_events[:3]:
                cal_lines.append(
                    f"  • {event_time_tehran(ev)} | {ev.get('country','')} | "
                    f"{ev.get('impact','')} | {ev.get('title','')}"
                )
        if tomorrow_events:
            if today_events:
                cal_lines.append("")
            cal_lines.append("📅 فردا:")
            for ev in tomorrow_events[:3]:
                cal_lines.append(
                    f"  • {event_time_tehran(ev)} | {ev.get('country','')} | "
                    f"{ev.get('impact','')} | {ev.get('title','')}"
                )
        if cal_lines:
            calendar_text = "\n".join(cal_lines)

    try:
        timeframe_view = build_timeframe_view(bull, bear, calendar_events, breaking_news)
    except Exception:
        timeframe_view = "-"
    try:
        currency_strength = build_currency_strength(bull, bear, calendar_events, breaking_news)
    except Exception:
        currency_strength = "-"

    bull_show = min(int(bull), 10)
    bear_show = min(int(bear), 10)

    msg_parts = [
        f"{emoji} تحلیل فاندامنتال EUR/USD - {slot_label}",
        date_fa, "",
    ]
    if volatility_alert:
        msg_parts.extend([volatility_alert, ""])
    if breaking_block:
        msg_parts.append(breaking_block)
    msg_parts.extend([
        f"جهت: {direction}",
        f"تمایل: {bias}",
        f"اطمینان: {conf}", "",
        timeframe_view, "",
        currency_strength, "",
    ])
    if indicators:
        msg_parts.extend([build_indicators_view(indicators), ""])
    if correlations:
        msg_parts.extend([build_correlation_view(correlations), ""])
    if cot:
        msg_parts.extend([build_cot_view(cot), ""])
    if performance and performance.get("total", 0) >= 1:
        msg_parts.extend([build_performance_view(performance), ""])
    msg_parts.extend([
        "📰 نکات کلیدی:", bullets, "",
        "📅 تقویم اقتصادی:", calendar_text, "",
        f"@EURUSDFaBot | {date_short}",
        f"امتیاز: صعودی {bull_show} / نزولی {bear_show}",
    ])
    msg = "\n".join(msg_parts)

    voice_parts = [
        f"تحلیل فاندامنتال یورو دلار، {date_short}.",
        f"جهت فعلی بازار {direction} است.",
        f"تمایل: {bias}.",
        "با مدیریت ریسک معامله کنید.",
    ]
    voice_text = "\n".join(voice_parts)
    return msg, voice_text, direction


# ---------- TELEGRAM ----------
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
                "parse_mode": "Markdown",
                "disable_web_page_preview": True,
            }, timeout=20)
            print(f"Telegram {i+1}/{len(chunks)}:", r.status_code)
            if not r.ok:
                r2 = requests.post(url, data={
                    "chat_id": CHAT_ID, "text": chunk,
                    "disable_web_page_preview": True,
                }, timeout=20)
                if not r2.ok: all_ok = False
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
            communicate = edge_tts.Communicate(
                text_fa, voice,
                rate=VOICE_RATE, pitch=VOICE_PITCH,
            )
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
                "chat_id": CHAT_ID,
                "title": "تحلیل یورو دلار",
                "performer": "EURUSDFaBot",
                "caption": "تحلیل صوتی",
            }, files={"audio": f}, timeout=30)
        print("Voice:", r.status_code)
        return r.ok
    except Exception as ex:
        print("Voice error:", ex)
        return False
    finally:
        try:
            if audio_path and os.path.exists(audio_path):
                os.unlink(audio_path)
        except Exception: pass


# ---------- RUN ----------
def run_once(slot="manual"):
    now_teh = datetime.now(TEHRAN_TZ)

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
                print(f"[prealert] {len(upcoming)} upcoming")
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
                    hits = [{
                        "title": h[:120], "country": "NEWS",
                        "actual": "breaking", "forecast": "-",
                        "previous": "-", "time": "now",
                        "instant_impact": "تیتر فوری.",
                    } for h in headlines]
            if hits:
                print(f"[watch] {len(hits)} new event(s).")
                news = fetch_news_all()
                breaking_text = "\n".join([
                    f"{h['country']} {h['title']} Actual {h['actual']} Forecast {h['forecast']}"
                    for h in hits
                ])
                news = breaking_text + "\n" + news
                # ✅ اصلاح ۳: score_sentiment_ai
                bull, bear = score_sentiment_ai(news)
                cal = get_today_events()
                indicators = fetch_market_indicators()
                correlations = fetch_correlation_pairs()
                vol_alert = check_volatility_alert(indicators, correlations)
                performance = calculate_performance()
                text_msg, voice_text, direction = build_brief(
                    news, bull, bear, cal,
                    slot_label="🔔 خبر فوری",
                    breaking_news=hits,
                    indicators=indicators,
                    correlations=correlations,
                    volatility_alert=vol_alert,
                    performance=performance,
                )
                send_telegram_text(text_msg)
                save_prediction(direction, bull, bear, slot, has_news=True)
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
    # ✅ اصلاح ۳: score_sentiment_ai به‌جای score_sentiment
    bull, bear = score_sentiment_ai(news)
    indicators = fetch_market_indicators()
    correlations = fetch_correlation_pairs()
    cot = fetch_cot_data()
    vol_alert = check_volatility_alert(indicators, correlations)
    performance = calculate_performance()

    slot_info = SCHEDULES.get(slot, SCHEDULES["manual"])
    slot_label = slot_info.get("label", slot)

    if slot == "morning":
        try:
            calendar_msg = build_morning_calendar_alert(cal)
            send_telegram_text(calendar_msg)
        except Exception as ex:
            print("Morning error:", ex)

    text_msg, voice_text, direction = build_brief(
        news_text=news, bull=bull, bear=bear,
        calendar_events=cal, slot_label=slot_label,
        indicators=indicators, correlations=correlations, cot=cot,
        volatility_alert=vol_alert, performance=performance,
    )

    ai_analysis = ai_analyze(news, cal, bull, bear, indicators, correlations, cot, performance)
    if ai_analysis:
        text_msg = "\n".join([text_msg, "", "🤖 تحلیل AI:", ai_analysis])

    send_telegram_text(text_msg)
    has_news = bool(cal)
    save_prediction(direction, bull, bear, slot, has_news=has_news)

    if SEND_VOICE:
        send_telegram_voice(voice_text)


# ---------- MAIN ----------
if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="EUR/USD FA Bot")
    parser.add_argument("--slot", choices=[
        "morning", "news_morning", "us_preopen",
        "evening", "manual", "watch", "weekly", "verify",
    ], default="manual")
    args = parser.parse_args()
    run_once(args.slot if args.slot else "manual")
