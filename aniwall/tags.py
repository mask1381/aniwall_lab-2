"""
موتور دسته‌بندی و پالایش هشتگ‌ها (Tag Classifier & Pipeline).

ویژگی‌ها:
- عدم محدودیت روی تعداد فرنچایزها (پشتیبانی کامل از کراس‌اورها و آلبوم‌های چندانیمه‌ای).
- استخراج کاراکترها (حداکثر ۳ مورد با اعتبارسنجی seen_count و عدم برخورد با کلمات تک‌کلمه‌ای تصادفی).
- انتخاب دقیقاً ۱ هشتگ تم (Theme) با بالاترین وزن از content_tags و synonyms.
- عدم وابستگی صرف به دیکشنری: استخراج الگوهای Name (Work)، متادیتای کتگوری منابع و کدهای کمکی.
- حذف هشتگ‌های موازی و تکراری (Redundant Tags).
- ارسال خودکار تگ‌های دیده‌شده به سیستم ۱ (stats.py) برای ثبت تاریخچه.
"""

from __future__ import annotations

import csv
import logging
import re
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple

from aniwall import config
from aniwall.enrich import (
    DENY_WORDS,
    PAREN_JUNK,
    SINGLE_CHAR_MIN_SEEN,
    SINGLE_FRANCHISE_MIN,
    franchise_total,
    get_maps,
    lookup_tag,
    pretty_name,
    split_paren,
)
from aniwall.stats import record_tag_sightings
from aniwall.synonyms import (
    compact_key,
    norm_key,
    resolve_franchise_synonym,
    resolve_theme_synonym,
    to_hashtag,
)

log = logging.getLogger(__name__)

PAREN_RE = re.compile(r"^(?P<head>[^()]+?)\s*\((?P<inside>[^()]+)\)\s*$")
SEP_RE = re.compile(r"[\s_\-./:'\"?*+]+")

_CONTENT_MAP: Dict[str, str] | None = None
_ADULT_SET: Set[str] | None = None
_DROP_SET: Set[str] | None = None
_FILTERS: Dict[str, list] | None = None


def load_tag_column(path: Path) -> Set[str]:
    out: Set[str] = set()
    if not path.exists():
        return out
    with path.open(encoding="utf-8-sig", newline="") as f:
        for row in csv.DictReader(f):
            k = norm_key((row.get("tag") or "").strip())
            if k:
                out.add(k)
    return out


def load_content_map(path: Optional[Path] = None) -> Dict[str, str]:
    global _CONTENT_MAP
    path = path or config.CONTENT_TAGS_PATH
    mapping: Dict[str, str] = {}
    if path.exists():
        with path.open(encoding="utf-8-sig", newline="") as f:
            for row in csv.DictReader(f):
                tag = (row.get("tag") or "").strip()
                ht = (row.get("hashtag") or "").strip()
                k = norm_key(tag)
                if k and ht:
                    mapping[k] = ht
    _CONTENT_MAP = mapping
    return _CONTENT_MAP


def load_filters(path: Optional[Path] = None) -> Dict[str, list]:
    global _FILTERS
    path = path or config.FILTERS_PATH
    out: Dict[str, list] = {"stems": [], "regexes": []}
    if path.exists():
        with path.open(encoding="utf-8-sig", newline="") as f:
            for row in csv.DictReader(f):
                kind = (row.get("kind") or "").strip().lower()
                val = (row.get("value") or "").strip()
                if not val:
                    continue
                if kind == "stem":
                    out["stems"].append(SEP_RE.sub("", val.lower()))
                elif kind == "regex":
                    try:
                        out["regexes"].append(re.compile(val, re.I))
                    except re.error:
                        pass
    _FILTERS = out
    return _FILTERS


def get_content_map() -> Dict[str, str]:
    global _CONTENT_MAP
    if _CONTENT_MAP is None:
        _CONTENT_MAP = load_content_map()
    return _CONTENT_MAP


def get_adult_set() -> Set[str]:
    global _ADULT_SET
    if _ADULT_SET is None:
        _ADULT_SET = load_tag_column(config.ADULT_TAGS_PATH)
    return _ADULT_SET


