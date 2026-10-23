"""
تنظیمات مرکزی AniWall Lab.

⚠️ توکن‌ها عمداً داخل کد هاردکد شدن — ریپو حتماً باید PRIVATE باشه.
"""

import os
import re
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

# ─────────────────────────────────────────
# مسیرها
# ─────────────────────────────────────────
ANIWALL_DIR = Path(__file__).resolve().parent
BASE_DIR = ANIWALL_DIR.parent
DATA_DIR = BASE_DIR / "data"

SENT_IDS_PATH = DATA_DIR / "sent_ids.json"          # معادل جدول arts
STATE_PATH = DATA_DIR / "state.json"                # معادل static data (کیسه‌ی انیمه)
DICTIONARY_PATH = DATA_DIR / "character_dictionary.csv"
CONTENT_TAGS_PATH = DATA_DIR / "content_tags.csv"
DROP_TAGS_PATH = DATA_DIR / "drop_tags.csv"
ADULT_TAGS_PATH = DATA_DIR / "adult_tags.csv"
FILTERS_PATH = DATA_DIR / "hashtag_filters.csv"
TAG_STATS_PATH = DATA_DIR / "tag_stats.csv"
SYNONYMS_PATH = DATA_DIR / "synonyms.json"

BRANCH = "aniwall_lab"

# ─────────────────────────────────────────
# تلگرام (بات ارسال آلبوم/عکس/سند)
# ─────────────────────────────────────────
TG_BOT_TOKEN = os.getenv("TG_BOT_TOKEN", "").strip()
TG_CHAT_ID = os.getenv("TG_CHAT_ID", "").strip()

# ─────────────────────────────────────────
# Wallhaven
# ─────────────────────────────────────────
WALLHAVEN_API_KEY = os.getenv("WALLHAVEN_API_KEY", "").strip()
WALLHAVEN_SEARCH = {
    "q": "anime",
    "categories": "010",
    "purity": "100",
    "sorting": "favorites",
    "order": "desc",
    "atleast": "1920x1080",
}
WALLHAVEN_MAX_PAGES = 15
WALLHAVEN_PAGE_INTERVAL = 0.35       # ثانیه بین صفحه‌ها (فقط اگر هنوز آیتم کم باشد)
WALLHAVEN_MAX_ITEMS = 45             # سقف بعد از حذف تکراری (نود Limit2)
WALLHAVEN_DETAIL_WORKERS = 6         # درخواست موازی جزئیات
WALLHAVEN_PICK_COUNT = 3             # تعداد عکس انتخابی (Pick Best Post9)

WALLHAVEN_TZ = "Asia/Tehran"
WALLHAVEN_HOURS = (4, 12)            # ۴ صبح و ۱۲ ظهر
WALLHAVEN_WINDOW_MINUTES = 15

# ───── زمان‌بندی (Scheduled Messages) ─────
SCHED_TZ = "Asia/Tehran"
SCHED_LEAD_MIN = 90            # اولین پست حداقل این‌قدر بعد از اجرا
SCHED_HORIZON_H = 24           # تا چند ساعت جلو پر کنه
SCHED_QUEUE_SAFE_CAP = 95      # سقف ایمن کل صف (سقف تلگرام ۱۰۰)
SCHED_RUN_CAP = 50             # حداکثر پیام هر ران
SCHED_MIN_GAP_MIN = 30         # حداقل فاصله از هر پیام دیگر
SCHED_SAME_SLOT_TOL_MIN = 5
SCHED_SHIFT_STEP_MIN = 5
SCHED_SHIFT_MAX_MIN = 15
# ───── مخزن اسناد HD (storage waifu lab) ─────
STORAGE_CHAT_ID = os.getenv("STORAGE_CHAT_ID", "").strip()
STORAGE_LINK_TIMEOUT = 90               # حداکثر ثانیه‌ی انتظار برای لینکی که بات میذاره
STORAGE_LINK_POLL = 3                   # فاصله‌ی چک کردن (ثانیه)
STORAGE_LINK_RE = re.compile(
    r"https?://t\.me/littlemask02_bot\?start=[A-Za-z0-9_\-]+", re.I)
