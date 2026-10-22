"""
مسیر Wallhaven / HD (زمان‌بندی‌شده؛ اسلات‌های ثابت HD_SLOTS):
  جستجو ← حذف تکراری ← جزئیات ← فیلتر ← غنی‌سازی ← انتخاب (Pick Best Post9)
  ← دانلود و آماده‌سازی ← اسناد فوری و گروهی به مخزن + گرفتن لینک بات
  ← کپشن (هشتگ + لینک دانلود HD) ← زمان‌بندی عکس‌ها ← ثبت در sent_ids
"""

import os
import re
import time
from urllib.parse import urlparse
from zoneinfo import ZoneInfo

from aniwall import caption, config, enrich, images, net, pickers, scheduler

EXCLUDE_TAGS = {
    'anime', 'anime girls', 'anime boys', 'solo', 'group',
    'artwork', '2d', 'digital art', 'fan art',
    'original characters', 'video game girls',
}
DL_HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; AniWallLab/1.0)"}
DL_TIMEOUT = (15, 180)


def search_new_ids(sent, log) -> list:
    seen, fresh = set(), []
    pages_used = 0
    for page in range(1, config.WALLHAVEN_MAX_PAGES + 1):
        params = {**config.WALLHAVEN_SEARCH, "apikey": config.WALLHAVEN_API_KEY, "page": page}
        body = net.request("GET", "https://wallhaven.cc/api/v1/search", params=params).json()
        data = body.get("data") or []
        pages_used = page
        if not data:
            break
        for d in data:
            wid = str(d["id"]) if d.get("id") else ""
            if not wid or wid in seen:
                continue
            seen.add(wid)
            if f"wallhaven:{wid}" not in sent:
                fresh.append(wid)
                if len(fresh) >= config.WALLHAVEN_MAX_ITEMS:
                    break
        if len(fresh) >= config.WALLHAVEN_MAX_ITEMS:
            break
        last_page = (body.get("meta") or {}).get("last_page")
        if last_page and page >= int(last_page):
            break
        if page < config.WALLHAVEN_MAX_PAGES:
            time.sleep(config.WALLHAVEN_PAGE_INTERVAL)

    log(f"جستجوی Wallhaven: {pages_used} صفحه، {len(seen)} نتیجه، "
        f"{len(fresh)} مورد جدید → سقف {config.WALLHAVEN_MAX_ITEMS}")
    return fresh[:config.WALLHAVEN_MAX_ITEMS]


def _telegram_dims(w, h):
    if w > 0 and h > 0:
        scale = 1.0
        if w + h > config.TG_MAX_SUM:
            scale = min(scale, config.TG_MAX_SUM / (w + h))
        if w * scale > config.TG_MAX_SIDE:
            scale = min(scale, config.TG_MAX_SIDE / w)
        if h * scale > config.TG_MAX_SIDE:
            scale = min(scale, config.TG_MAX_SIDE / h)
        return round(w * scale), round(h * scale)
    return w, h


def adopt(p: dict) -> dict:
    raw_tags = p.get("tags") if isinstance(p.get("tags"), list) else []
    clean = []
    for t in raw_tags:
        name = t.get("name") if isinstance(t, dict) else None
        if not name or name.lower().strip() in EXCLUDE_TAGS:
            continue
        clean.append(re.sub(r"\s+", "_", name).lower())

    width, height = _telegram_dims(p.get("dimension_x") or 0, p.get("dimension_y") or 0)
    return {
        "id": f"wallhaven:{p.get('id') or ''}",
        "id01": str(p.get("id") or ""),
        "image_url_hq": p.get("path") or None,
        "image_url_std": p.get("path") or None,
        "is_nsfw": p.get("purity") != "sfw",
        "score": p.get("favorites") or 0,
        "byte_size": p.get("file_size") or None,
        "character": "unknown",
        "generalTags": clean,
        "tagsRaw": raw_tags,
        "source": "wallhaven",
        "author": "unknown",
        "branch": config.BRANCH,
        "category": "general_anime",
        "views": p.get("views") or 0,
        "resolution": p.get("resolution") or None,
        "width": width,
        "height": height,
        "ratio": p.get("ratio") or None,
        "purity": p.get("purity") or None,
        "source_url": p.get("source") or None,
    }


def fetch_details(ids: list, log) -> list:
    def one(wid):
        try:
            body = net.request("GET", f"https://wallhaven.cc/api/v1/w/{wid}",
                               params={"apikey": config.WALLHAVEN_API_KEY}).json()
            data = body.get("data")
            if not isinstance(data, dict) or not data.get("id"):
                raise ValueError("پاسخ بدون data")
            return adopt(data)
        except Exception as e:
            raise RuntimeError(f"wallhaven:{wid}: {e}") from e

    out = net.map_parallel(
        ids, one, workers=config.WALLHAVEN_DETAIL_WORKERS, log=log,
        label="جزئیات wallhaven")
    log(f"جزئیات گرفته‌شده: {len(out)} از {len(ids)}")
    return out


def _ext_of(url: str) -> str:
    ext = os.path.splitext(urlparse(url).path)[1].lstrip(".").lower()
    return ext if ext in ("jpg", "jpeg", "png", "webp") else "jpg"


