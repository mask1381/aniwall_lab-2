"""
مسیر Zerochan (زمان‌بندی‌شده):
  اسلات‌های خالی ← گروه از انیمه‌ی کیسه ← جزئیات ← فیلتر ← غنی‌سازی
  ← انتخاب گروه (Pick Best Post10) ← کپشن ۳ لایه ← دانلود و ریسایز
  ← Scheduled Message ← ثبت در sent_ids
"""

import json
import random
import re
from urllib.parse import unquote
from zoneinfo import ZoneInfo

from aniwall import caption, config, enrich, images, net, pickers, scheduler

EXCLUDE_TAGS = {
    'female', 'male', 'fanart', 'pixiv', 'solo', 'official art', 'fanart from pixiv',
    'fanart from bilibili', 'bilibili', 'fanart from x (twitter)', 'x (twitter)',
    'mobile wallpaper', 'official art from pixiv',
}


def parse_zerochan_json(text: str, key: str):
    text = text or ""
    try:
        data = json.loads(text)
        if isinstance(data, dict):
            return data
    except ValueError:
        pass

    marker = f'"{key}"'
    idx = text.find(marker)
    if idx < 0:
        return None

    decoder = json.JSONDecoder()
    pos = text.rfind("{", 0, idx + 1)
    tries = 0
    while pos >= 0 and tries < 5:
        try:
            obj, _ = decoder.raw_decode(text[pos:])
            if isinstance(obj, dict) and key in obj:
                return obj
        except ValueError:
            pass
        pos = text.rfind("{", 0, pos)
        tries += 1
    return None


def _brief(text: str) -> str:
    text = text or ""
    head = " ".join(text[:200].split())
    tail = " ".join(text[-200:].split())
    return f"len={len(text)} head={head!r} tail={tail!r}"


def clean_franchise(encoded: str):
    try:
        return unquote(encoded.replace("+", " ")).strip() or None
    except Exception:
        return encoded.replace("+", " ").strip() or None


def pick_anime(state, log) -> str:
    pool_version = "|".join(config.ANIME_POOL) + "::" + repr(sorted(config.ANIME_WEIGHTS.items()))
    bag = state.get("animeBag") or []

    if not bag or state.get("animePoolVersion") != pool_version:
        weighted = []
        for a in config.ANIME_POOL:
            weighted.extend([a] * config.ANIME_WEIGHTS.get(a, 1))
        random.shuffle(weighted)
        bag = weighted
        state.set("animePoolVersion", pool_version)
        state.set("animeCycle", (state.get("animeCycle") or 0) + 1)
        log(f"کیسه‌ی انیمه از نو ساخته شد (دور {state.get('animeCycle')}، {len(bag)} آیتم)")

    anime = bag.pop(0)
    state.set("animeBag", bag)
    state.set("lastAnime", anime)
    state.set("remaining", len(bag))
    state.save()
    return anime


def fetch_candidates(anime: str, sent, log) -> list:
    r = net.request("GET", "https://www.zerochan.net/" + anime,
                    params=config.ZEROCHAN_LIST_PARAMS,
                    headers={"User-Agent": config.ZEROCHAN_LIST_UA,
                             "Accept": "application/json, text/plain, */*",
                             "Accept-Language": "en-US,en;q=0.9"},
                    accept_marker='"items"')

    data = parse_zerochan_json(r.text, "items")
    if data is None:
        raise RuntimeError(
            f"پاسخ لیست Zerochan JSON قابل‌خواندن نبود (status={r.status_code}) | {_brief(r.text)}")

    items = data.get("items") or []
    cands = [it for it in items
             if isinstance(it, dict) and it.get("id") is not None
             and f"zerochan:{it['id']}" not in sent]
    log(f"لیست Zerochan: {len(items)} آیتم، {len(cands)} مورد جدید (ارسال‌نشده)"
        f"{' [status ' + str(r.status_code) + ']' if r.status_code >= 400 else ''}")
    return cands


def adopt(p: dict, franchise) -> dict:
    raw_tags = p.get("tags") if isinstance(p.get("tags"), list) else []
    clean = [re.sub(r"\s+", "_", str(t)).lower() for t in raw_tags
             if str(t).lower().strip() not in EXCLUDE_TAGS]
    return {
        "id": f"zerochan:{p.get('id')}",
        "image_url_hq": p.get("full") or None,
        "image_url_std": p.get("large") or p.get("medium") or p.get("small") or "",
        "is_nsfw": False,
        "score": 0,
        "byte_size": (p.get("size") or None) if p.get("full") else None,
        "character": "unknown",
        "generalTags": clean,
        "tagsRaw": raw_tags,
        "zerochan_tags": raw_tags,
        "requestedAnime": franchise,
        "source": "zerochan",
        "author": "unknown",
        "branch": config.BRANCH,
        "category": "anime",
        "width": p.get("width"),
        "height": p.get("height"),
    }