HD_SLOTS = ((4, 0), (12, 0))
ZEROCHAN_SLOTS = tuple((h, 30) for h in range(0, 24, 3))


def wallhaven_now() -> datetime:
    return datetime.now(ZoneInfo(WALLHAVEN_TZ))


def in_wallhaven_window(now: datetime | None = None) -> bool:
    """True اگر الان حوالی ۴:۰۰ یا ۱۲:۰۰ (تهران) با حاشیه ۱۵ دقیقه باشد."""
    now = now or wallhaven_now()
    minutes = now.hour * 60 + now.minute
    return any(abs(minutes - hour * 60) <= WALLHAVEN_WINDOW_MINUTES for hour in WALLHAVEN_HOURS)


# ─────────────────────────────────────────
# Zerochan
# ─────────────────────────────────────────
ZEROCHAN_LIST_UA = "ytpost_GWS_channel - HimedereRyu585"
ZEROCHAN_DETAIL_UA = "HimedereRyu585"
ZEROCHAN_LIST_PARAMS = {"l": 100, "s": "fav", "json": 1}
ZEROCHAN_DETAIL_MAX = 36             # جزئیات همهٔ لیست لازم نیست؛ برای ۲ آلبوم کافی است
ZEROCHAN_DETAIL_WORKERS = 4
ZEROCHAN_MAX_ALBUM = 8               # سقف تعداد عکس هر آلبوم

# ─────────────────────────────────────────
# تصویر / تلگرام
# ─────────────────────────────────────────
IMG_MAX_SIDE_RESIZE = 1920           # ریسایز onlyIfLarger برای Zerochan
IMG_JPEG_QUALITY = 85
BIG_FILE_BYTES = 5_000_000           # نود If10
TG_MAX_SUM = 9800                    # مجموع طول+عرض مجاز تلگرام (Wallhaven)
TG_MAX_SIDE = 4000
TG_DOC_MAX_BYTES = 49_000_000        # سقف آپلود document

# ─────────────────────────────────────────
# درخواست‌های شبکه: retry با فاصله (آی‌پی GitHub ممکنه rate-limit بشه)
# ─────────────────────────────────────────
HTTP_TIMEOUT = 25
HTTP_RETRIES = 3
HTTP_BACKOFF = 2.0                   # ثانیه؛ بین تلاش‌ها ضرب در شماره‌ی تلاش
DOWNLOAD_WORKERS = 4                 # دانلود موازی فایل تصویر

# ─────────────────────────────────────────
# چرخش انیمه‌ها (Zerochan) — عیناً از نود "aniwall tag"
# ─────────────────────────────────────────
ANIME_WEIGHTS = {
    "One+Piece": 5, "Attack+on+Titan": 5, "Jujutsu+Kaisen": 5, "Kimetsu+no+Yaiba": 5,
    "Chainsaw+Man": 5, "NARUTO": 5, "Death+Note": 5, "Solo+Leveling": 5,
    "Sword+Art+Online": 5, "Boku+no+Hero+Academia": 5,

    "Bleach": 2, "Hunter+x+Hunter": 2, "One+Punch+Man": 2, "Tokyo+Ghoul": 2,
    "CODE+GEASS%3A+Hangyaku+no+Lelouch": 2, "JoJo+no+Kimyou+na+Bouken": 2,
    "Fairy+Tail": 2, "Haikyuu%21%21": 2, "Blue+Lock": 2, "Spy+×+Family": 2,
    "Oshi+no+Ko": 2, "Sousou+no+Frieren": 2, "Re%3AZero+Kara+Hajimeru+Isekai+Seikatsu": 2,
    "Fullmetal+Alchemist": 2, "Dragon+Ball": 2, "Mob+Psycho+100": 2, "Black+Clover": 2,
}