def prepare(posts: list, log):
    def one(post):
        try:
            raw = net.request("GET", post["image_url_hq"], headers=DL_HEADERS, timeout=DL_TIMEOUT).content
        except Exception as e:
            log(f"⚠️ دانلود {post['id']} شکست خورد: {e}")
            return None
        try:
            doc_bytes, doc_ext = images.fit_document(raw, _ext_of(post["image_url_hq"]))
            photo_bytes = images.fit_photo(raw)
            return {
                "post": post,
                "photo": photo_bytes,
                "doc": (doc_bytes, f"{config.BRANCH}_{post['id01']}.{doc_ext}"),
            }
        except Exception as e:
            log(f"❌ رد دائمی {post['id']} ({type(e).__name__}: {e})")
            return post["id"]

    results = net.map_parallel(posts, one, workers=config.DOWNLOAD_WORKERS, log=log, label="دانلود wallhaven")
    ready = [r for r in results if isinstance(r, dict)]
    skipped = [r for r in results if isinstance(r, str)]

    if len(ready) != len(posts):
        return [], skipped
    return ready, skipped


def fill_slot(sched, pool, when, sent, dry_run, log) -> tuple[str, list]:
    tz = ZoneInfo(config.SCHED_TZ)
    while pool:
        picked = pickers.pick_wallhaven(pool)
        if not picked:
            return "empty", pool
        used = {p["id"] for p in picked}
        pool = [x for x in pool if x["id"] not in used]
        log(f"اسلات {when.astimezone(tz):%m-%d %H:%M} | انتخاب‌شده‌ها: {', '.join(p['id'] for p in picked)}")

        ready, skipped = prepare(picked, log)
        if skipped:
            sent.add(*skipped)
        if not ready:
            log("هیچ فایلی آماده نشد؛ دسته‌ی بعدی امتحان می‌شه.")
            continue

        posts = [e["post"] for e in ready]
        all_ids = [p["id"] for p in posts]
        photos = [(e["photo"], f"{config.BRANCH}_{e['post']['id01']}.jpg") for e in ready]
        docs = [e["doc"] for e in ready]

        if dry_run:
            fake = sched.send_documents_to_storage(docs)   # در dry-run چیزی نمی‌فرسته
            cap = caption.build_caption_wallhaven(posts, hd_link=fake["link"])
            log(f"کپشن (نمونه با لینک فرضی): {cap}")
            log("   [dry-run] عکس‌ها: " + ", ".join(f"{len(b) // 1024}KB" for b, _ in photos))
            log("   [dry-run] اسناد مخزن: " + ", ".join(f"{n} ({len(b) // 1024}KB)" for b, n in docs))
            return "ok", pool

        # قبل از فرستادن سند به مخزن مطمئن می‌شیم برای عکس‌ها جا هست (تا سند یتیم نمونه)
        if not sched.room_for(len(photos)):
            log(f"صف پر است؛ جا برای {len(photos)} عکس نیست.")
            return "full", pool

        # ۱) اسناد: فوری و گروهی به مخزن ← لینک بات (عیناً)
        try:
            stored = sched.send_documents_to_storage(docs)
        except scheduler.StorageLinkError as e:
            raise RuntimeError(f"گرفتن لینک مخزن شکست خورد: {e}")
        rollback_ids = list(stored["doc_ids"]) + ([stored["link_msg_id"]] if stored["link_msg_id"] else [])

        # ۲) کپشن با لینک
        cap = caption.build_caption_wallhaven(posts, hd_link=stored["link"])
        log(f"کپشن: {cap}")

        # ۳) عکس‌ها زمان‌بندی؛ اگه نشد، اسناد (و پیام لینک) مخزن برگردونده می‌شن
        try:
            sched.schedule_photos(when, photos, cap)
        except Exception as e:
            sched.delete_storage(rollback_ids)
            if isinstance(e, scheduler.QueueFull):
                log(f"صف پر شد ({e}); اسناد مخزن برگشت داده شد.")
                return "full", pool
            raise RuntimeError(f"زمان‌بندی عکس‌ها شکست خورد: {type(e).__name__}: {e}")

        sent.add(*all_ids)
        log(f"✅ اسلات زمان‌بندی شد ({len(photos)} عکس + {len(docs)} سند در مخزن)")
        return "ok", pool
    return "empty", pool


def run(sent, state, dry_run, log, sched) -> int:
    slots = sched.plan(config.HD_SLOTS, "HD")
    if not slots:
        log("هیچ اسلات خالی‌ای برای HD نیست؛ پایان.")
        return 0

    # اسناد دیگه توی صف Scheduled نمیرن؛ هر اسلات فقط عکس‌ها رو مصرف می‌کنه
    need = config.WALLHAVEN_PICK_COUNT
    budget = sched.free_space()
    log(f"{len(slots)} اسلات خالی | جای خالی صف برای این ران: {budget} (هر اسلات {need} پیام)")
    if budget < need and not dry_run:
        log("جای خالی کافی نیست؛ ران بعدی.")
        return 0

    ids = search_new_ids(sent, log)
    if not ids:
        log("آیتم جدیدی نیست؛ پایان.")
        return 0

    adopted = fetch_details(ids, log)
    items = enrich.filter_items(adopted, log)
    items = [x for x in items if enrich.valid_image_urls(x)]
    log(f"بعد از بررسی URL تصاویر: {len(items)} آیتم")
    if not items:
        return 0

    pool = enrich.enrich_posts(items)
    posted = 0
    for when in slots:
        if budget < need and not dry_run:
            log("جای خالی کافی نیست؛ اسلات‌های باقی‌مونده ران بعدی پر می‌شن.")
            break
        status, pool = fill_slot(sched, pool, when, sent, dry_run, log)
        if status != "ok":
            break
        posted += 1
        budget = budget - need if dry_run else sched.free_space()
    return posted
