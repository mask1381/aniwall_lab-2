"""
انتخاب‌گرها.
  - pick_zerochan_groups ← نود «Pick Best Post10» (کیفیت + همگرایی وزن‌دار IDF، تا ۲ گروه)
  - pick_wallhaven       ← نود «Pick Best Post9» (۳ عکس با فرنچایز متفاوت)
"""

import math
import re

from aniwall import config

QUALITY_FLOOR = 0.35
COHESION_FLOOR_BASE = 0.15
SMALL_BATCH_N = 5
MIN_WEIGHT = 0.05

POSITIVE_QUALITY_TAGS = {'official_art', 'highres', 'wallpaper', 'mobile_wallpaper', 'desktop_wallpaper'}
NEGATIVE_QUALITY_TAGS = {'low_quality', 'worst_quality', 'compression_artifacts',
                         'jpeg_artifacts', 'screenshot'}
NOISE_TAGS = {'cross_over', 'crossover', 'parody'}


def _norm(s) -> str:
    return re.sub(r"[-\s]+", "_", str(s or "").lower().strip())


def _all_tags_of(x: dict) -> set:
    out = set()
    for key in ("tagsRaw", "zerochan_tags", "generalTags", "general_tags", "all_tags", "tags"):
        v = x.get(key)
        if isinstance(v, list):
            for t in v:
                if isinstance(t, dict):
                    name = t.get("name")
                    if name:
                        out.add(_norm(name))
                else:
                    out.add(_norm(t))
    return out


def _is_animated_gif(x: dict, tags: set) -> bool:
    url = x.get("image_url_hq") or x.get("image_url_std") or ""
    return bool(re.search(r"\.gif(\?|$)", url, re.I)) or "animated_gif" in tags


def _num(v) -> float:
    try:
        f = float(v or 0)
        return 0.0 if f != f else f
    except (TypeError, ValueError):
        return 0.0


def _weighted_jaccard(a: set, b: set, weight_of) -> float:
    if not a and not b:
        return 0.0
    union = a | b
    if not union:
        return 0.0
    inter_w = union_w = 0.0
    for t in union:
        w = weight_of(t)
        union_w += w
        if t in a and t in b:
            inter_w += w
    return inter_w / union_w if union_w else 0.0


def _quality_of(x: dict, tags: set) -> float:
    resolution = _num(x.get("width")) * _num(x.get("height"))
    byte_size = _num(x.get("byte_size"))
    explicit = _num(x.get("score"))

    raw = 0.0
    raw += min(1.0, resolution / 4_000_000)
    raw += min(1.0, byte_size / 5_000_000)
    raw += min(1.0, explicit / 100) if explicit > 0 else 0.0
    for p in POSITIVE_QUALITY_TAGS:
        if p in tags:
            raw += 0.3
    for n in NEGATIVE_QUALITY_TAGS:
        if n in tags:
            raw -= 0.5
    clamped = max(-1.5, min(3.0, raw))
    return (clamped + 1.5) / 4.5


def pick_zerochan_groups(raw_items: list) -> list:
    """خروجی: لیست گروه‌ها؛ هر گروه {groupIndex, groupSize, low_confidence, posts}"""
    if not raw_items:
        return []

    pool = [x for x in raw_items if not _is_animated_gif(x, _all_tags_of(x))] or raw_items
    clean = [x for x in pool if not (NOISE_TAGS & _all_tags_of(x))] or pool
    if not clean:
        return []

    n = len(clean)
    tags_by_item = [_all_tags_of(x) for x in clean]

    df = {}
    for ts in tags_by_item:
        for t in ts:
            df[t] = df.get(t, 0) + 1

    weight_cache = {}

    def weight_of(t):
        if t not in weight_cache:
            d = df.get(t) or 1
            weight_cache[t] = max(MIN_WEIGHT, math.log(n / d))
        return weight_cache[t]

    enriched = [{"x": x, "tags": tags_by_item[i], "quality": _quality_of(x, tags_by_item[i])}
                for i, x in enumerate(clean)]

    cohesion_floor = COHESION_FLOOR_BASE * 0.7 if n < SMALL_BATCH_N else COHESION_FLOOR_BASE

    def build_group(items):
        if not items:
            return None
        by_quality = sorted(items, key=lambda e: -e["quality"])
        seed = by_quality[0]
        selected = [seed]
        low_conf = seed["quality"] < QUALITY_FLOOR

        def cohesion_with_group(c):
            sims = [_weighted_jaccard(c["tags"], m["tags"], weight_of) for m in selected]
            return sum(sims) / len(sims)

        while len(selected) < config.ZEROCHAN_MAX_ALBUM:
            remaining = [e for e in items if e not in selected]
            if not remaining:
                break
            scored = [(e, cohesion_with_group(e)) for e in remaining]
            scored.sort(key=lambda s: -(0.4 * s[0]["quality"] + 0.6 * s[1]))
            nxt = next((s for s in scored
                        if s[0]["quality"] >= QUALITY_FLOOR and s[1] >= cohesion_floor), None)
            if not nxt:
                break
            selected.append(nxt[0])
        return selected, low_conf

    g1 = build_group(enriched)
    if not g1:
        return []
    remainder = [e for e in enriched if e not in g1[0]]
    g2 = build_group(remainder)

    groups = []
    for idx, g in enumerate([g1, g2]):
        if not g:
            continue
        selected, low_conf = g
        size = len(selected)
        mode = "quality_thematic" if size > 1 else "single_best"
        groups.append({
            "groupIndex": idx,
            "groupSize": size,
            "album_mode": mode,
            "low_confidence": low_conf,
            "posts": [{**e["x"], "slotIndex": i, "albumIndex": i, "albumCount": size,
                       "groupSize": size, "album_mode": mode, "low_confidence": low_conf}
                      for i, e in enumerate(selected)],
        })
    return groups


# ═══════════════════════════════════════════════════════════
# Wallhaven ← نود «Pick Best Post9» (۳ عکس با فرنچایز متفاوت)
# ═══════════════════════════════════════════════════════════
def _wallhaven_score(x: dict) -> float:
    score = 0.0
    if x.get("character"):
        score += 3
    if x.get("inferred_franchise"):
        score += 2
    if x.get("inferred_studio"):
        score += 1

    tags = x.get("general_tags")
    if tags is None:
        tags = x.get("all_tags") or []
    score += min(len(tags), 6) * 0.5
    if any(re.search(r"8K", str(t), re.I) for t in tags):
        score += 1
    s = x.get("score")
    if isinstance(s, (int, float)) and not isinstance(s, bool):
        score += s
    return score


def pick_wallhaven(items: list, count: int | None = None) -> list:
    """۳ آیتم برتر با فرنچایز متفاوت؛ اگه ۳ تا پیدا نشد لیست خالی (مثل فلو)."""
    count = count or config.WALLHAVEN_PICK_COUNT
    if not items:
        return []

    scored = sorted(
        ({"x": x, "score": _wallhaven_score(x),
          "franchise": x.get("inferred_franchise") or x.get("franchise") or "Unknown"}
         for x in items),
        key=lambda e: -e["score"])

    picked, used = [], set()
    for e in scored:
        if len(picked) >= count:
            break
        if e["franchise"] not in used:
            picked.append(e)
            used.add(e["franchise"])
    if len(picked) < count:
        for e in scored:
            if len(picked) >= count:
                break
            if e not in picked:
                picked.append(e)

    if len(picked) < count:
        return []
    return [e["x"] for e in picked[:count]]