def get_drop_set() -> Set[str]:
    global _DROP_SET
    if _DROP_SET is None:
        _DROP_SET = load_tag_column(config.DROP_TAGS_PATH)
    return _DROP_SET


def get_filters() -> Dict[str, list]:
    global _FILTERS
    if _FILTERS is None:
        _FILTERS = load_filters()
    return _FILTERS


def is_blocked_word(text: str) -> bool:
    if not text:
        return False
    raw = str(text).lower()
    compact = SEP_RE.sub("", raw)
    f = get_filters()
    return any(s in compact for s in f["stems"]) or any(rx.search(raw) for rx in f["regexes"])


def is_redundant(candidate_ht: str, anchor_hts: List[str]) -> bool:
    c_body = candidate_ht.lstrip("#").lower()
    for a in anchor_hts:
        a_body = a.lstrip("#").lower()
        if not a_body or len(a_body) < 4:
            continue
        if len(c_body) >= 4 and (a_body in c_body or c_body in a_body):
            return True
    return False


def extract_raw_tags(items: List[dict]) -> List[str]:
    seen: Set[str] = set()
    out: List[str] = []
    for it in items:
        for key in ("tagsRaw", "zerochan_tags", "generalTags", "general_tags", "all_tags", "tags"):
            val = it.get(key)
            if not isinstance(val, list):
                continue
            for t in val:
                s = ""
                if isinstance(t, dict):
                    s = str(t.get("name") or "").strip()
                else:
                    s = str(t or "").strip()
                if s and s.lower() not in seen:
                    seen.add(s.lower())
                    out.append(s)
    return out


