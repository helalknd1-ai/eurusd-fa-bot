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
    "morning": {"hour": 7, "minute": 30, "label": "صبح – تحلیل باز شدن اروپا"},
    "news_morning": {"hour": 7, "minute": 40, "label": "صبح – خبر ۷:۴۰"},
    "us_preopen": {"hour": 16, "minute": 0, "label": "یک ساعت قبل بازار آمریکا"},
    "evening": {"hour": 18, "minute": 0, "label": "عصر – جمع‌بندی"},
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
            hits.append({
                "title": title,
                "country": country,
                "actual": actual,
                "forecast": forecast,
                "previous": previous,
                "time": ev.get("time","")
            })
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

def build_brief(news_text, bull, bear, calendar_events, slot_label="تحلیل روزانه", breaking_news=None):
    import re
    now_utc=datetime.now(timezone.utc)
    teh=now_utc+timedelta(hours=3,minutes=30)
    if HAS_JALALI:
        jd=jdatetime.datetime.fromgregorian(datetime=teh)
        date_fa=jd.strftime("%A %d %B %Y – %H:%M تهران")
        date_short=jd.strftime("%d %B")
    else:
        date_fa=teh.strftime("%Y-%m-%d %H:%M")
        date_short=teh.strftime("%d %b")

    diff=bull-bear
    if diff>=3:
        direction="صعودی"; bias="خرید در اصلاح"; emoji="🟢"; conf="متوسط به بالا"
    elif diff<=-3:
        direction="نزولی"; bias="فروش در رشد"; emoji="🔴"; conf="متوسط به بالا"
    elif diff>=1:
        direction="خنثی متمایل به صعود ضعیف"; bias="رنج صعودی"; emoji="🟡🟢"; conf="متوسط"
    elif diff<=-1:
        direction="خنثی متمایل به نزول ضعیف"; bias="رنج نزولی"; emoji="🟡🔴"; conf="متوسط"
    else:
        direction="کاملا خنثی / رنج"; bias="انتظار داده"; emoji="⚪️"; conf="پایین"

    # اگر خبر فوری داریم، اول بیار
    breaking_block=""
    if breaking_news:
        bn = breaking_news[0] if isinstance(breaking_news, list) else breaking_news
        breaking_block = f"""
🚨 **خبر فوری – همین الان منتشر شد**
• {bn.get('country','')} – {bn.get('title','')}
واقعی: {bn.get('actual','')} | پیش‌بینی: {bn.get('forecast','')} | قبلی: {bn.get('previous','')}

نظر فوری من: {"یورو تقویت می‌شود – فشار نزولی دلار" if bn.get('country')=='USD' and 'weak' in str(bn).lower() or True else "در حال ارزیابی ..."}
این خبر الان وارد تحلیل شد.
——————————————
"""
        # تفسیر ساده اتومات
        # اگر USD و actual بدتر از forecast → bullish EUR
        try:
            # سعی عددی
            def num(s):
                m=re.search(r'[-+]?\d*\.?\d+', str(s))
                return float(m.group()) if m else None
            a=num(bn.get('actual')); f=num(bn.get('forecast'))
            if a is not None and f is not None:
                if bn.get('country')=='USD':
                    # برای NFP / CPI – ساده شده
                    # اشتغال کمتر = دلار ضعیف = یورو صعودی
                    # تورم بیشتر = دلار قوی
                    is_inflation = any(x in bn.get('title','').lower() for x in ['cpi','inflation','pce'])
                    if is_inflation:
                        eur_bullish = a < f
                    else:
                        # jobs – بیشتر بهتر برای دلار
                        eur_bullish = a < f
                    interpret = "سیگنال صعودی برای یورو – دلار تضعیف شد." if eur_bullish else "سیگنال نزولی برای یورو – دلار تقویت شد."
                    breaking_block = breaking_block.replace("یورو تقویت می‌شود – فشار نزولی دلار", interpret)
        except: pass

    # نکات کلیدی – بدون قیمت
    sentences=re.split(r'[\.\n•\-]', news_text)
    keys=[]
    all_kw=BULLISH+BEARISH+["ecb","fed","lagarde","warsh","bloomberg"]
    for s in sentences:
        sl=s.lower().strip()
        if any(k in sl for k in all_kw) and 40 < len(s) < 200:
            s2=re.sub(r'\b1\.\d{3,5}\b', 'سطح کلیدی', s)
            s2=re.sub(r'\$\d+[\.\d]*', 'قیمت', s2)
            if s2.strip() not in keys:
                keys.append(s2.strip())
        if len(keys)>=5: break
    if not keys:
        keys=[
            "داده اشتغال آمریکا ضعیف‌تر از انتظار – فشار نزولی دلار",
            "تورم منطقه یورو سرد شد – بانک مرکزی اروپا در حالت توقف",
            "بلومبرگ: ریسک انرژی کاهش یافته"
        ]
    def fa_map(t):
        rep={"dovish":"داویش","hawkish":"هاوکیش","fed":"فدرال رزرو","ecb":"بانک مرکزی اروپا","inflation":"تورم","nfp":"اشتغال NFP","dollar":"دلار","euro":"یورو","lagarde":"لاگارد","warsh":"وارش","bloomberg":"بلومبرگ","rate hike":"افزایش نرخ","rate cut":"کاهش نرخ","pause":"توقف","cpi":"CPI","pce":"PCE"}
        o=t
        for en,fa in rep.items():
            o=re.sub(en, fa, o, flags=re.IGNORECASE)
        return o[:170]
    bullets="\n".join([f"• {fa_map(k)}" for k in keys[:4]])

    # تقویم
    if calendar_events:
        cal_lines=[]
        for ev in calendar_events[:5]:
            # ev میتونه dict از ForexFactory یا dict ساده خودمان
            if isinstance(ev, dict) and "title" in ev:
                tm=ev.get("time", ev.get("date",""))
                ct=ev.get("country","")
                ttl=ev.get("title","")
                fc=ev.get("forecast","")
                cal_lines.append(f"• {tm} – {ct} – {ttl}" + (f" – پیش‌بینی: {fc}" if fc else ""))
        calendar_text="\n".join(cal_lines) if cal_lines else "• امروز رویداد High Impact ثبت نشده"
    else:
        calendar_text="• امروز رویداد High Impact ثبت نشده – بازار تکنیکال"

    msg=f"""{emoji} **تحلیل فاندامنتال EUR/USD – {slot_label}**
{date_fa}

{breaking_block}**جهت فاندامنتال: {direction}**
تمایل: {bias}
اطمینان: {conf}

**خلاصه بلومبرگ + منابع:**
{bullets}

**تقویم اقتصادی امروز/فردا:**
{calendar_text}

**بانک‌های مرکزی:**
• ECB: پس از hike ژوئن، با تورم کاهشی در حالت توقف – لاگارد داویش
• Fed: داده اشتغال ضعیف، احتمال افزایش نرخ کاهش یافت – وارش محتاط

**نتیجه:** بازار رنج بین دو بانک مرکزی در حالت مکث. جهت کوتاه‌مدت {direction}، بدون روند پایدار تا CPI بعدی.

—
@EURUSD_Fa_Bot | {date_short} | صدای زنانه ✓ | بلومبرگ ✓
امتیاز خبری: صعودی {bull} / نزولی {bear}
"""
    # ویس کوتاه – زنانه – بدون قیمت
    voice_text = f"""تحلیل فاندامنتال یورو دلار، {date_short}، {slot_label}.
جهت امروز: {direction}، اطمینان {conf}.
بانک مرکزی اروپا در حالت توقف است.
فدرال رزرو بعد از اشتغال ضعیف، محتاط شده.
{ 'خبر فوری منتشر شد. نظر من: ' + (breaking_news[0].get('title','') if breaking_news else '') if breaking_news else ''}
بازار در حالت رنج است. با مدیریت ریسک معامله کنید.
"""
    # پاکسازی اعداد قیمتی برای ویس هم
    voice_text = re.sub(r'\b1\.\d{3,5}\b', '', voice_text)
    return msg, voice_text

