#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
EUR/USD Fundamental Brief – Persian – Telegram
- تحلیل فاندامنتال EUR/USD به فارسی
- ارسال 4 نوبت روزانه + چک خبر فوری بدون تکرار
"""

import os
import re
import json
import time
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

TEHRAN_TZ = timezone(timedelta(hours=3, minutes=30))

SCHEDULES = {
    "morning": {"hour": 7, "minute": 30, "label": "🌅 صبح – تحلیل باز شدن اروپا"},
    "news_morning": {"hour": 7, "minute": 40, "label": "☕ صبح – آپدیت خبری"},
    "us_preopen": {"hour": 16, "minute": 0, "label": "🌆 قبل بازار آمریکا"},
    "evening": {"hour": 18, "minute": 0, "label": "🌙 عصر – جمع‌بندی روز"},
    "watch": {"hour": 0, "minute": 0, "label": "🔔 رصد اخبار فوری"},
    "manual": {"hour": 0, "minute": 0, "label": "🔧 اجرای دستی"},
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

BULLISH = [
    "dovish fed", "fed cut", "fed pause", "soft us cpi",
    "cooling inflation", "weak nfp", "weak payrolls",
    "higher jobless claims", "lower treasury yields",
    "ecb hawkish", "eurozone inflation beats",
    "dollar weak", "dxy down",
]

BEARISH = [
    "hawkish fed", "fed hike", "hot us cpi", "strong nfp",
    "strong payrolls", "lower jobless claims",
    "higher treasury yields", "ecb dovish",
    "eurozone inflation misses", "dollar strong", "dxy up",
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
    geo_terms = [
        "iran", "hormuz", "war", "oil", "geopolitical",
        "risk-off", "risk off"
    ]

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
        "High": "خیلی مهم", "Medium": "متوسط",
        "actual": "عدد واقعی", "forecast": "پیش بینی",
        "manual": "اجرای دستی", "watch": "خبر فوری",
    }
    for old, new in replacements.items():
        text = text.replace(old, new)

    for ch in ["/", "|", "-", "_", "•", "📌", "📅", "📰", "⚖️",
               "🤖", "🔔", "🌅", "☕", "🌆", "🌙", "🟢", "🟡", "🔴", "🚨"]:
        text = text.replace(ch, " ")

    text = text.replace("ي", "ی").replace("ك", "ک")
    text = re.sub(r"\s+", " ", text).strip()
    return text


# ---------- SEEN EVENTS ----------
def load_seen_events():
    try:
        if os.path.exists(SEEN_FILE):
            with open(SEEN_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                today = datetime.now(TEHRAN_TZ).strftime("%Y-%m-%d")
                return {
                    k: v for k, v in data.items()
                    if v.get("date", "").startswith(today)
                }
    except Exception as ex:
        print("load_seen_events error:", ex)
    return {}


def save_seen_events(seen):
    try:
        with open(SEEN_FILE, "w", encoding="utf-8") as f:
            json.dump(seen, f, ensure_ascii=False, indent=2)
    except Exception as ex:
        print("save_seen_events error:", ex)


# ---------- AI ----------
def ai_analyze(news_text, calendar_events, bull_score, bear_score):
    if not HAS_GROQ:
        return None
    try:
        cal_summary = ""
        if calendar_events:
            for ev in calendar_events[:3]:
                cal_summary += (
                    f"- {ev.get('country','')}: {ev.get('title','')} "
                    f"(پیش‌بینی: {ev.get('forecast','N/A')})\n"
                )

        prompt = f"""
تو تحلیل‌گر حرفه‌ای EUR/USD هستی.
فقط بر اساس خبرهای مرتبط با EUR/USD تحلیل کن.
اگر خبر مستقیم مهم کم بود، صریح بگو: «خبر مستقیم مهم برای EUR/USD محدود است».

قواعد:
- حداکثر 120 کلمه
- بدون تکرار متن اصلی
- فقط 4 خط کوتاه
- بدون قیمت

