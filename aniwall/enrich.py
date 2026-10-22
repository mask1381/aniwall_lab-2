"""
موتور دیکشنری هوشمند کاراکتر و فرنچایز + پالایش ورودی‌ها.

- خواندن داده‌های character_dictionary.csv با ساخت ایندکس سریع.
- پشتیبانی از ترتیب برعکس کلمات (Marin Kitagawa == Kitagawa Marin).
- تفکیک الگوهای پرانتزی مثل Name (Work).
- استخراج مجموع دیده شدن‌های فرنچایز (franchise_total) برای رتبه‌بندی اعتبارسنجی.
- توابع پالایش اولیه filter_items و valid_image_urls و enrich_posts.
"""

from __future__ import annotations

import csv
import logging
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

from aniwall import config
from aniwall.synonyms import compact_key, norm_key, resolve_franchise_synonym

log = logging.getLogger(__name__)

MIN_SEEN_SINGLE = 3
MIN_SEEN_WEAK_NS = 2
SINGLE_FRANCHISE_MIN = 150
SINGLE_CHAR_MIN_SEEN = 100

DENY_WORDS = {
    "shade", "shadow", "pudding", "chair", "flower", "flowers", "smile", "star", "stars",
    "ribbon", "dress", "skirt", "bell", "heart", "cake", "feet", "wings", "halo", "gem",
    "ring", "boots", "hat", "jacket", "necklace", "earrings", "gloves", "tights", "fruit",
    "navel", "bird", "girl", "girls", "woman", "female", "original", "lady", "person",
    "character", "solo", "boy", "boys", "unknown", "illust", "illustration", "art", "artist",
    "anime", "anime_girl", "anime_girls", "anime_boy", "anime_boys", "wallpaper",
    "desktop_wallpaper", "mobile_wallpaper", "highres", "official_art", "clothes", "clothing",
    "collar", "symbol", "hair", "long_hair", "short_hair", "eyes", "blue_eyes", "red_eyes",
    "fanart", "artwork", "tagme", "sample", "general", "parody", "cross_over", "crossover",
}

PAREN_JUNK = re.compile(r"cosplay|meme|outfit|alternate|default|wallpaper|character|series|anime", re.I)
NULL_VALUES = {"", "null", "none", "unknown", "n/a", "nan"}
IMG_EXT = re.compile(r"\.(jpg|jpeg|png|webp)($|\?)", re.I)

_MAPS: Tuple[dict, list] | None = None


def clean_val(v) -> str:
    s = str(v if v is not None else "").strip()
    return "" if s.lower() in NULL_VALUES else s


def split_paren(norm: str) -> Optional[Dict[str, str]]:
    """'rem_(re_zero)' -> {'head': 'rem', 'inside': 're_zero'}"""
    i = norm.find("_(")
    if i < 0 or not norm.endswith(")"):
        return None
    inside = re.sub(r"[()]", "_", norm[i + 2 : -1])
    inside = re.sub(r"_+", "_", inside).strip("_")
    return {"head": norm[:i], "inside": inside}


def pretty_name(head: str) -> str:
    """'rem' -> 'Rem', 'gojo_satoru' -> 'Gojo Satoru'"""
    return " ".join(w[:1].upper() + w[1:] for w in head.split("_") if w)


def _sorted_key(k: str) -> Optional[str]:
    tokens = [t for t in k.split("_") if t]
    if len(tokens) < 2 or "(" in k:
        return None
    return "~" + "_".join(sorted(tokens))


def _compact_forms(k: str) -> List[str]:
    tokens = [t for t in k.split("_") if t]
    if len(tokens) < 2 or "(" in k:
        return []
    forms = ["".join(tokens)]
    if len(tokens) == 2:
        forms.append(tokens[1] + tokens[0])
    return [f for f in forms if len(f) >= 6]


def build_maps(rows: List[dict]) -> dict:
    maps: Dict[str, dict] = {
        "character": {},
        "franchise": {},
        "studio": {},
        "source": {},
        "char_by_cat": {},
        "franchise_total": {},
    }

    def put(store: dict, key: str, original: str, row: dict, seen: int):
        prev = store.get(key)
        if not prev or prev["seen"] < seen:
            store[key] = {"original": original, "row": row, "seen": seen}

    for row in rows:
        try:
            seen = int(float(row.get("seen_count") or 0))
        except (ValueError, TypeError):
            seen = 0

        # فرنچایز
        f_vals = []
        for col in ("franchise", "franchise_en", "franchise_jp"):
            val = clean_val(row.get(col))
            if val and val not in f_vals:
                f_vals.append(val)

        f_norms = list({norm_key(v) for v in f_vals if norm_key(v)})
        for fn in f_norms:
            maps["franchise_total"][fn] = maps["franchise_total"].get(fn, 0) + seen

        for original in f_vals:
            n = norm_key(original)
            if not n:
                continue
            keys = [n]
            sp = split_paren(n)
            if sp and sp["head"]:
                keys.append(sp["head"])
            sk = _sorted_key(n)
            if sk:
                keys.append(sk)

            for k in keys:
                if k in DENY_WORDS:
                    continue
                if "_" not in k and seen < MIN_SEEN_WEAK_NS:
                    continue
                put(maps["franchise"], k, original, row, seen)

        # کاراکتر
        raw_char = clean_val(row.get("character"))
        if raw_char:
            n = norm_key(raw_char)
            if n and n not in DENY_WORDS:
                keys = [n]
                sp = split_paren(n)
                if sp and sp["head"]:
                    keys.append(sp["head"])
                sk = _sorted_key(n)
                if sk:
                    keys.append(sk)
                for cf in _compact_forms(n):
                    keys.append(cf)

                is_single = "_" not in n
                if not (is_single and seen < MIN_SEEN_SINGLE):
                    for k in keys:
                        put(maps["character"], k, raw_char, row, seen)
                        for fn in f_norms:
                            char_map = maps["char_by_cat"].setdefault(fn, {})
                            put(char_map, k, raw_char, row, seen)

    return maps