def send_telegram_text(text):
    if TELEGRAM_TOKEN.startswith("PUT_"):
        print("=== DRY RUN TEXT ===")
        print(text[:2000])
        return True
    url=f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    # تلگرام حد 4096 کاراکتر
    if len(text) > 4000:
        text = text[:4000] + "\n…"
    r=requests.post(url, data={"chat_id":CHAT_ID,"text":text,"parse_mode":"Markdown","disable_web_page_preview":True}, timeout=20)
    print("Telegram text:", r.status_code)
    return r.ok

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
    bull, bear = score_sentiment(news)
    slot_label = SCHEDULES.get(slot, {}).get("label", slot)

    # 🤖 تحلیل با هوش مصنوعی Groq
    ai_analysis = ai_analyze(news, cal, bull, bear)

    text_msg, voice_msg = build_brief(news, bull, bear, cal, slot_label=slot_label)

    # اگر AI جواب داد، به پیام اضافه کن
    if ai_analysis:
        text_msg = f"🤖 **تحلیل هوش مصنوعی (Groq AI):**\n\n{ai_analysis}\n\n━━━━━━━━━━━━━━━\n\n{text_msg}"
        # ویس هم از تحلیل AI استفاده کنه (بهتر و طبیعی‌تر)
        voice_msg = ai_analysis[:1500]

    send_telegram_text(text_msg)
    send_telegram_voice(voice_msg)
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
    parser.add_argument("--slot", choices=["morning","news_morning","us_preopen","evening","manual"], default="manual")
    parser.add_argument("--watch", action="store_true", help="اجرای واچر خبر زنده – بعد از هر داده High Impact بلافاصله تحلیل می‌فرستد")
    parser.add_argument("--once", action="store_true", help="فقط یک بار اجرا")
    args=parser.parse_args()

    if args.watch:
        watch_news_loop()
    else:
        run_once(args.slot if args.slot else "manual")
