#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
EUR/USD Fundamental Brief – Persian – Telegram v3
- صدای زنانه
- ارسال 4 نوبت: 07:30 صبح – 07:40 خبر صبح – 16:00 یک ساعت قبل بازار آمریکا – 18:00 عصر
- واچر خبر زنده – بعد از انتشار هر داده High Impact بلافاصله تحلیل آپدیت میفرسته
- بلومبرگ + FXStreet + ECB + Fed
- بدون قیمت معاملاتی

pip install -r requirements_v3.txt
"""
import os, requests, feedparser, re, json, time, argparse
from datetime import datetime, timezone, timedelta
from bs4 import BeautifulSoup

try:
    from dotenv import load_dotenv
    load_dotenv()
except: pass

try:
    import jdatetime
    HAS_JALALI = True
except:
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


def ai_analyze(news_text, calendar_events, bull_score, bear_score):
    """تحلیل هوشمند با Groq AI"""
    if not HAS_GROQ:
        return None
    try:
        cal_summary = ""
        if calendar_events:
            for ev in calendar_events[:5]:
                cal_summary += f"- {ev.get('country','')}: {ev.get('title','')} (پیش‌بینی: {ev.get('forecast','N/A')})\n"

        prompt = f"""تو یک تحلیل‌گر حرفه‌ای فاندامنتال بازار فارکس هستی، متخصص جفت‌ارز EUR/USD.

بر اساس اخبار و داده‌های زیر، یک تحلیل کوتاه (حداکثر 300 کلمه) به زبان فارسی روان و حرفه‌ای بنویس:

📰 اخبار امروز از Bloomberg، FXStreet، ECB، Fed:
{news_text[:3500]}

📅 تقویم اقتصادی:
{cal_summary if cal_summary else "رویداد مهمی ثبت نشده"}

📊 امتیاز احساسات: صعودی={bull_score} | نزولی={bear_score}

لطفاً تحلیلت شامل این بخش‌ها باشه:
1. 🎯 جهت کلی بازار (صعودی/نزولی/خنثی) با دلیل
2. 🏦 وضعیت بانک‌های مرکزی (ECB و Fed)
3. ⚠️ ریسک‌های مهم امروز
4. 💡 توصیه کلی برای معامله‌گران (بدون قیمت دقیق)