def classify_post_tags(
    items: List[dict],
    source: str = "",
    max_characters: int = 3,
) -> dict:
    dict_maps, _ = get_maps()
    content_map = get_content_map()
    adult_set = get_adult_set()
    drop_set = get_drop_set()

    raw_tags = extract_raw_tags(items)

    explicit_franchises: List[str] = []
    explicit_characters: List[str] = []

    for it in items:
        for t in it.get("tagsRaw", []):
            if isinstance(t, dict):
                name = str(t.get("name") or "").strip()
                cat = str(t.get("category") or "")
                if cat == "Series" and name:
                    explicit_franchises.append(name)
                elif cat in ("Characters", "Fictional Characters") and name:
                    m = PAREN_RE.match(name)
                    if m:
                        explicit_characters.append(m.group("head").strip())
                        explicit_franchises.append(m.group("inside").strip())
                    else:
                        explicit_characters.append(name)

        req = it.get("requestedAnime")
        if req and str(req).strip():
            explicit_franchises.append(str(req).strip())
        char_field = it.get("character")
        if char_field and str(char_field).strip() and str(char_field).lower() != "unknown":
            explicit_characters.append(str(char_field).strip())

    ns_order = [
        ("character", dict_maps.get("character", {})),
        ("franchise", dict_maps.get("franchise", {})),
    ]

    decisions: List[dict] = []
    detected_franchises: List[str] = []
    detected_characters: List[str] = []
    theme_candidates: List[Tuple[str, int]] = []

    rank_lookup = {ht: i for i, ht in enumerate(content_map.values())}

    for tag in raw_tags:
        norm = norm_key(tag)
        if not norm:
            continue

        if norm in adult_set or is_blocked_word(tag):
            decisions.append({"tag": tag, "status": "adult", "used": False})
            continue
        if norm in drop_set or norm in DENY_WORDS:
            decisions.append({"tag": tag, "status": "drop", "used": False})
            continue

        # بررسی مترادف‌های ثبت‌شده
        syn_franchise = resolve_franchise_synonym(norm)
        if syn_franchise:
            detected_franchises.append(syn_franchise)
            decisions.append({"tag": tag, "status": "franchise", "used": True})
            continue

        syn_theme = resolve_theme_synonym(norm)
        if syn_theme:
            ht = f"#{syn_theme}" if not syn_theme.startswith("#") else syn_theme
            priority = rank_lookup.get(ht, 999)
            theme_candidates.append((ht, priority))
            decisions.append({"tag": tag, "status": "theme", "used": True})
            continue

        # تطبیق با دیکشنری با اعتبارسنجی
        hit = lookup_tag(norm, ns_order)
        if hit:
            ns, rec = hit
            orig = rec["original"]
            seen_cnt = rec["seen"]
            is_single_word = "_" not in norm

            if ns == "franchise":
                # کلمه تک‌کلمه‌ای باید اعتبارسنجی شود
                if is_single_word and franchise_total(orig) < SINGLE_FRANCHISE_MIN and seen_cnt < SINGLE_FRANCHISE_MIN:
                    decisions.append({"tag": tag, "status": "skip", "used": False})
                    continue
                detected_franchises.append(orig)
                decisions.append({"tag": tag, "status": "franchise", "used": True})
                continue
            elif ns == "character":
                if is_single_word and seen_cnt < SINGLE_CHAR_MIN_SEEN:
                    decisions.append({"tag": tag, "status": "skip", "used": False})
                    continue
                detected_characters.append(orig)
                decisions.append({"tag": tag, "status": "character", "used": True})
                continue

        # الگوی Name (Work)
        m = PAREN_RE.match(tag.replace("_", " "))
        if m:
            head, inside = m.group("head").strip(), m.group("inside").strip()
            head_norm = norm_key(head)
            if head_norm and head_norm not in DENY_WORDS and not PAREN_JUNK.search(inside):
                ins_syn = resolve_franchise_synonym(inside)
                detected_franchises.append(ins_syn or inside)
                detected_characters.append(head)
                decisions.append({"tag": tag, "status": "paren_char", "used": True})
                continue

        # تم از content_map
        if norm in content_map:
            ht = content_map[norm]
            priority = rank_lookup.get(ht, 999)
            theme_candidates.append((ht, priority))
            decisions.append({"tag": tag, "status": "theme", "used": True})
            continue

        decisions.append({"tag": tag, "status": "skip", "used": False})

    # اضافه کردن موارد صریح
    for ef in explicit_franchises:
        ef_norm = norm_key(ef)
        if ef_norm and ef_norm not in DENY_WORDS and ef_norm not in drop_set:
            syn = resolve_franchise_synonym(ef)
            detected_franchises.append(syn or ef)
    for ec in explicit_characters:
        ec_norm = norm_key(ec)
        if ec_norm and ec_norm not in DENY_WORDS and ec_norm not in drop_set:
            detected_characters.append(ec)

    # یکتاکردن هشتگ‌های فرنچایز
    franchise_hts: List[str] = []
    seen_fr: Set[str] = set()
    for f in detected_franchises:
        ht = to_hashtag(f)
        if ht and ht.lower() not in seen_fr:
            seen_fr.add(ht.lower())
            franchise_hts.append(ht)

    # یکتاکردن هشتگ‌های کاراکترها
    char_hts: List[str] = []
    seen_ch: Set[str] = set()
    for c in detected_characters:
        ht = to_hashtag(c)
        if not ht or ht.lower() in seen_fr:
            continue
        if is_redundant(ht, franchise_hts):
            continue
        if ht.lower() not in seen_ch:
            seen_ch.add(ht.lower())
            char_hts.append(ht)
            if len(char_hts) >= max_characters:
                break

    # انتخاب دقیقاً ۱ هشتگ تم (Theme) با بالاترین اولویت
    selected_theme: Optional[str] = None
    if theme_candidates:
        theme_candidates.sort(key=lambda t: t[1])
        for ht, _ in theme_candidates:
            if ht.lower() not in seen_fr and ht.lower() not in seen_ch:
                if not is_redundant(ht, franchise_hts + char_hts):
                    selected_theme = ht
                    break

    final_hashtags = franchise_hts + char_hts
    if selected_theme:
        final_hashtags.append(selected_theme)

    record_tag_sightings(raw_tags, source=source, decisions=decisions)

    return {
        "franchises": detected_franchises,
        "franchise_hashtags": franchise_hts,
        "characters": detected_characters,
        "character_hashtags": char_hts,
        "theme_hashtag": selected_theme,
        "hashtags": final_hashtags,
        "decisions": decisions,
        "raw_tags": raw_tags,
    }
