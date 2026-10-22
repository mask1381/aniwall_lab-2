"""
سیستم ۲: نگاشت مترادف‌ها، مخفف‌ها و شکل‌های کانونیکال (Synonyms & Canonical Engine)

این ماژول فرم‌های گوناگون یک مفهوم (مثل jjk، jujutsu kaisen، Jujutsu_Kaisen) را دریافت کرده
و به یک شکل واحد و هشتگ استاندارد کانونیکال نگاشت می‌کند.
"""

from __future__ import annotations

import json
import logging
import re
import unicodedata
from pathlib import Path
from typing import Dict, List, Optional
from urllib.parse import unquote

from aniwall import config

log = logging.getLogger(__name__)

_SYNONYMS: Dict[str, Dict[str, str]] | None = None


def norm_key(s) -> str:
    """نرمال‌سازی کلید متنی: حروف کوچک، بدون کاراکترهای ویژه، فاصله‌ها و زیرخط‌های پیوسته به یک _."""
    text = str(s or "").strip()
    try:
        text = unquote(text)
    except Exception:
        pass
    text = text.lower().replace(":", "").replace("+", "_").replace("-", "_")
    text = re.sub(r"[\s_]+", "_", text)
    return text.strip("_")


def compact_key(s) -> str:
    """حذف کامل فاصله‌ها و علائم برای مقایسه فشرده: 'jujutsu_kaisen' -> 'jujutsukaisen'."""
    k = norm_key(s)
    return re.sub(r"[^a-z0-9]", "", k)


def to_hashtag(name: str, max_len: int = 35) -> Optional[str]:
    """
    تبدیل متن به هشتگ معتبر با حروف بزرگ اول هر کلمه:
    'Genshin Impact' -> '#GenshinImpact'
    'Mushoku Tensei: Isekai...' -> '#MushokuTensei' (زیرعنوان بلند حذف می‌شود)
    'Re:Zero' -> '#ReZero' ، 'Honkai: Star Rail' -> '#HonkaiStarRail'
    (اگر بخش قبل از «:» خیلی کوتاه باشد یا تک‌کلمه با زیرعنوان کوتاه، بخش بعدی هم می‌آید)
    """
    if not name:
        return None
    # حذف پرانتز
    text = re.sub(r"\([^)]*\)", " ", str(name))

    # جداسازی عنوان و زیرعنوان
    head, _, tail = text.partition(":")
    head, tail = head.strip(), tail.strip()
    tail_words = tail.split()
    if tail_words:
        head_alnum = re.sub(r"[^A-Za-z0-9]", "", head)
        if len(head_alnum) < 4:
            # «Re:Zero Kara Hajimeru...» -> Re + Zero
            head = f"{head} {tail_words[0]}"
        elif len(head.split()) == 1 and len(tail_words) <= 2:
            # «Honkai: Star Rail» ، «Arknights: Endfield»
            head = f"{head} {tail}"
    text = head

    # یونیکد NFKD و حذف combining characters
    text = unicodedata.normalize("NFKD", text)
    text = "".join(c for c in text if not unicodedata.combining(c))

    # جداسازی کلمات و بزرگ کردن حرف اول
    parts = [w[:1].upper() + w[1:] for w in re.split(r"[^A-Za-z0-9]+", text) if w]
    joined = "".join(parts)

    if len(joined) < 2 or joined.isdigit():
        return None
    if max_len and len(joined) > max_len:
        return None
    return f"#{joined}"


def load_synonyms(path: Optional[Path] = None) -> Dict[str, Dict[str, str]]:
    """بارگذاری مترادف‌ها و نام‌های مستعار از فایل synonyms.json."""
    global _SYNONYMS
    path = path or config.SYNONYMS_PATH
    out: Dict[str, Dict[str, str]] = {"franchises": {}, "themes": {}}
    if path.exists():
        try:
            with path.open(encoding="utf-8") as f:
                data = json.load(f)
                for cat in ("franchises", "themes"):
                    for k, v in data.get(cat, {}).items():
                        # هم با norm_key و هم با compact_key نگاشت را ثبت می‌کنیم
                        nk = norm_key(k)
                        ck = compact_key(k)
                        if nk:
                            out[cat][nk] = v
                        if ck:
                            out[cat][ck] = v
        except Exception as e:
            log.warning("خطا در بارگذاری synonyms.json: %s", e)
    _SYNONYMS = out
    return _SYNONYMS


def get_synonyms() -> Dict[str, Dict[str, str]]:
    global _SYNONYMS
    if _SYNONYMS is None:
        _SYNONYMS = load_synonyms()
    return _SYNONYMS


def resolve_franchise_synonym(name: str) -> Optional[str]:
    """
    بررسی آیا نام یا مخفف داده‌شده متعلق به فرنچایز شناخته‌شده‌ای است:
    jjk -> Jujutsu Kaisen
    aot -> Attack on Titan
    """
    if not name:
        return None
    syn = get_synonyms().get("franchises", {})
    nk = norm_key(name)
    if nk in syn:
        return syn[nk]
    ck = compact_key(name)
    if ck in syn:
        return syn[ck]
    return None


def resolve_theme_synonym(tag: str) -> Optional[str]:
    """
    بررسی معادل موضوعی/تمی:
    school uniform -> Uniform
    serafuku -> Uniform
    kimono -> Kimono
    """
    if not tag:
        return None
    syn = get_synonyms().get("themes", {})
    nk = norm_key(tag)
    if nk in syn:
        return syn[nk]
    ck = compact_key(tag)
    if ck in syn:
        return syn[ck]
    return None