فقط تحلیل فارسی بنویس، بدون مقدمه و بدون توضیح اضافه."""

        response = groq_client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[
                {"role": "system", "content": "تو یک تحلیل‌گر خبره بازار فارکس هستی که به فارسی روان تحلیل می‌نویسی."},
                {"role": "user", "content": prompt}
            ],
            temperature=0.7,
            max_tokens=800,
        )
        return response.choices[0].message.content.strip()
    except Exception as ex:
        print("AI analyze error:", ex)
        return None 

# ---------- CONFIG ----------
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN", "PUT_YOURS")
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "PUT_YOURS")
SEND_VOICE = os.getenv("SEND_VOICE", "true").lower() == "true"
# صدای زنانه پیش‌فرض
VOICE_NAME = os.getenv("VOICE_NAME", "fa-IR-DilaraNeural")
VOICE_RATE = os.getenv("VOICE_RATE", "-5%")
VOICE_PITCH = os.getenv("VOICE_PITCH", "+2Hz")
VOICE_STYLE = os.getenv("VOICE_STYLE", "chat")
NEWS_IMPACT_LEVELS = os.getenv("NEWS_IMPACT", "High,Medium").split(",")  # زنانه – مایکروسافت Edge
VOICE_FALLBACK_LANG = "fa"  # gTTS fallback
# زمان‌های تهران

SCHEDULES = {
    "morning": {"hour": 7, "minute": 30, "label": "🌅 صبح – تحلیل باز شدن اروپا"},
    "news_morning": {"hour": 7, "minute": 40, "label": "☕ صبح – آپدیت خبری"},
    "us_preopen": {"hour": 16, "minute": 0, "label": "🌆 قبل بازار آمریکا"},
    "evening": {"hour": 18, "minute": 0, "label": "🌙 عصر – جمع‌بندی روز"},
    "watch": {"hour": 0, "minute": 0, "label": "🔔 رصد اخبار فوری"},
    "manual": {"hour": 0, "minute": 0, "label": "🔧 اجرای دستی"},
}
# واچ خبر زنده
WATCH_INTERVAL_SECONDS = int(os.getenv("WATCH_INTERVAL", "60"))
# ----------------------------

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
    "tradingeconomics": "https://tradingeconomics.com/euro-area/rss",
}

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36",
    "Accept-Language": "en-US,en;q=0.9,fa;q=0.8",
}

BULLISH = ["weak nfp","weak jobs","miss","dovish fed","fed pause","fed cut","dollar falls","dollar weak","dxy down","ecb hike","lagarde hawkish","euro rises","risk on","warsh dovish","cpi cool us","inflation cools us","unemployment rises"]
BEARISH = ["strong nfp","strong jobs","beat","hawkish fed","fed hike","warsh hawkish","dollar rises","dollar strong","dxy up","safe haven","ecb dovish","ecb pause","lagarde dovish","inflation cools eu","hicp eases","eur falls","oil spike","iran","hormuz","risk off","cpi hot us"]

def fetch_rss(url, n=15):
    out=[]
    try:
        d=feedparser.parse(url)
        for e in d.entries[:n]:
            out.append(f"{getattr(e,'title','')} {getattr(e,'summary','')}")
    except Exception: pass
    return out

def fetch_bloomberg():
    texts=[]
    for rss in SOURCES["bloomberg_rss"]:
        texts+=fetch_rss(rss,15)
    try:
        r=requests.get(SOURCES["bloomberg_web"], headers=HEADERS, timeout=12)
        if r.status_code==200:
            soup=BeautifulSoup(r.text,"html.parser")
            for tag in soup.select("a, h3, h2")[:60]:
                t=tag.get_text(strip=True)
                if t and any(k in t.lower() for k in ["euro","dollar","eur","fed","ecb","inflation","fx"]):
                    if 25 < len(t) < 220:
                        texts.append(t)
    except Exception: pass
    # dedupe
    seen=set(); uniq=[]
    for x in texts:
        if x not in seen:
            seen.add(x); uniq.append(x)
    return uniq[:45]

def fetch_news_all():
    blob=[]
    blob.append("=== BLOOMBERG ===")
    blob+=fetch_bloomberg()
    blob.append("\n=== FXSTREET ===")
    blob+=fetch_rss(SOURCES["fxstreet_rss"],15)
    blob.append("\n=== FOREXLIVE ===")
    blob+=fetch_rss(SOURCES["forexlive"],12)
    blob.append("\n=== ECB ===")
    blob+=fetch_rss(SOURCES["ecb_press"],8)
    blob.append("\n=== FED ===")
    blob+=fetch_rss(SOURCES["fed_press"],8)
    return "\n".join(blob)

def fetch_calendar_full():
    """ForexFactory این هفته – همه High Impact EUR/USD"""
    try:
        r=requests.get("https://nfs.faireconomy.media/ff_calendar_thisweek.json", headers=HEADERS, timeout=12)
        return r.json()
    except Exception as ex:
        return []

def get_today_events():
    data=fetch_calendar_full()
    now_teh=datetime.now(timezone.utc)+timedelta(hours=3,minutes=30)
    today=now_teh.strftime("%Y-%m-%d")
    tomorrow=(now_teh+timedelta(days=1)).strftime("%Y-%m-%d")
    out=[]
    for ev in data:
        if ev.get("country") in ["USD","EUR","EMU"] and ev.get("impact") in ("High","Medium"):
            d=ev.get("date","")[:10]
            if d in [today, tomorrow]:
                out.append(ev)
    return out
    # ---------- MORNING CALENDAR ALERT ----------

TEHRAN_TZ = timezone(timedelta(hours=3, minutes=30))


def impact_to_fa(impact):
    """تبدیل درجه اهمیت خبر به فارسی"""
    impact = (impact or "").strip().lower()

    if impact == "high":
        return "🔴 خیلی مهم"
    elif impact == "medium":
        return "🟠 متوسط مهم"
    elif impact == "low":
        return "🟢 کم‌اهمیت"
    else:
        return "⚪ نامشخص"


def parse_event_datetime(event):
    """تلاش برای خواندن زمان خبر از تقویم"""
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
    """نمایش ساعت خبر به وقت تهران"""
    dt = parse_event_datetime(event)

    if dt:
        teh = dt.astimezone(TEHRAN_TZ)
        return teh.strftime("%H:%M تهران")

    raw_time = event.get("time", "")
    if raw_time:
        return str(raw_time)

    return "زمان نامشخص"


def is_event_today_tehran(event):
    """بررسی اینکه خبر برای امروز تهران است یا نه"""
    dt = parse_event_datetime(event)

    if not dt:
        return True

    event_day = dt.astimezone(TEHRAN_TZ).date()
    today_tehran = datetime.now(TEHRAN_TZ).date()

    return event_day == today_tehran


def expected_event_impact(event):
    """
    توضیح اثر احتمالی خبر روی EUR/USD قبل از انتشار actual.
    این تابع برای یادآور صبحگاهی استفاده می‌شود.
    """

    title = (event.get("title") or "").lower()
    country = (event.get("country") or "").upper()

    # ---------- USD EVENTS ----------

    if country == "USD" and any(k in title for k in ["cpi", "inflation", "pce"]):
        return (
            "اگر عدد تورم بالاتر از پیش‌بینی منتشر شود، احتمال تقویت دلار بیشتر می‌شود و EUR/USD می‌تواند فشار نزولی بگیرد. "
            "اگر عدد پایین‌تر از پیش‌بینی باشد، دلار می‌تواند تضعیف شود و EUR/USD حمایت بگیرد."
        )

    if country == "USD" and any(k in title for k in ["nfp", "nonfarm", "non-farm", "payroll", "employment change"]):
        return (
            "عدد اشتغال قوی‌تر از پیش‌بینی معمولاً به نفع دلار است و می‌تواند EUR/USD را تحت فشار بگذارد. "
            "عدد ضعیف‌تر از پیش‌بینی معمولاً به ضرر دلار و به نفع EUR/USD است."
        )

    if country == "USD" and any(k in title for k in ["unemployment claims", "unemployment rate", "jobless claims", "initial jobless", "continuing claims", "claims"]):
        return (
            "برای داده‌های مطالبات بیکاری آمریکا، عدد بالاتر از پیش‌بینی معمولاً نشانه ضعف بازار کار است؛ "
            "این حالت می‌تواند دلار را تضعیف کند و برای EUR/USD حمایتی باشد. "
            "عدد پایین‌تر از پیش‌بینی معمولاً نشانه بازار کار قوی‌تر است، می‌تواند دلار را تقویت کند و روی EUR/USD فشار نزولی بگذارد."
        )

    if country == "USD" and any(k in title for k in ["average hourly earnings", "wages", "wage"]):
        return (
            "رشد دستمزد بالاتر از پیش‌بینی می‌تواند فشار تورمی را بالا نگه دارد و به نفع دلار باشد. "
            "رشد دستمزد پایین‌تر از پیش‌بینی می‌تواند انتظارات سیاست انقباضی Fed را کاهش دهد و به ضرر دلار باشد."
        )

    if country == "USD" and any(k in title for k in ["fomc", "fed", "powell", "rate decision", "interest rate"]):
        return (
            "لحن هاوکیش فدرال رزرو معمولاً دلار را تقویت می‌کند و برای EUR/USD نزولی است. "
            "لحن داویش می‌تواند دلار را تضعیف کند و به EUR/USD کمک کند."
        )

    if country == "USD" and any(k in title for k in ["retail sales", "gdp", "ism", "pmi", "durable goods", "consumer confidence"]):
        return (
            "عدد قوی‌تر از پیش‌بینی معمولاً دلار را تقویت می‌کند و برای EUR/USD فشار نزولی دارد. "
            "عدد ضعیف‌تر از پیش‌بینی می‌تواند دلار را تضعیف کند و به نفع EUR/USD باشد."
        )

    # ---------- EUR / EURO AREA EVENTS ----------

    if country in ["EUR", "EMU"] and any(k in title for k in ["cpi", "inflation", "hicp"]):
        return (
            "تورم بالاتر از پیش‌بینی می‌تواند احتمال لحن هاوکیش‌تر ECB را بالا ببرد و به نفع یورو باشد. "
            "تورم پایین‌تر از پیش‌بینی می‌تواند یورو را تضعیف کند و برای EUR/USD منفی باشد."
        )

    if country in ["EUR", "EMU"] and any(k in title for k in ["ecb", "lagarde", "rate decision", "interest rate"]):
        return (
            "لحن هاوکیش ECB معمولاً به نفع یورو و صعود EUR/USD است. "
            "لحن داویش ECB می‌تواند یورو را تضعیف کند و برای EUR/USD منفی باشد."
        )

    if country in ["EUR", "EMU"] and any(k in title for k in ["gdp", "pmi", "retail sales", "zew", "ifo", "employment", "unemployment"]):
        return (
            "داده قوی‌تر از انتظار معمولاً به نفع یورو است و می‌تواند EUR/USD را حمایت کند. "
            "داده ضعیف‌تر می‌تواند یورو را تحت فشار بگذارد."
        )

    return (
        "این خبر می‌تواند روی احساسات بازار اثر بگذارد. هنگام انتشار باید عدد واقعی با پیش‌بینی مقایسه شود."
    )
def event_number(value):
    m = re.search(r'[-+]?\d+(?:\.\d+)?', str(value or "").replace(",", ""))
    return float(m.group()) if m else None


def released_event_impact(event):
    title = (event.get("title") or "").lower()
    country = (event.get("country") or "").upper()

    actual = event_number(event.get("actual"))
    forecast = event_number(event.get("forecast"))

    if actual is None or forecast is None:
        return "خبر منتشر شده، اما برای تحلیل دقیق باید عدد واقعی با پیش‌بینی مقایسه شود."

    if actual == forecast:
        return "عدد واقعی مطابق پیش‌بینی منتشر شد؛ اثر اولیه روی EUR/USD خنثی است."

    higher = actual > forecast

    if country == "USD" and any(k in title for k in ["unemployment claims", "jobless claims", "unemployment rate", "claims"]):
        if higher:
            return "عدد بیکاری بالاتر از پیش‌بینی آمد؛ این معمولاً دلار را تضعیف می‌کند و برای EUR/USD صعودی است."
        else:
            return "عدد بیکاری پایین‌تر از پیش‌بینی آمد؛ این معمولاً دلار را تقویت می‌کند و برای EUR/USD نزولی است."

    if country == "USD":
        if higher:
            return "عدد آمریکا قوی‌تر از پیش‌بینی آمد؛ این معمولاً دلار را تقویت می‌کند و برای EUR/USD نزولی است."
        else:
            return "عدد آمریکا ضعیف‌تر از پیش‌بینی آمد؛ این معمولاً دلار را تضعیف می‌کند و برای EUR/USD صعودی است."

    if country in ["EUR", "EMU"]:
        if higher:
            return "عدد اروپا بهتر از پیش‌بینی آمد؛ این معمولاً یورو را تقویت می‌کند و برای EUR/USD صعودی است."
        else:
            return "عدد اروپا ضعیف‌تر از پیش‌بینی آمد؛ این معمولاً یورو را تضعیف می‌کند و برای EUR/USD نزولی است."

    return "خبر منتشر شد؛ اثر آن باید در کنار واکنش دلار و یورو بررسی شود."

def build_morning_calendar_alert(calendar_events):
    """
    ساخت پیام صبحگاهی برای خبرهای High و Medium امروز.
    """

    now_teh = datetime.now(TEHRAN_TZ)

    if HAS_JALALI:
        jd = jdatetime.datetime.fromgregorian(datetime=now_teh)
        date_fa = jd.strftime("%A %d %B %Y – %H:%M تهران")
    else:
        date_fa = now_teh.strftime("%Y-%m-%d %H:%M تهران")

    allowed_impacts = {x.strip().lower() for x in NEWS_IMPACT_LEVELS}

    events = []
    for ev in calendar_events:
        impact = (ev.get("impact") or "").strip().lower()

        if impact not in allowed_impacts:
            continue

        if not is_event_today_tehran(ev):
            continue

        events.append(ev)

    if not events:
        return f"""🌅 یادآور اقتصادی امروز EUR/USD