ANIME_POOL = [
    "Bleach", "One+Piece", "Jujutsu+Kaisen", "Kimetsu+no+Yaiba", "Attack+on+Titan",
    "Boku+no+Hero+Academia", "Hunter+x+Hunter", "Fullmetal+Alchemist", "Black+Clover",
    "Chainsaw+Man", "One+Punch+Man", "Mob+Psycho+100", "Tokyo+Ghoul", "Death+Note",
    "CODE+GEASS%3A+Hangyaku+no+Lelouch", "JoJo+no+Kimyou+na+Bouken", "Dragon+Ball",
    "Fairy+Tail", "Haikyuu%21%21", "Blue+Lock", "Bungou+Stray+Dogs", "Vinland+Saga",
    "Sousou+no+Frieren", "Solo+Leveling", "Spy+×+Family", "Oshi+no+Ko", "Bocchi+the+Rock%21",
    "Kaguya+sama+wa+Kokurasetai", "Violet+Evergarden", "Shigatsu+wa+Kimi+no+Uso", "Toradora%21",
    "Re%3AZero+Kara+Hajimeru+Isekai+Seikatsu", "Sword+Art+Online", "Made+in+Abyss",
    "Fate%2Fstay+night", "Neon+Genesis+Evangelion", "Cowboy+Bebop",
    "Mushoku+Tensei%3A+Isekai+Ittara+Honki+Dasu", "Kage+no+Jitsuryokusha+ni+Naritakute%21",
    "Kusuriya+no+Hitorigoto", "Dungeon+Meshi", "Noragami", "Kakegurui", "Gintama", "NARUTO",
    "Mato+Seihei+no+Slave",
]

# ─────────────────────────────────────────
# فیلتر برچسب‌ها — عیناً از نود "filter" (فقط برنچ aniwall_lab)
# ─────────────────────────────────────────
def norm_tag(x) -> str:
    return re.sub(r"[\s_:.\-]+", "", str(x if x is not None else "").lower().strip())


def _mk_set(words) -> frozenset:
    return frozenset(norm_tag(w) for w in words)


FILTER_DEFAULT = _mk_set([
    'pussy', 'penis', 'testicles', 'anus', 'nipples', 'areolae', 'sex', 'vaginal', 'anal', 'oral',
    'Group', ' Text: Sample', 'Text: Brand Name', 'pussy', 'Ecchi',
    'fellatio', 'cunnilingus', 'masturbation', 'fingering', 'penetration', 'cum', 'ejaculation',
    'watermarked', 'Anime poster',
    'precum', 'bukkake', 'group_sex', 'creampie', 'rape', 'sex_toy', 'dildo', 'vibrator',
    'hetero_sex', 'yuri_sex', 'yaoi_sex', 'pubic_hair', 'spread_pussy',
    'spread_legs_and_pussy_visible', 'nude', 'completely_nude', 'topless', 'bottomless',
    'Official_Art', 'tagme',
    'text', 'comic', 'furry', 'furry_female', 'cross-over', 'bdsm',
    'genshinimpact', 'arknights', 'honkaistarrail', 'starrail', 'wutheringwaves',
    'zenlesszonezero', 'honkaiimpact3rd', 'houkai3rd', 'houkai3', 'hoyoverse', 'mihoyo',
    'speech_bubble', 'thought_bubble', 'blush', 'artist_name', 'english_text',
])

FILTER_WALLHAVEN = _mk_set([
    'pussy', 'penis', 'testicles', 'anus', 'nipples', 'areolae', 'sex', 'vaginal', 'anal', 'oral',
    'Group', ' Text: Sample', 'Text: Brand Name', 'pussy',
    'fellatio', 'cunnilingus', 'masturbation', 'fingering', 'penetration', 'cum', 'ejaculation',
    'photoshopped', 'Anime poster',
    'precum', 'bukkake', 'group_sex', 'creampie', 'rape', 'sex_toy', 'dildo', 'vibrator',
    'hetero_sex', 'yuri_sex', 'yaoi_sex', 'pubic_hair', 'spread_pussy',
    'spread_legs_and_pussy_visible', 'nude', 'completely_nude', 'topless', 'bottomless',
    'Official_Art', 'tagme',
    'comic', 'furry', 'furry_female', 'cross-over', 'bdsm',
    'genshinimpact', 'arknights', 'honkaistarrail', 'starrail', 'wutheringwaves',
    'zenlesszonezero', 'honkaiimpact3rd', 'houkai3rd', 'houkai3', 'hoyoverse', 'mihoyo',
    'speech_bubble', 'thought_bubble', 'blush', 'english_text',
])

