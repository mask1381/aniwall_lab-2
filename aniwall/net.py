"""درخواست‌های HTTP با retry (معادل retryOnFail و batching نودهای n8n)."""

import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

import requests

from aniwall import config

RETRY_STATUS = {429, 500, 502, 503, 504}
_local = threading.local()

_DIAG_HEADERS = ("server", "cf-ray", "cf-mitigated", "retry-after",
                 "content-type", "via", "x-cache")


def _diag(r) -> str:
    hdrs = {k: r.headers.get(k) for k in _DIAG_HEADERS if r.headers.get(k)}
    text = r.text or ""
    head = " ".join(text[:200].split())
    tail = " ".join(text[-200:].split())
    return f"headers={hdrs} len={len(text)} head={head!r} tail={tail!r}"


def _session():
    s = getattr(_local, "session", None)
    if s is None:
        s = requests.Session()
        _local.session = s
    return s


def request(method, url, *, retries=None, backoff=None, accept_marker=None, **kw):
    """accept_marker: اگر status از نوع 5xx بود ولی این رشته داخل بدنه بود،
    پاسخ به‌عنوان موفق برگردانده می‌شود (Zerochan گاهی داده‌ی سالم را با 500 می‌دهد)."""
    retries = retries or config.HTTP_RETRIES
    backoff = config.HTTP_BACKOFF if backoff is None else backoff
    kw.setdefault("timeout", config.HTTP_TIMEOUT)
    short = str(url).split("?")[0][:120]
    last = "unknown"

    for attempt in range(1, retries + 1):
        wait = backoff * attempt
        try:
            r = _session().request(method, url, **kw)
        except requests.RequestException as e:
            last = type(e).__name__
        else:
            if r.status_code < 400:
                return r
            if accept_marker and r.status_code >= 500 and accept_marker in (r.text or ""):
                return r
            last = f"HTTP {r.status_code} | {_diag(r)}"
            if r.status_code not in RETRY_STATUS:
                raise RuntimeError(f"{method} {short} → {last}")
            ra = r.headers.get("Retry-After", "")
            if ra.isdigit():
                wait = max(wait, min(int(ra), 60))
        if attempt < retries:
            time.sleep(wait)

    raise RuntimeError(f"{method} {short} → {last} (بعد از {retries} تلاش)")


def paced(items, batch_size, interval):
    """مثل batching در n8n: بعد از هر batch_size آیتم، interval ثانیه مکث."""
    for i, item in enumerate(items):
        if i and batch_size and i % batch_size == 0:
            time.sleep(interval)
        yield item


def map_parallel(items, fn, *, workers, log=None, label="آیتم"):
    """fn(item) → result؛ خطاها لاگ می‌شن و آن آیتم حذف می‌شود. ترتیب ورودی حفظ می‌شود."""
    if not items:
        return []
    workers = max(1, min(workers, len(items)))
    out = [None] * len(items)

    def _run(i, item):
        return i, fn(item)

    with ThreadPoolExecutor(max_workers=workers) as pool:
        futs = [pool.submit(_run, i, item) for i, item in enumerate(items)]
        for fut in as_completed(futs):
            try:
                i, result = fut.result()
                out[i] = result
            except Exception as e:
                if log:
                    log(f"⚠️ {label} گرفته نشد: {e}")

    return [x for x in out if x is not None]