{date_fa}

امروز برای EUR/USD خبر High یا Medium مهمی در تقویم ثبت نشده است.

با این حال بازار می‌تواند به تیترهای ناگهانی Fed، ECB، دلار، اوراق آمریکا و فضای ریسک جهانی واکنش نشان دهد.

⚠️ نکته:
حتی در روزهای بدون خبر قرمز، سخنرانی‌های ناگهانی یا تیترهای ژئوپلیتیک می‌توانند نوسان ایجاد کنند.
"""

    def sort_key(ev):
        dt = parse_event_datetime(ev)
        if dt:
            return dt.astimezone(TEHRAN_TZ)
        return datetime.max.replace(tzinfo=TEHRAN_TZ)

    events = sorted(events, key=sort_key)

    lines = []

    for ev in events:
        country = ev.get("country", "")
        title = ev.get("title", "")
        impact = ev.get("impact", "")
        forecast = ev.get("forecast", "")
        previous = ev.get("previous", "")

        time_fa = event_time_tehran(ev)
        impact_fa = impact_to_fa(impact)
        effect = expected_event_impact(ev)

        block = f"""━━━━━━━━━━━━━━
{impact_fa}
🕒 زمان: {time_fa}
🌍 ارز: {country}
📌 خبر: {title}"""

        if forecast:
            block += f"\n📊 پیش‌بینی: {forecast}"

        if previous:
            block += f"\n📉 قبلی: {previous}"

        block += f"""