FILTERS_BY_SOURCE = {
    "wallhaven": FILTER_WALLHAVEN,
}
IMG_JPEG_QUALITY_SMALL = 90
GROUP_GAP_SECONDS = 3


def pick_filter_set(source: str) -> frozenset:
    return FILTERS_BY_SOURCE.get(norm_tag(source), FILTER_DEFAULT)

# ═══════════════════════════════════════════════════════════
# رفتار «انسانی» + سقف‌ها — همه با env هم قابل تغییر
# بازه‌ها به شکل "2-5" (ثانیه) یا یک عدد؛ بعداً می‌نویسیم که مقدار قبلی‌ها رو override می‌کنه
# ═══════════════════════════════════════════════════════════
def _env_bool(name, default):
    v = os.getenv(name)
    return default if v is None or v.strip() == "" else v.strip().lower() in ("1", "true", "yes", "on")


def _env_int(name, default):
    try:
        return int(os.getenv(name, "").strip())
    except ValueError:
        return default


def _env_range(name, default):
    raw = os.getenv(name, "").strip()
    if not raw:
        return default
    try:
        parts = [float(x) for x in raw.replace(",", "-").split("-") if x.strip()]
        if len(parts) == 1:
            return (parts[0], parts[0])
        return (min(parts[:2]), max(parts[:2]))
    except ValueError:
        return default


HUMAN_PACING = _env_bool("HUMAN_PACING", True)            # False = همه‌ی مکث‌ها خاموش

# Zerochan
ZEROCHAN_PRE_DELAY = _env_range("ZEROCHAN_PRE_DELAY", (3.0, 8.0))                # قبل از درخواست لیست
ZEROCHAN_BETWEEN_ANIME_DELAY = _env_range("ZEROCHAN_BETWEEN_ANIME_DELAY", (8.0, 20.0))
ZEROCHAN_DETAIL_DELAY = _env_range("ZEROCHAN_DETAIL_DELAY", (2.0, 5.0))          # بین جزئیات
ZEROCHAN_DOWNLOAD_DELAY = _env_range("ZEROCHAN_DOWNLOAD_DELAY", (1.0, 2.5))      # بین دانلود عکس‌ها
ZEROCHAN_DETAIL_MAX = _env_int("ZEROCHAN_DETAIL_MAX", 14)
ZEROCHAN_DETAIL_WORKERS = _env_int("ZEROCHAN_DETAIL_WORKERS", 1)                 # 1 = پشت‌سرهم
ZEROCHAN_DOWNLOAD_WORKERS = _env_int("ZEROCHAN_DOWNLOAD_WORKERS", 1)
ZEROCHAN_BLOCK_STATUSES = (503, 429, 403)                # نشانه‌ی بلاک/محدودیت
ZEROCHAN_BLOCK_WAIT = _env_range("ZEROCHAN_BLOCK_WAIT", (20.0, 40.0))            # صبر قبل از تلاش دوباره
ZEROCHAN_BLOCK_RETRIES = _env_int("ZEROCHAN_BLOCK_RETRIES", 1)                   # بعدش قطع
ZEROCHAN_MAX_ANIME_FAILS = _env_int("ZEROCHAN_MAX_ANIME_FAILS", 2)               # خطای غیر بلاک: بعد از این‌قدر انیمه کنار می‌ره
ZEROCHAN_BLOCK_IS_ERROR = _env_bool("ZEROCHAN_BLOCK_IS_ERROR", True)             # بلاک + هیچ پستی = ران خطادار (لاگ می‌ره گروه)

# Wallhaven
WALLHAVEN_DETAIL_WORKERS = _env_int("WALLHAVEN_DETAIL_WORKERS", 3)
WALLHAVEN_DETAIL_DELAY = _env_range("WALLHAVEN_DETAIL_DELAY", (0.3, 0.9))
WALLHAVEN_ROUND_DELAY = _env_range("WALLHAVEN_ROUND_DELAY", (1.0, 3.0))
WALLHAVEN_MIN_ITEMS = _env_int("WALLHAVEN_MIN_ITEMS", 9)       # حداقل آیتم سالم قبل از انتخاب
WALLHAVEN_MAX_ROUNDS = _env_int("WALLHAVEN_MAX_ROUNDS", 3)     # حداکثر دور جستجو+فیلتر