def load_dictionary(path: Optional[Path] = None) -> Tuple[dict, List[dict]]:
    global _MAPS
    path = path or config.DICTIONARY_PATH
    if not path.exists():
        log.warning("فایل دیکشنری در %s پیدا نشد.", path)
        return {"character": {}, "franchise": {}, "char_by_cat": {}, "franchise_total": {}}, []

    rows: List[dict] = []
    with path.open(encoding="utf-8-sig", newline="") as f:
        rows = list(csv.DictReader(f))
    maps = build_maps(rows)
    _MAPS = (maps, rows)
    return _MAPS


def get_maps() -> Tuple[dict, List[dict]]:
    global _MAPS
    if _MAPS is None:
        _MAPS = load_dictionary()
    return _MAPS


def franchise_total(name: str) -> int:
    """مجموع دیده شدن‌های فرنچایز در دیکشنری."""
    maps, _ = get_maps()
    return maps.get("franchise_total", {}).get(norm_key(name), 0)


def lookup_tag(norm: str, namespace_order: List[Tuple[str, dict]]) -> Optional[Tuple[str, dict]]:
    """جستجوی تگ نرمال‌شده در ایندکس با اولویت‌های مشخص."""
    if not norm or norm in DENY_WORDS:
        return None

    keys_to_test = [norm]
    sp = split_paren(norm)
    if sp and sp["head"]:
        keys_to_test.append(sp["head"])
    sk = _sorted_key(norm)
    if sk:
        keys_to_test.append(sk)
    ck = compact_key(norm)
    if ck and len(ck) >= 6:
        keys_to_test.append(ck)

    for ns, m in namespace_order:
        if not m:
            continue
        for k in keys_to_test:
            hit = m.get(k)
            if hit:
                return ns, hit
    return None


def js_str(t) -> str:
    return str(t.get("name") if isinstance(t, dict) else t)


def _filter_tags(x: dict) -> list:
    out = []
    for key in ("generalTags", "general_tags", "tagsRaw", "tags_raw"):
        v = x.get(key)
        if isinstance(v, list):
            for t in v:
                s = js_str(t).strip()
                if s:
                    out.append(s)
    return out


def filter_items(items: list, log=print) -> list:
    seen, out = set(), []
    n_tag = 0
    for it in items:
        hq = str(it.get("image_url_hq") or "").strip()
        std = str(it.get("image_url_std") or "").strip()
        item_id = str(it.get("id") or "").strip()
        branch = str(it.get("branch") or "").strip()
        source = str(it.get("source") or "").strip()
        category = str(it.get("category") or "").strip()

        if not (hq or std) or not item_id or not branch or not source or not category:
            continue
        if item_id in seen:
            continue
        seen.add(item_id)

        filter_set = config.pick_filter_set(source)
        if any(config.norm_tag(t) in filter_set for t in _filter_tags(it)):
            n_tag += 1
            continue
        out.append(it)

    log(f"فیلتر: {len(items)} ورودی → {len(out)} باقی ماند ({n_tag} مورد به خاطر برچسب حذف شد)")
    return out


def valid_image_urls(it: dict) -> bool:
    hq = str(it.get("image_url_hq") or "")
    std = str(it.get("image_url_std") or "")
    return (hq.startswith("https://") and std.startswith("https://")
            and bool(IMG_EXT.search(hq)) and bool(IMG_EXT.search(std)))


def enrich_posts(posts: list, dict_maps: Optional[dict] = None) -> list:
    """غنی‌سازی پست‌ها با نام فرنچایز و کاراکتر جهت استفاده در انتخاب‌گرها."""
    if dict_maps is None:
        dict_maps, _ = get_maps()

    ns_order = [
        ("character", dict_maps.get("character", {})),
        ("franchise", dict_maps.get("franchise", {})),
    ]

    out = []
    for p in posts:
        raw_tags = []
        for key in ("tagsRaw", "generalTags", "tags", "all_tags"):
            val = p.get(key)
            if isinstance(val, list):
                raw_tags.extend(val)

        characters = []
        franchises = []
        general = []

        for t in raw_tags:
            s = js_str(t).strip()
            norm = norm_key(s)
            if not norm or norm in DENY_WORDS:
                continue

            syn_f = resolve_franchise_synonym(norm)
            if syn_f:
                franchises.append(syn_f)
                continue

            hit = lookup_tag(norm, ns_order)
            if hit:
                ns, h = hit
                if ns == "character":
                    characters.append(h["original"])
                elif ns == "franchise":
                    franchises.append(h["original"])
            else:
                sp = split_paren(norm)
                if sp and sp["head"] and len(sp["head"]) > 1 and sp["head"] not in DENY_WORDS:
                    characters.append(pretty_name(sp["head"]))
                general.append(s)

        req = p.get("requestedAnime")
        if req:
            syn_req = resolve_franchise_synonym(req)
            franchises.append(syn_req or str(req).strip())

        inferred_fr = franchises[0] if franchises else (p.get("category") if p.get("category") != "anime" else None)
        char = characters[0] if characters else None

        out.append({
            **p,
            "character": char,
            "character_tags": characters,
            "franchise_tags": franchises,
            "general_tags": general,
            "inferred_franchise": inferred_fr,
            "all_tags": [js_str(t) for t in raw_tags],
        })
    return out