اثر احتمالی روی EUR/USD:
{effect}
"""

        lines.append(block)

    msg = f"""🌅 یادآور اقتصادی امروز EUR/USD

{date_fa}

امروز این خبرهای مهم و متوسط برای یورو/دلار زیر نظر هستند:

{chr(10).join(lines)}

⚠️ هشدار مدیریت ریسک
:نزدیک زمان خبرهای قرمز و نارنجی، احتمال افزایش نوسان وجود دارد. بهتر است قبل از انتشار داده، از تصمیم عجولانه و حجم بالا پرهیز شود.
"""

    return msg

# واچر خبر زنده
_notified_events=set()
_headline_seen=set()

def check_breaking_headlines():
    """چک هدلاین بلومبرگ/FXStreet – اگر تیتر جدید با کلمات EUR/USD/Fed/ECB آمد"""
    global _headline_seen
    try:
        import hashlib
        from bs4 import BeautifulSoup
        import requests, feedparser
        urls=[
            "https://www.fxstreet.com/news/forex/feed",
            "https://feeds.bloomberg.com/markets/news.rss",
            "https://www.forexlive.com/feed/"
        ]
        hits=[]
        keywords=["eurusd","eur/usd","euro dollar","ecb","fed","lagarde","warsh","cpi","nfp","eurozone","eur "," usd "]
        for u in urls:
            try:
                d=feedparser.parse(u)
                for e in d.entries[:5]:
                    title=getattr(e,"title","").lower()
                    h=hashlib.md5(title.encode()).hexdigest()
                    if h in _headline_seen: continue
                    if any(k in title for k in keywords):
                        _headline_seen.add(h)
                        # اولین بار که اسکریپت اجرا می‌شود همه را mark کن، نفرست – با فلگ قابل کنترل است
                        # اینجا فرض می‌کنیم بعد از اولین پرایم هستیم
                        hits.append(title)
            except: pass
        return hits[:3]
    except Exception:
        return []

def check_live_news():
    """هر دقیقه چک می‌کند – اگر actual جدید آمد، True برمی‌گرداند با متن خبر"""
    global _notified_events
    try:
        data=fetch_calendar_full()
        now_teh=datetime.now(timezone.utc)+timedelta(hours=3,minutes=30)
        today=now_teh.strftime("%Y-%m-%d")
        hits=[]
        for ev in data:
            if ev.get("country") not in ["USD","EUR","EMU"]: continue
            if ev.get("impact") not in ("High","Medium"): continue
            datestr=ev.get("date","")[:10]
            if datestr!=today: continue
            actual= (ev.get("actual") or "").strip()
            if not actual: continue
            uid=f"{ev.get('title')}_{ev.get('date')}_{ev.get('time')}"
            if uid in _notified_events: continue
            # خبر جدید منتشر شده
            _notified_events.add(uid)
            title=ev.get("title","")
            country=ev.get("country","")
            actual=ev.get("actual","")
            forecast=ev.get("forecast","")
            previous=ev.get("previous","")
            # تفسیر سریع
            # قانون ساده: اگر USD خبر بدتر از forecast → یورو صعودی
            # این خیلی ساده است – بعدا قابل ارتقا
            item = {
                "title": title,
                "country": country,
                "actual": actual,
                "forecast": forecast,
                "previous": previous,
                "time": ev.get("time", "")
            }

            item["instant_impact"] = released_event_impact(item)

            hits.append(item)
        
        return hits
    except Exception as ex:
        return []

def score_sentiment(text):
    low=text.lower()
    bull=sum(low.count(k) for k in BULLISH)
    bear=sum(low.count(k) for k in BEARISH)
    # وزن بلومبرگ
    if "=== bloomberg ===" in low:
        try:
            bloom=low.split("=== bloomberg ===")[1].split("===")[0]
            bull+=sum(bloom.count(k) for k in BULLISH)//2
            bear+=sum(bloom.count(k) for k in BEARISH)//2
        except: pass
    return bull, bear

def build_currency_strength(bull, bear, calendar_events=None, breaking_news=None):
    eur_score = int(bull)
    usd_score = int(bear)

    calendar_events = calendar_events or []

    high_count = sum(1 for ev in calendar_events if (ev.get("impact") or "").lower() == "high")
    medium_count = sum(1 for ev in calendar_events if (ev.get("impact") or "").lower() == "medium")

    risk_level = "پایین"
    if high_count >= 1:
        risk_level = "بالا"
    elif medium_count >= 1:
        risk_level = "متوسط"

    if breaking_news:
        bn = breaking_news[0] if isinstance(breaking_news, list) else breaking_news
        impact_text = str(bn.get("instant_impact", ""))

        if "صعودی" in impact_text:
            eur_score += 3
        elif "نزولی" in impact_text:
            usd_score += 3

    diff = eur_score - usd_score

    if diff >= 5:
        result = "برتری فعلی با یورو است؛ فشار بنیادی بیشتر به سمت صعود EUR/USD است."
    elif diff <= -5:
        result = "برتری فعلی با دلار است؛ فشار بنیادی بیشتر به سمت نزول EUR/USD است."
    elif diff > 0:
        result = "یورو کمی برتری دارد، اما اختلاف هنوز قوی نیست."
    elif diff < 0:
        result = "دلار کمی برتری دارد، اما اختلاف هنوز قوی نیست."
    else:
        result = "قدرت یورو و دلار تقریباً برابر است؛ بازار حالت خنثی و رنج دارد."

    return f"""⚖️ قدرت نسبی ارزها:

• قدرت EUR: {eur_score}
• قدرت USD: {usd_score}
• ریسک تقویم امروز: {risk_level}

نتیجه:
{result}
"""

def build_timeframe_view(bull, bear, calendar_events=None, breaking_news=None):
    """
    ساخت دید لحظه‌ای، امروز و بلندمدت برای EUR/USD
    """

    diff = bull - bear
    calendar_events = calendar_events or []

    high_events = [
        ev for ev in calendar_events
        if (ev.get("impact") or "").lower() == "high"
    ]

    medium_events = [
        ev for ev in calendar_events
        if (ev.get("impact") or "").lower() == "medium"
    ]

    # دید لحظه‌ای
    if breaking_news:
        instant = "بازار در حال واکنش به خبر تازه منتشرشده است؛ جهت لحظه‌ای باید با actual نسبت به forecast سنجیده شود."
    elif diff >= 3:
        instant = "متمایل به صعود EUR/USD؛ فشار خبری فعلی بیشتر علیه دلار یا به نفع یورو است."
    elif diff <= -3:
        instant = "متمایل به نزول EUR/USD؛ جریان خبری فعلی بیشتر به نفع دلار یا علیه یورو است."
    else:
        instant = "خنثی تا رنج؛ بازار فعلاً سیگنال لحظه‌ای قوی ندارد."

    # دید امروز
    if high_events:
        today = "امروز بازار زیر سایه خبرهای قرمز است؛ تا قبل از انتشار داده‌های مهم، احتیاط و نوسان‌گیری کوتاه‌مدت محتمل‌تر است."
    elif medium_events:
        today = "امروز خبرهای نارنجی می‌توانند جهت کوتاه‌مدت بدهند، اما برای روند قوی نیاز به تأیید از دلار، اوراق و لحن بانک‌های مرکزی است."
    else:
        today = "امروز از نظر تقویم اقتصادی فشار خبری سنگین دیده نمی‌شود؛ تیترهای Fed، ECB و احساسات ریسک جهانی مهم‌تر می‌شوند."

    # دید بلندمدت
    if diff >= 6:
        long_term = "در نمای کلان، اگر ضعف دلار ادامه پیدا کند، EUR/USD می‌تواند حمایت بنیادی بیشتری بگیرد؛ اما تأیید آن به داده‌های تورم و سیاست Fed نیاز دارد."
    elif diff <= -6:
        long_term = "در نمای کلان، برتری نسبی دلار فعلاً پررنگ‌تر است؛ تا وقتی داده‌های آمریکا قوی بماند یا Fed هاوکیش باشد، فشار روی EUR/USD باقی می‌ماند."
    else:
        long_term = "دید بلندمدت فعلاً خنثی است؛ مسیر اصلی به تفاوت سیاست‌های Fed و ECB، تورم و رشد اقتصادی دو طرف بستگی دارد."

    return f"""📌 جمع‌بندی چندزمانه:

