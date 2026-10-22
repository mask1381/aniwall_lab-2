"""
سیستم ۳: تولید و فرمت‌بندی کپشن تلگرام (Telegram Caption Builder)

قالب نهایی هماهنگ:
  <blockquote>💠 #Franchise(s) #Character(s) #Theme</blockquote>
  [فقط HD] <blockquote><a href="لینک بات">📥 𝑫𝒐𝒘𝒏𝒍𝒐𝒂𝒅 𝑯𝑫 𝑸𝒖𝒂𝒍𝒊𝒕𝒚 ✨</a></blockquote>

- رعایت محدودیت ۱۰۲۴ کاراکتر تلگرام (فقط هشتگ‌ها کم می‌شن، بلاک لینک دست‌نخورده می‌مونه).
- امن‌سازی کاراکترهای ویژه HTML.
- فوتر THE LABS کار بات جداست و اینجا اضافه نمی‌شه.
"""

from __future__ import annotations

import html
import logging
from typing import List, Optional

from aniwall.tags import classify_post_tags

log = logging.getLogger(__name__)

CAPTION_LIMIT = 1024
FALLBACK_TAG = "#AnimeArt"
HD_LINK_TEXT = "📥 𝑫𝒐𝒘𝒏𝒍𝒐𝒂𝒅 𝑯𝑫 𝑸𝒖𝒂𝒍𝒊𝒕𝒚 ✨"


def _esc(s: str) -> str:
    return html.escape(str(s or ""), quote=False)


def build_hd_link_block(link: Optional[str]) -> str:
    """بلاک لینک دانلود HD؛ آدرس عیناً همونیه که بات داده."""
    if not link:
        return ""
    href = html.escape(str(link).strip(), quote=True)
    return f'<blockquote><a href="{href}">{HD_LINK_TEXT}</a></blockquote>'


def build_caption_from_hashtags(hashtags: List[str], badge: str = "💠", extra_block: str = "") -> str:
    """ساخت بلاک‌کوت نهایی بر اساس هشتگ‌های تولیدشده (+ بلوک اختیاری زیرش)."""
    tags = [h if h.startswith("#") else f"#{h}" for h in hashtags if h]
    if not tags:
        tags = [FALLBACK_TAG]

    def assemble(tg: List[str]) -> str:
        content = f"{badge} {' '.join(tg)}".strip()
        main = f"<blockquote>{_esc(content)}</blockquote>"
        return f"{main}\n\n{extra_block}" if extra_block else main

    caption = assemble(tags)
    # اگر بیش از حد طولانی شد، تگ‌های انتهایی را کم می‌کنیم (بلاک لینک ثابت می‌ماند)
    while len(caption) > CAPTION_LIMIT and len(tags) > 1:
        tags.pop()
        caption = assemble(tags)
    return caption


def build_caption_zerochan(items: List[dict]) -> str:
    """کپشن‌ساز برای مسیر Zerochan (یک گروه/آلبوم)."""
    res = classify_post_tags(items, source="zerochan", max_characters=3)
    return build_caption_from_hashtags(res["hashtags"], badge="💠")


def build_caption_wallhaven(items: List[dict], hd_link: Optional[str] = None) -> str:
    """کپشن‌ساز برای مسیر Wallhaven (۳ والپیپر یک اسلات) + لینک دانلود HD."""
    res = classify_post_tags(items, source="wallhaven", max_characters=3)
    return build_caption_from_hashtags(
        res["hashtags"], badge="💠", extra_block=build_hd_link_block(hd_link))


def build_caption_generic(items: List[dict], source: str = "") -> str:
    """کپشن‌ساز عمومی قابل استفاده در سایر مسیرها مانند offline_sender."""
    res = classify_post_tags(items, source=source, max_characters=3)
    return build_caption_from_hashtags(res["hashtags"], badge="💠")


def format_trace(res: dict) -> str:
    """گزارش شفاف برای حالت dry-run و لاگ."""
    lines = ["TAGS: " + " ".join(res.get("hashtags", []))]
    if res.get("franchises"):
        lines.append(f"  🏢 Franchises: {', '.join(res['franchises'])}")
    if res.get("characters"):
        lines.append(f"  👤 Characters: {', '.join(res['characters'])}")
    if res.get("theme_hashtag"):
        lines.append(f"  🎨 Theme: {res['theme_hashtag']}")
    return "\n".join(lines)
