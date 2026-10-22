"""
سیستم ۱: انبارش و آمارگیری برچسب‌های خام (Raw Stats Engine)

هر تگی که از منابع (Wallhaven، Zerochan، Instagram و...) می‌آید در tag_stats.csv ثبت و شمارش می‌شود.
این داده‌ها اساس یادگیری و گسترش هشتگ‌ها و تم‌ها توسط انسان یا AI در آینده هستند.
"""

from __future__ import annotations

import csv
import logging
from datetime import date
from pathlib import Path
from typing import Dict, List, Optional

from aniwall import config

log = logging.getLogger(__name__)

STATS_FIELDS = [
    "tag",
    "translation",
    "count",
    "nsfw_count",
    "status",
    "used_count",
    "last_seen",
    "source",
]

_STATS_STORE: Dict[str, dict] | None = None


def load_stats(path: Optional[Path] = None) -> Dict[str, dict]:
    """بارگذاری آمار برچسب‌ها از فایل CSV."""
    global _STATS_STORE
    path = path or config.TAG_STATS_PATH
    data: Dict[str, dict] = {}
    if path.exists():
        try:
            with path.open(encoding="utf-8-sig", newline="") as f:
                reader = csv.DictReader(f)
                for row in reader:
                    tag = (row.get("tag") or "").strip()
                    if not tag:
                        continue
                    data[tag] = {
                        "tag": tag,
                        "translation": row.get("translation") or "",
                        "count": int(row.get("count") or 0),
                        "nsfw_count": int(row.get("nsfw_count") or 0),
                        "status": row.get("status") or "",
                        "used_count": int(row.get("used_count") or 0),
                        "last_seen": row.get("last_seen") or "",
                        "source": row.get("source") or "",
                    }
        except Exception as e:
            log.warning("خطا در خواندن فایل tag_stats (%s): %s", path, e)
    _STATS_STORE = data
    return _STATS_STORE


def get_stats() -> Dict[str, dict]:
    global _STATS_STORE
    if _STATS_STORE is None:
        _STATS_STORE = load_stats()
    return _STATS_STORE


def record_tag_sightings(
    tags: List[str],
    source: str = "",
    is_nsfw: bool = False,
    decisions: Optional[List[dict]] = None,
    path: Optional[Path] = None,
) -> None:
    """
    ثبت دسته‌ای تگ‌های دیده‌شده در یک پست / آلبوم.
    decisions: لیست دیکشنری‌های خروجی دسته‌بندی با کلیدهای:
      - tag: تگ خام
      - status: character / franchise / theme / pass / drop / adult / skip
      - used: True اگر در هشتگ‌های نهایی کپشن منتشر شد
    """
    stats = get_stats()
    today_str = date.today().isoformat()
    dec_map = {d["tag"].strip().lower(): d for d in (decisions or []) if "tag" in d}

    for t in tags:
        t_clean = str(t or "").strip()
        if not t_clean or len(t_clean) < 2:
            continue
        key = t_clean.lower()
        rec = stats.setdefault(
            t_clean,
            {
                "tag": t_clean,
                "translation": "",
                "count": 0,
                "nsfw_count": 0,
                "status": "",
                "used_count": 0,
                "last_seen": today_str,
                "source": source,
            },
        )
        rec["count"] += 1
        if is_nsfw:
            rec["nsfw_count"] += 1
        rec["last_seen"] = today_str
        if source and not rec.get("source"):
            rec["source"] = source

        dec = dec_map.get(key)
        if dec:
            if dec.get("status"):
                rec["status"] = dec["status"]
            if dec.get("used"):
                rec["used_count"] += 1

    save_stats(path)


def save_stats(path: Optional[Path] = None) -> None:
    """ذخیره تغییرات در فایل tag_stats.csv."""
    global _STATS_STORE
    if _STATS_STORE is None:
        return
    path = path or config.TAG_STATS_PATH
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        # مرتب‌سازی بر اساس بیشترین تکرار
        sorted_rows = sorted(_STATS_STORE.values(), key=lambda r: -r["count"])
        with path.open("w", encoding="utf-8-sig", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=STATS_FIELDS)
            writer.writeheader()
            writer.writerows(sorted_rows)
    except Exception as e:
        log.warning("خطا در نوشتن tag_stats.csv: %s", e)