def fetch_details(cands: list, franchise, log) -> list:
    cands = cands[:config.ZEROCHAN_DETAIL_MAX]

    def one(it):
        try:
            r = net.request("GET", f"https://www.zerochan.net/{it['id']}",
                            params={"json": 1},
                            headers={"User-Agent": config.ZEROCHAN_DETAIL_UA},
                            accept_marker='"id"')
            p = parse_zerochan_json(r.text, "id")
            if not isinstance(p, dict) or p.get("id") is None:
                raise ValueError(f"پاسخ قابل‌خواندن نبود (status={r.status_code}) | {_brief(r.text)}")
            return adopt(p, franchise)
        except Exception as e:
            raise RuntimeError(f"zerochan:{it.get('id')}: {e}") from e

    out = net.map_parallel(
        cands, one, workers=config.ZEROCHAN_DETAIL_WORKERS, log=log,
        label="جزئیات zerochan")
    log(f"جزئیات گرفته‌شده: {len(out)} از {len(cands)}")
    return out


def prepare_group(posts: list, log) -> list:
    def one(post):
        try:
            raw = net.request("GET", post["image_url_hq"],
                              headers={"User-Agent": config.ZEROCHAN_DETAIL_UA}).content
            big = (post.get("byte_size") or 0) > config.BIG_FILE_BYTES
            quality = config.IMG_JPEG_QUALITY if big else config.IMG_JPEG_QUALITY_SMALL
            jpg = images.to_jpeg(raw, max_side=config.IMG_MAX_SIDE_RESIZE, quality=quality)
            return post, jpg
        except Exception as e:
            raise RuntimeError(f"{post.get('id')}: {e}") from e

    return net.map_parallel(
        posts, one, workers=config.DOWNLOAD_WORKERS, log=log,
        label="آماده‌سازی")


def fetch_groups(sent, state, log) -> list:
    anime = pick_anime(state, log)
    franchise = clean_franchise(anime)
    log(f"انیمه: {franchise} (باقی‌مانده در کیسه: {state.get('remaining')})")

    cands = fetch_candidates(anime, sent, log)
    if not cands:
        log("آیتم جدیدی نیست.")
        return []

    adopted = fetch_details(cands, franchise, log)
    items = enrich.filter_items(adopted, log)
    items = [x for x in items if enrich.valid_image_urls(x)]
    log(f"بعد از بررسی URL تصاویر: {len(items)} آیتم")
    if not items:
        return []

    enriched = enrich.enrich_posts(items)
    groups = pickers.pick_zerochan_groups(enriched)
    log(f"گروه‌های انتخاب‌شده: {[g['groupSize'] for g in groups]}")
    return groups


def run(sent, state, dry_run, log, sched) -> int:
    slots = sched.plan(config.ZEROCHAN_SLOTS, "Zerochan")
    if not slots:
        log("هیچ اسلات خالی‌ای برای Zerochan نیست؛ پایان.")
        return 0

    tz = ZoneInfo(config.SCHED_TZ)
    budget = sched.free_space()
    log(f"{len(slots)} اسلات خالی | جای خالی صف برای این ران: {budget}")

    pending, fetches, posted, failures = [], 0, 0, 0

    for when in slots:
        if budget < 1 and not dry_run:
            log("جای خالی در صف نیست؛ اسلات‌های باقی‌مونده ران بعدی پر می‌شن.")
            break

        done = False
        for _try in range(3):
            while not pending and fetches < 5:
                fetches += 1
                try:
                    pending = fetch_groups(sent, state, log)
                except Exception as e:
                    log(f"⚠️ گرفتن گروه شکست خورد ({type(e).__name__}: {e})")
            if not pending:
                break
            g = pending.pop(0)
            posts = g["posts"]
            if len(posts) > budget and not dry_run:
                log(f"گروه {len(posts)} عکسی جا نمی‌شه (جای خالی {budget}) — پایان.")
                return posted if not failures else _fail(failures, posted)

            # تولید کپشن با سیستم ۳ لایه
            cap = caption.build_caption_zerochan(posts)
            log(f"اسلات {when.astimezone(tz):%m-%d %H:%M} | {len(posts)} عکس | "
                f"low_confidence={g['low_confidence']} | {cap}")
            log("   شناسه‌ها: " + ", ".join(p["id"] for p in posts))

            prepared = prepare_group(posts, log)
            if not prepared:
                log("⚠️ هیچ عکسی آماده نشد؛ گروه بعدی.")
                failures += 1
                continue
            photos = [(jpg, post["id"].replace(":", "_") + ".jpg") for post, jpg in prepared]

            if dry_run:
                sizes = ", ".join(f"{len(j) // 1024}KB" for _, j in prepared)
                log(f"   [dry-run] زمان‌بندی نمی‌شه — {len(prepared)} عکس آماده ({sizes})")
                budget -= len(photos)
                posted += 1
                done = True
                break

            try:
                sched.schedule_photos(when, photos, cap)
            except scheduler.QueueFull as e:
                log(f"صف پر شد ({e}) — پایان؛ ران بعدی ادامه می‌ده.")
                return posted if not failures else _fail(failures, posted)
            except Exception as e:
                log(f"❌ زمان‌بندی شکست خورد: {type(e).__name__}: {e}")
                failures += 1
                continue

            sent.add(*[p["id"] for p, _ in prepared])
            posted += 1
            budget = sched.free_space()
            log(f"✅ زمان‌بندی شد ({len(prepared)} عکس)")
            done = True
            break

        if not done:
            log("برای این اسلات گروهی پیدا نشد؛ پایان.")
            break

    if failures:
        _fail(failures, posted)
    return posted


def _fail(failures: int, posted: int):
    raise RuntimeError(f"{failures} گروه زمان‌بندی نشد ({posted} گروه موفق بود؛ جزئیات در لاگ بالا)")