اخبار:
{news_text[:2200]}

تقویم:
{cal_summary if cal_summary else "رویداد مهمی ثبت نشده"}

امتیاز:
صعودی={bull_score} | نزولی={bear_score}

خروجی دقیقاً شامل این 4 بخش:
- جهت کلی:
- عامل اصلی:
- ریسک امروز:
- جمع‌بندی:
"""

        response = groq_client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[
                {"role": "system", "content": "تو تحلیل‌گر فاندامنتال فارکس هستی و کوتاه فارسی می‌نویسی."},
                {"role": "user", "content": prompt}
            ],
            temperature=0.4,
            max_tokens=300,
        )
        return response.choices[0].message.content.strip()
    except Exception as ex:
        print("AI error:", ex)
        return None


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
    blob = []
    blob.append("=== BLOOMBERG ===")
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
    today = now_teh.strftime("%Y-%m-%d")
    tomorrow = (now_teh + timedelta(days=1)).strftime("%Y-%m-%d")
    out = []
    for ev in data:
        if (ev.get("country") in ["USD", "EUR", "EMU"]
                and ev.get("impact") in ("High", "Medium")):
            d = ev.get("date", "")[:10]
            if d in [today, tomorrow]:
                out.append(ev)
    return out


# ---------- CALENDAR ----------
def impact_to_fa(impact):
    impact = (impact or "").strip().lower()
    if impact == "high":
        return "🔴 خیلی مهم"
    elif impact == "medium":
        return "🟠 متوسط مهم"
    elif impact == "low":
        return "🟢 کم‌اهمیت"
    return "⚪ نامشخص"


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
    return event.get("time", "زمان نامشخص")


def is_event_today_tehran(event):
    dt = parse_event_datetime(event)
    if not dt:
        return True
    return dt.astimezone(TEHRAN_TZ).date() == datetime.now(TEHRAN_TZ).date()


def expected_event_impact(event):
    title = (event.get("title") or "").lower()
    country = (event.get("country") or "").upper()

    if country == "USD" and any(k in title for k in ["cpi", "inflation", "pce"]):
        return "تورم بالاتر از پیش‌بینی → دلار قوی‌تر، EUR/USD نزولی. پایین‌تر → برعکس."
    if country == "USD" and any(k in title for k in ["nfp", "payroll", "employment change"]):
        return "اشتغال قوی → به نفع دلار. ضعیف → به ضرر دلار."
    if country == "USD" and any(k in title for k in ["jobless claims", "unemployment"]):
        return "بیکاری بالاتر → دلار ضعیف. پایین‌تر → دلار قوی‌تر."
    if country == "USD" and any(k in title for k in ["fomc", "fed", "powell", "rate decision"]):
        return "لحن هاوکیش Fed → دلار قوی. داویش → دلار ضعیف."
    if country in ["EUR", "EMU"] and any(k in title for k in ["cpi", "inflation", "hicp"]):
        return "تورم بالاتر → احتمال هاوکیش‌تر شدن ECB → یورو قوی."
    if country in ["EUR", "EMU"] and any(k in title for k in ["ecb", "lagarde", "rate decision"]):
        return "لحن هاوکیش ECB → یورو قوی. داویش → یورو ضعیف."
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
        return "خبر منتشر شد، actual/forecast در دسترس نیست."
    if actual == forecast:
        return "actual مطابق forecast؛ اثر خنثی."

    higher = actual > forecast

    if country == "USD" and any(k in title for k in ["jobless claims", "unemployment"]):
        return ("بیکاری بالاتر → دلار ضعیف → EUR/USD صعودی."
                if higher else "بیکاری پایین‌تر → دلار قوی → EUR/USD نزولی.")
    if country == "USD":
        return ("داده آمریکا قوی‌تر → دلار قوی → EUR/USD نزولی."
                if higher else "داده آمریکا ضعیف‌تر → دلار ضعیف → EUR/USD صعودی.")
    if country in ["EUR", "EMU"]:
        return ("داده اروپا بهتر → یورو قوی → EUR/USD صعودی."
                if higher else "داده اروپا ضعیف‌تر → یورو ضعیف → EUR/USD نزولی.")
    return "اثر خبر باید با واکنش بازار بررسی شود."


# ---------- MORNING ALERT ----------
def build_morning_calendar_alert(calendar_events):
    now_teh = datetime.now(TEHRAN_TZ)
    if HAS_JALALI:
        jd = jdatetime.datetime.fromgregorian(datetime=now_teh)
        date_fa = jd.strftime("%A %d %B %Y – %H:%M تهران")
    else:
        date_fa = now_teh.strftime("%Y-%m-%d %H:%M تهران")

    allowed_impacts = {x.strip().lower() for x in NEWS_IMPACT_LEVELS}
    events = [ev for ev in calendar_events
              if (ev.get("impact") or "").strip().lower() in allowed_impacts
              and is_event_today_tehran(ev)]

    if not events:
        return "\n".join([
            "🌅 یادآور اقتصادی امروز EUR/USD",
            "", date_fa, "",
            "امروز خبر High یا Medium مهمی برای EUR/USD نداریم.",
            "بازار می‌تواند به تیترهای ناگهانی Fed، ECB و ریسک جهانی واکنش دهد.",
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
        block.extend(["", "اثر احتمالی:", expected_event_impact(ev)])
        lines.append("\n".join(block))

    return "\n".join([
        "🌅 یادآور اقتصادی امروز EUR/USD",
        "", date_fa, "",
        "خبرهای مهم امروز:", "",
        "\n\n".join(lines), "",
        "⚠️ نزدیک زمان خبرهای مهم، احتیاط کنید.",
    ])


# ---------- LIVE NEWS (با ضدتکرار) ----------
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

            seen[uid] = {
                "date": today,
                "title": ev.get("title", ""),
                "actual": actual,
                "sent_at": now_teh.strftime("%Y-%m-%d %H:%M"),
            }

            item = {
                "title": ev.get("title", ""),
                "country": ev.get("country", ""),
                "actual": ev.get("actual", ""),
                "forecast": ev.get("forecast", ""),
                "previous": ev.get("previous", ""),
                "time": ev.get("time", ""),
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
                    if not is_relevant_news(title):
                        continue
                    uid = f"headline_{hash(title.lower())}"
                    if uid in seen:
                        continue
                    seen[uid] = {
                        "date": today,
                        "title": title,
                        "sent_at": datetime.now(TEHRAN_TZ).strftime("%Y-%m-%d %H:%M"),
                    }
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


# ---------- SCORING ----------
def score_sentiment(text):
    lines = [x.strip().lower() for x in str(text or "").splitlines()
             if x.strip() and not x.strip().startswith("===")]
    bull = 0
    bear = 0
    for line in lines:
        bull += sum(1 for k in BULLISH if k in line)
        bear += sum(1 for k in BEARISH if k in line)
    return bull, bear


# ---------- BUILDERS ----------
def build_timeframe_view(bull, bear, calendar_events=None, breaking_news=None):
    diff = int(bull) - int(bear)
    calendar_events = calendar_events or []
    high_events = [ev for ev in calendar_events if (ev.get("impact") or "").lower() == "high"]
    medium_events = [ev for ev in calendar_events if (ev.get("impact") or "").lower() == "medium"]

    if breaking_news:
        instant = "بازار در حال واکنش به خبر تازه است."
    elif diff >= 2:
        instant = "متمایل به صعود EUR/USD."
    elif diff <= -2:
        instant = "متمایل به نزول EUR/USD."
    else:
        instant = "خنثی؛ سیگنال قوی نیست."

    if high_events:
        today_view = "امروز خبرهای قرمز داریم؛ احتیاط کنید."
    elif medium_events:
        today_view = "خبرهای نارنجی جهت کوتاه‌مدت می‌دهند."
    else:
        today_view = "فشار خبری سنگین نیست."

    if diff >= 4:
        long_term = "ضعف دلار می‌تواند EUR/USD را حمایت کند."
    elif diff <= -4:
        long_term = "قدرت دلار روی EUR/USD فشار می‌گذارد."
    else:
        long_term = "دید بلندمدت خنثی."

    return "\n".join([
        "📌 جمع‌بندی چندزمانه:",
        f"• لحظه‌ای: {instant}",
        f"• امروز: {today_view}",
        f"• بلندمدت: {long_term}",
    ])


def build_currency_strength(bull, bear, calendar_events=None, breaking_news=None):
    def clamp(x):
        return max(0, min(10, int(x)))

    eur_score = clamp(bull)
    usd_score = clamp(bear)
    calendar_events = calendar_events or []

    high_count = sum(1 for ev in calendar_events if (ev.get("impact") or "").lower() == "high")
    medium_count = sum(1 for ev in calendar_events if (ev.get("impact") or "").lower() == "medium")

    risk_level = "بالا" if high_count >= 1 else ("متوسط" if medium_count >= 1 else "پایین")

    if breaking_news:
        bn = breaking_news[0] if isinstance(breaking_news, list) else breaking_news
        impact_text = str(bn.get("instant_impact", ""))
        if "صعودی" in impact_text:
            eur_score = min(10, eur_score + 2)
        elif "نزولی" in impact_text:
            usd_score = min(10, usd_score + 2)

    diff = eur_score - usd_score
    if diff >= 3:
        result = "برتری با یورو."
    elif diff <= -3:
        result = "برتری با دلار."
    elif diff > 0:
        result = "یورو کمی برتری دارد."
    elif diff < 0:
        result = "دلار کمی برتری دارد."
    else:
        result = "قدرت برابر."

    return "\n".join([
        "⚖️ قدرت نسبی ارزها:",
        f"• EUR: {eur_score}/10",
        f"• USD: {usd_score}/10",
        f"• ریسک تقویم: {risk_level}",
        f"• جمع‌بندی: {result}",
    ])


def build_brief(news_text, bull, bear, calendar_events, slot_label="تحلیل روزانه", breaking_news=None):
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
        direction, bias, emoji, conf = "صعودی", "خرید در اصلاح", "🟢", "متوسط"
    elif diff <= -2:
        direction, bias, emoji, conf = "نزولی", "فروش در رشد", "🔴", "متوسط"
    else:
        direction, bias, emoji, conf = "خنثی", "انتظار داده مهم", "🟡", "پایین"

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
        if len(keys) >= 3:
            break

    if not keys:
        keys = ["خبر مستقیم مهم برای EUR/USD محدود است.",
                "جهت بازار به دلار و بانک‌های مرکزی وابسته است."]

    bullets = "\n".join([f"- {k}" for k in keys[:3]])

    if calendar_events:
        cal_lines = []
        for ev in calendar_events[:3]:
            cal_lines.append(f"- {event_time_tehran(ev)} | {ev.get('country','')} | {ev.get('impact','')} | {ev.get('title','')}")
        calendar_text = "\n".join(cal_lines)
    else:
        calendar_text = "خبر تقویمی مهمی نداریم."

    try:
        timeframe_view = build_timeframe_view(bull, bear, calendar_events, breaking_news)
    except Exception:
        timeframe_view = "جمع‌بندی چندزمانه در دسترس نیست."

    try:
        currency_strength = build_currency_strength(bull, bear, calendar_events, breaking_news)
    except Exception:
        currency_strength = "قدرت نسبی در دسترس نیست."

    bull_show = min(int(bull), 10)
    bear_show = min(int(bear), 10)

    msg_parts = [
        f"{emoji} تحلیل فاندامنتال EUR/USD - {slot_label}",
        date_fa, "",
    ]
    if breaking_block:
        msg_parts.append(breaking_block)

    msg_parts.extend([
        f"جهت: {direction}",
        f"تمایل: {bias}",
        f"اطمینان: {conf}", "",
        timeframe_view, "",
        currency_strength, "",
        "📰 نکات کلیدی:", bullets, "",
        "📅 تقویم اقتصادی:", calendar_text, "",
        f"جمع‌بندی: تمایل فعلی {direction} است.", "",
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
    return msg, voice_text


# ---------- TELEGRAM ----------
def send_telegram_text(text):
    if TELEGRAM_TOKEN.startswith("PUT_"):
        print("=== DRY RUN TEXT ===")
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
                all_ok = False
                r2 = requests.post(url, data={
                    "chat_id": CHAT_ID, "text": chunk,
                    "disable_web_page_preview": True,
                }, timeout=20)
                if r2.ok:
                    all_ok = True
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
        import edge_tts
        import asyncio
        import tempfile

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
            print(f"[VOICE DRY RUN] {audio_path}")
            return True

        url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendAudio"
        with open(audio_path, "rb") as f:
            r = requests.post(url, data={
                "chat_id": CHAT_ID,
                "title": "تحلیل یورو دلار",
                "performer": "EURUSDFaBot",
                "caption": "تحلیل صوتی فارسی",
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
        except Exception:
            pass


# ---------- RUN ----------
def run_once(slot="manual"):
    if slot == "watch":
        print("[watch] Checking for new events...")
        try:
            hits = check_live_news()
            if not hits:
                headlines = check_breaking_headlines()
                if headlines:
                    hits = [{
                        "title": h[:120], "country": "NEWS",
                        "actual": "breaking", "forecast": "-",
                        "previous": "-", "time": "now",
                        "instant_impact": "تیتر فوری دریافت شد.",
                    } for h in headlines]

            if hits:
                print(f"[watch] {len(hits)} new event(s).")
                news = fetch_news_all()
                breaking_text = "\n".join([
                    f"{h['country']} {h['title']} Actual {h['actual']} Forecast {h['forecast']}"
                    for h in hits
                ])
                news = breaking_text + "\n" + news
                bull, bear = score_sentiment(news)
                cal = get_today_events()
                text_msg, voice_text = build_brief(
                    news, bull, bear, cal,
                    slot_label="🔔 خبر فوری",
                    breaking_news=hits,
                )
                send_telegram_text(text_msg)
                if SEND_VOICE:
                    send_telegram_voice(voice_text)
            else:
                print("[watch] Silent exit.")
        except Exception as e:
            print(f"[watch] Error: {e}")
        return

    print(f"[{slot}] Fetching news...")
    news = fetch_news_all()
    cal = get_today_events()
    bull, bear = score_sentiment(news)

    slot_info = SCHEDULES.get(slot, SCHEDULES["manual"])
    slot_label = slot_info.get("label", slot)

    if slot == "morning":
        try:
            calendar_msg = build_morning_calendar_alert(cal)
            send_telegram_text(calendar_msg)
        except Exception as ex:
            print("Morning alert error:", ex)

    text_msg, voice_text = build_brief(
        news_text=news, bull=bull, bear=bear,
        calendar_events=cal, slot_label=slot_label,
    )

    ai_analysis = ai_analyze(news, cal, bull, bear)
    if ai_analysis:
        text_msg = "\n".join([text_msg, "", "🤖 تحلیل AI:", ai_analysis])

    send_telegram_text(text_msg)
    if SEND_VOICE:
        send_telegram_voice(voice_text)


# ---------- MAIN ----------
if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="EUR/USD FA Bot")
    parser.add_argument("--slot", choices=[
        "morning", "news_morning", "us_preopen",
        "evening", "manual", "watch",
    ], default="manual")
    args = parser.parse_args()
    run_once(args.slot if args.slot else "manual")