• لحظه‌ای: {instant}

• امروز: {today}

• بلندمدت: {long_term}
"""

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

    if diff >= 3:
        direction = "صعودی"
        bias = "خرید در اصلاح"
        emoji = "سبز"
        conf = "متوسط به بالا"
    elif diff <= -3:
        direction = "نزولی"
        bias = "فروش در رشد"
        emoji = "قرمز"
        conf = "متوسط به بالا"
    elif diff >= 1:
        direction = "خنثی متمایل به صعود"
        bias = "رنج صعودی"
        emoji = "زرد"
        conf = "متوسط"
    elif diff <= -1:
        direction = "خنثی متمایل به نزول"
        bias = "رنج نزولی"
        emoji = "زرد"
        conf = "متوسط"
    else:
        direction = "خنثی / رنج"
        bias = "انتظار داده"
        emoji = "خنثی"
        conf = "پایین"

    breaking_block = ""

    if breaking_news:
        bn = breaking_news[0] if isinstance(breaking_news, list) else breaking_news

        if "released_event_impact" in globals():
            impact_text = bn.get("instant_impact") or released_event_impact(bn)
        else:
            impact_text = bn.get("instant_impact") or "خبر منتشر شده و نیاز به بررسی واکنش بازار دارد."

        breaking_block = "\n".join([
            "خبر فوری:",
            f"{bn.get('country', '')} - {bn.get('title', '')}",
            f"واقعی: {bn.get('actual', '')} | پیش بینی: {bn.get('forecast', '')} | قبلی: {bn.get('previous', '')}",
            f"نظر فوری: {impact_text}",
        ])

    sentences = re.split(r'[\.\n]', news_text or "")
    keys = []
    all_kw = BULLISH + BEARISH + ["ecb", "fed", "lagarde", "cpi", "pce", "nfp", "dollar", "euro", "inflation"]

    for s in sentences:
        s_clean = s.strip()
        s_low = s_clean.lower()

        if any(k in s_low for k in all_kw) and 30 < len(s_clean) < 220:
            s_clean = re.sub(r'\b1\.\d{3,5}\b', 'سطح قیمتی', s_clean)
            s_clean = re.sub(r'\$\d+[\.\d]*', 'قیمت', s_clean)

            if s_clean not in keys:
                keys.append(s_clean)

        if len(keys) >= 4:
            break

    if not keys:
        keys = [
            "در منابع خبری فعلی، تیتر قوی و قطعی برای جهت دهی بازار دیده نشد.",
            "بازار ممکن است تا انتشار داده های مهم بعدی در حالت احتیاط باقی بماند.",
            "واکنش دلار، یورو و لحن بانک های مرکزی برای ادامه مسیر مهم است."
        ]

    bullets = "\n".join([f"- {k[:180]}" for k in keys[:4]])

    if calendar_events:
        cal_lines = []

        for ev in calendar_events[:5]:
            tm = ev.get("time", ev.get("date", ""))
            ct = ev.get("country", "")
            ttl = ev.get("title", "")
            impact = ev.get("impact", "")
            fc = ev.get("forecast", "")

            line = f"- {tm} | {ct} | {impact} | {ttl}"
            if fc:
                line += f" | پیش بینی: {fc}"

            cal_lines.append(line)

        calendar_text = "\n".join(cal_lines) if cal_lines else "امروز رویداد مهمی ثبت نشده است."
    else:
        calendar_text = "امروز رویداد High یا Medium مهمی ثبت نشده است."

    try:
        timeframe_view = build_timeframe_view(bull, bear, calendar_events, breaking_news)
    except Exception:
        timeframe_view = "جمع بندی چندزمانه فعلا در دسترس نیست."

    try:
        currency_strength = build_currency_strength(bull, bear, calendar_events, breaking_news)
    except Exception:
        currency_strength = "قدرت نسبی ارزها فعلا در دسترس نیست."

    msg_parts = [
        f"{emoji} تحلیل فاندامنتال EUR/USD - {slot_label}",
        "",
        date_fa,
        ""
    ]

    if breaking_block:
        msg_parts.extend([
            breaking_block,
            ""
        ])

    msg_parts.extend([
        f"جهت فاندامنتال: {direction}",
        f"تمایل: {bias}",
        f"اطمینان: {conf}",
        "",
        str(timeframe_view),
        "",
        str(currency_strength),
        "",
        "خلاصه منابع:",
        bullets,
        "",
        "تقویم اقتصادی امروز/فردا:",
        calendar_text,
        "",
        "بانک های مرکزی:",
        "- ECB: وضعیت بانک مرکزی اروپا بر اساس خبرهای امروز و لحن بازار بررسی می شود.",
        "- Fed: وضعیت فدرال رزرو بر اساس داده های آمریکا، تورم، اشتغال و لحن اعضا بررسی می شود.",
        "",
        f"نتیجه: جهت کوتاه مدت {direction} است. تا قبل از داده های مهم، مدیریت ریسک ضروری است.",
        "",
        f"@EURUSD_Fa_Bot | {date_short}",
        f"امتیاز خبری: صعودی {bull} / نزولی {bear}"
    ])

    msg = "\n".join(msg_parts)

    voice_parts = [
        f"تحلیل فاندامنتال یورو دلار، {date_short}، {slot_label}.",
        f"جهت امروز: {direction}. اطمینان: {conf}.",
        "بانک مرکزی اروپا بر اساس خبرهای امروز بررسی می شود.",
        "فدرال رزرو بر اساس داده های آمریکا بررسی می شود.",
        "بازار ممکن است نوسانی باشد. با مدیریت ریسک معامله کنید."
    ]

    voice_text = "\n".join(voice_parts)
    voice_text = re.sub(r'\b1\.\d{3,5}\b', '', voice_text)

    return msg, voice_text
                        

def send_telegram_text(text):
    if TELEGRAM_TOKEN.startswith("PUT_"):
        print("=== DRY RUN TEXT ===")
        print(text[:2000])
        return True

    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"

    # اگه پیام طولانی‌تر از 4000 کاراکتره، به چند بخش تقسیم کن
    max_len = 4000
    if len(text) <= max_len:
        chunks = [text]
    else:
        chunks = []
        while text:
            chunk = text[:max_len]
            # سعی کن آخرین خط کامل رو جدا کنی
            last_newline = chunk.rfind('\n')
            if last_newline > max_len // 2:
                chunk = chunk[:last_newline]
            chunks.append(chunk)
            text = text[len(chunk):].lstrip()

    all_ok = True
    for i, chunk in enumerate(chunks):
        try:
            r = requests.post(
                url,
                data={
                    "chat_id": CHAT_ID,
                    "text": chunk,
                    "parse_mode": "Markdown",
                    "disable_web_page_preview": True
                },
                timeout=20
            )
            print(f"Telegram text part {i+1}/{len(chunks)}:", r.status_code)
            if not r.ok:
                all_ok = False
                # اگه Markdown مشکل داشت، بدون parse_mode بفرست
                r2 = requests.post(
                    url,
                    data={
                        "chat_id": CHAT_ID,
                        "text": chunk,
                        "disable_web_page_preview": True
                    },
                    timeout=20
                )
                print(f"Retry without markdown: {r2.status_code}")
                if r2.ok:
                    all_ok = True
        except Exception as ex:
            print(f"Send error: {ex}")
            all_ok = False

    return all_ok

def send_telegram_voice(text_fa):
    if not SEND_VOICE:
        return False
    audio_path=None
    try:
        # اول سعی edge-tts زنانه
        try:
            import edge_tts, asyncio, tempfile
            voice = os.getenv("VOICE_NAME", VOICE_NAME)
            async def _synth():
                communicate = edge_tts.Communicate(text_fa, voice, rate=VOICE_RATE, pitch=VOICE_PITCH)
                with tempfile.NamedTemporaryFile(delete=False, suffix=".mp3") as tf:
                    out_path=tf.name
                await communicate.save(out_path)
                return out_path
            audio_path = asyncio.run(_synth())
        except Exception as e_edge:
            print("edge-tts failed, fallback gTTS:", e_edge)
            # fallback gTTS – صدای پیش‌فرض فارسی نسبتا زنانه است
            from gtts import gTTS
            import tempfile
            tts=gTTS(text=text_fa, lang='fa', slow=False)
            fd, audio_path = tempfile.mkstemp(suffix=".mp3")
            os.close(fd)
            tts.save(audio_path)

        if TELEGRAM_TOKEN.startswith("PUT_"):
            print(f"[VOICE DRY RUN] saved {audio_path}")
            print("Voice text:", text_fa)
            return True

        url=f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendAudio"
        with open(audio_path, "rb") as f:
            files={"audio": f}
            data={"chat_id": CHAT_ID, "title": "EUR/USD FA – Persian – Female", "performer": "EURUSD_Fa_Bot", "caption": "تحلیل صوتی – زنانه – بدون قیمت"}
            r=requests.post(url, data=data, files=files, timeout=30)
        print("Telegram voice:", r.status_code)
        return r.ok
    except Exception as ex:
        print("Voice error:", ex)
        return False
    finally:
        try:
            if audio_path and os.path.exists(audio_path):
                os.unlink(audio_path)
        except: pass

def run_once(slot="manual"):
    print(f"[{slot}] Fetching news ...")
    news = fetch_news_all()
    cal = get_today_events()

        # پیام یادآور صبحگاهی خبرهای High و Medium
    if slot in ["morning", "manual"]:
        calendar_msg = build_morning_calendar_alert(cal)
        send_telegram_text(calendar_msg)
    bull, bear = score_sentiment(news)
    slot_label = SCHEDULES.get(slot, {}).get("label", slot)

    # 🔔 حالت watch: فقط اگه خبر High Impact جدید باشه پیام بده
    if slot == "watch":
        hits = check_live_news()
        if not hits:
            print("[watch] No new high-impact events. Skipping.")
            return
        print(f"[watch] {len(hits)} new event(s) found")

    # 🤖 تحلیل با هوش مصنوعی Groq
    ai_analysis = ai_analyze(news, cal, bull, bear)

    # 📊 محاسبه جهت بازار
    diff = bull - bear
    if diff >= 3:
        direction_emoji = "🟢"
        direction = "صعودی"
    elif diff <= -3:
        direction_emoji = "🔴"
        direction = "نزولی"
    elif diff >= 1:
        direction_emoji = "🟡🟢"
        direction = "خنثی متمایل به صعود"
    elif diff <= -1:
        direction_emoji = "🟡🔴"
        direction = "خنثی متمایل به نزول"
    else:
        direction_emoji = "⚪️"
        direction = "خنثی / رنج"

    # 📅 زمان تهران
    now_teh = datetime.now(timezone.utc) + timedelta(hours=3, minutes=30)
    if HAS_JALALI:
        jd = jdatetime.datetime.fromgregorian(datetime=now_teh)
        date_fa = jd.strftime("%A %d %B %Y – %H:%M")
    else:
        date_fa = now_teh.strftime("%Y-%m-%d %H:%M")

    # 🎨 ساخت پیام حرفه‌ای
    if ai_analysis:
        text_msg = "\n".join([
            f"{direction_emoji} EUR/USD | {slot_label}",
            "",
            f"زمان تهران: {date_fa}",
            "",
            "تحلیل هوش مصنوعی:",
            "",
            str(ai_analysis),
            "",
            "--------------------",
            "خلاصه احساسات بازار:",
            f"- جهت: {direction}",
            f"- امتیاز صعودی: {bull}",
            f"- امتیاز نزولی: {bear}",
            f"- رویدادهای مهم امروز: {len(cal)}",
            "",
            "این تحلیل صرفا اطلاع رسانی است و توصیه معاملاتی نیست.",
            "",
            "@EURUSDFaBot"
        ])
    else:
        text_msg = "\n".join([
            f"{direction_emoji} EUR/USD | {slot_label}",
            "",
            f"زمان تهران: {date_fa}",
            "",
            "تحلیل هوش مصنوعی در دسترس نیست.",
            "",
            f"- جهت: {direction}",
            f"- امتیاز صعودی: {bull}",
            f"- امتیاز نزولی: {bear}",
            f"- رویدادهای مهم امروز: {len(cal)}",
            "",
            "@EURUSDFaBot"
        ])

    # 📤 ارسال به تلگرام
    if send_telegram_text(text_msg):
        print("✅ Text sent successfully")
    else:
        print("❌ Text send failed")

    if SEND_VOICE:
        if send_telegram_voice(voice_text):
            print("✅ Voice sent successfully")
        else:
            print("❌ Voice send failed")
def watch_news_loop():
    """واچر زنده – هر 60 ثانیه چک می‌کند، اگر خبر High Impact جدید منتشر شد بلافاصله تحلیل می‌فرستد"""
    print("Live news watcher started – interval", WATCH_INTERVAL_SECONDS, "sec – Ctrl+C to stop")
    # یک بار اول state را پر کن بدون ارسال
    check_live_news()  # پرایم – تا خبرهای قدیمی امروز را mark کند، اگر نمی‌خواهی اولین بار بفرستد، دو خط پایین را کامنت کن
    global _notified_events
    _notified_events.clear()  # اگر می‌خواهی خبرهای امروز که قبلا آمده هم دوباره بفرستد، این خط را نگه دار، وگرنه حذف کن
    while True:
        try:
            hits = check_live_news()
            # --- خبر فوری هدلاین --- 
            headlines = []
            try:
                headlines = check_breaking_headlines()
            except: pass
            if headlines and not hits:
                # تبدیل هدلاین به شبه-event برای ارسال فوری
                hits = [{"title": h[:120], "country": "NEWS", "actual": "breaking", "forecast": "-", "previous": "-", "time": "now"} for h in headlines]
            if hits:
                print(f"[BREAKING] {len(hits)} new High Impact event(s)")
                # تحلیل فوری با خبر جدید
                news = fetch_news_all()
                # خبر فوری را به بالای news اضافه کن
                breaking_text = "\n".join([f"{h['country']} {h['title']} Actual {h['actual']} Forecast {h['forecast']}" for h in hits])
                news = breaking_text + "\n" + news
                bull, bear = score_sentiment(news)
                cal = get_today_events()
                text_msg, voice_msg = build_brief(news, bull, bear, cal, slot_label="خبر فوری – آپدیت آنی", breaking_news=hits)
                send_telegram_text(text_msg)
                send_telegram_voice(voice_msg)
            time.sleep(WATCH_INTERVAL_SECONDS)
        except KeyboardInterrupt:
            print("Watcher stopped.")
            break
        except Exception as ex:
            print("Watcher error:", ex)
            time.sleep(WATCH_INTERVAL_SECONDS)

if __name__=="__main__":
    import argparse
    parser=argparse.ArgumentParser(description="EUR/USD FA Persian Telegram Bot v3")
    parser.add_argument("--slot", choices=["morning","news_morning","us_preopen","evening","manual","watch"], default="manual")
    parser.add_argument("--watch", action="store_true", help="اجرای واچر خبر زنده – بعد از هر داده High Impact بلافاصله تحلیل می‌فرستد")
    parser.add_argument("--once", action="store_true", help="فقط یک بار اجرا")
    args=parser.parse_args()

    if args.watch:
        watch_news_loop()
    else:
        run_once(args.slot if args.slot else "manual")
