"""
زمان‌بندی تلگرام با Telethon (Scheduled Messages) — صف مشترک کانال.

- پشتیبانی از حالت آفلاین در dry-run (در صورتی که سشن تلگرام موجود نباشد، کرش نمی‌کند).
- مدیریت اسلات‌های زمانی و ظرفیت صف.
- ارسال اسناد HD به مخزن (storage) و گرفتن لینک بات (بدون هیچ دستکاری در لینک).
"""

import asyncio
import io
import os
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from aniwall import config


class QueueFull(RuntimeError):
    """صف Scheduled پر است (یا جا برای این گروه نیست) — خطای عادی؛ ران آروم تموم می‌شه."""


class StorageLinkError(RuntimeError):
    """لینک بات بعد از ارسال اسناد به مخزن نیومد (اسناد مخزن پاک شدن)."""


def upcoming_slots(now_utc: datetime, slots_hm) -> list:
    """اسلات‌های (ساعت, دقیقه‌ی تهران) که توی بازه‌ی [الان + LEAD ، الان + HORIZON] می‌افتن → لیست datetime (UTC)."""
    tz = ZoneInfo(config.SCHED_TZ)
    now_l = now_utc.astimezone(tz)
    start = now_l + timedelta(minutes=config.SCHED_LEAD_MIN)
    end = now_l + timedelta(hours=config.SCHED_HORIZON_H)
    out = []
    for d in range(0, 3):
        day = (now_l + timedelta(days=d)).date()
        for h, m in slots_hm:
            t = datetime(day.year, day.month, day.day, h, m, tzinfo=tz)
            if start <= t <= end:
                out.append(t.astimezone(timezone.utc))
    return sorted(out)


def classify_slot(slot: datetime, queue: list):
    """خروجی: ('filled', None) | ('free', زمان_نهایی) | ('blocked', None)"""
    tol = timedelta(minutes=config.SCHED_SAME_SLOT_TOL_MIN)
    span = timedelta(minutes=config.SCHED_SHIFT_MAX_MIN)
    if any(slot - tol <= q < slot + span + tol for q in queue):
        return "filled", None

    gap = timedelta(minutes=config.SCHED_MIN_GAP_MIN)
    step = config.SCHED_SHIFT_STEP_MIN
    for k in range(0, config.SCHED_SHIFT_MAX_MIN // step + 1):
        cand = slot + timedelta(minutes=k * step)
        if all(abs(q - cand) >= gap for q in queue):
            return "free", cand
    return "blocked", None


class Scheduler:
    def __init__(self, log, dry_run: bool = False):
        self.log = log
        self.dry_run = dry_run
        self.loop = None
        self.client = None
        self.entity = None
        self.storage = None    # entity مخزن اسناد (تنبل resolve می‌شه)
        self.queue = []        # زمان‌های (UTC) همه‌ی پیام‌های Scheduled کانال
        self.run_used = 0      # تعداد پیامی که همین ران گذاشته

    def __enter__(self):
        self.open()
        return self

    def __exit__(self, *exc):
        self.close()

    def _run(self, coro):
        if not self.loop:
            return None
        return self.loop.run_until_complete(coro)

    def open(self):
        missing = [k for k in ("TG_API_ID", "TG_API_HASH", "TG_SESSION_STRING") if not os.environ.get(k)]
        if missing:
            if self.dry_run:
                self.log(f"[dry-run] اطلاعات تلگرام ست نشده ({', '.join(missing)}) — شبیه‌سازی آفلاین صف فعال شد.")
                self.queue = []
                return
            raise RuntimeError(f"env تنظیم نشده: {', '.join(missing)} (باید GitHub Secrets باشن)")

        from telethon import TelegramClient
        from telethon.sessions import StringSession

        self.loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self.loop)
        self.client = TelegramClient(
            StringSession(os.environ["TG_SESSION_STRING"]),
            int(os.environ["TG_API_ID"]), os.environ["TG_API_HASH"])
        self._run(self.client.connect())
        self.entity = self._run(self._resolve(config.TG_CHAT_ID))
        self.refresh()
        self.log(f"صف Scheduled: {len(self.queue)} پیام | ظرفیت ایمن {config.SCHED_QUEUE_SAFE_CAP} | "
                 f"سقف این ران {config.SCHED_RUN_CAP}")
   
    def close(self):
        if self.client and self.loop:
            try:
                res = self.client.disconnect()
                # بسته به نسخه‌ی Telethon ممکنه coroutine برگردونه یا خودش همزمان قطع کنه
                if asyncio.iscoroutine(res) or isinstance(res, asyncio.Future):
                    self.loop.run_until_complete(res)
            except Exception as e:
                self.log(f"⚠️ قطع اتصال تلگرام با خطا مواجه شد: {type(e).__name__}: {e}")
            finally:
                self.loop.close()
        self.client = None

    async def _resolve(self, chat):
        value = int(chat) if str(chat).lstrip("-").isdigit() else chat
        try:
            return await self.client.get_input_entity(value)
        except ValueError:
            await self.client.get_dialogs()
            return await self.client.get_input_entity(value)

    async def _read_queue(self) -> list:
        if not self.client:
            return []
        from telethon.tl import functions
        res = await self.client(functions.messages.GetScheduledHistoryRequest(peer=self.entity, hash=0))
        times = []
        for m in getattr(res, "messages", None) or []:
            d = getattr(m, "date", None)
            if d is not None:
                times.append(d.astimezone(timezone.utc) if d.tzinfo else d.replace(tzinfo=timezone.utc))
        return sorted(times)

    def refresh(self) -> int:
        if not self.client:
            return len(self.queue)
        self.queue = self._run(self._read_queue())
        return len(self.queue)

    def free_space(self) -> int:
        return max(0, min(config.SCHED_RUN_CAP - self.run_used,
                          config.SCHED_QUEUE_SAFE_CAP - len(self.queue)))

    def room_for(self, n: int) -> bool:
        self.refresh()
        return n <= self.free_space()

    def plan(self, slots_hm, label: str, now: datetime = None) -> list:
        now = now or datetime.now(timezone.utc)
        tz = ZoneInfo(config.SCHED_TZ)
        out = []
        for slot in upcoming_slots(now, slots_hm):
            state, when = classify_slot(slot, self.queue)
            tag = f"{label} {slot.astimezone(tz):%m-%d %H:%M}"
            if state == "free":
                shifted = f" (جابه‌جا → {when.astimezone(tz):%H:%M})" if when != slot else ""
                self.log(f"   🟢 {tag} خالی{shifted}")
                out.append(when)
            elif state == "filled":
                self.log(f"   ⏭️ {tag} قبلاً پر شده")
            else:
                self.log(f"   🔴 {tag} نزدیک پیام دیگه‌ست و جا برای جابه‌جایی نیست؛ رد شد")
        return out

    # ───────────── ارسال زمان‌بندی‌شده‌ی عکس‌ها ─────────────
    async def _send(self, files, when, caption, as_doc):
        from telethon.errors import RPCError
        try:
            res = await self.client.send_file(
                self.entity, files if len(files) > 1 else files[0],
                caption=caption or None, parse_mode="html" if caption else None,
                force_document=as_doc, schedule=when)
        except RPCError as e:
            if "SCHEDULE_TOO_MUCH" in str(e):
                raise QueueFull(str(e)) from e
            raise
        return res if isinstance(res, list) else [res]

    @staticmethod
    def _named(blob: bytes, name: str):
        bio = io.BytesIO(blob)
        bio.name = name
        return bio

    def _schedule(self, items, when, caption, as_doc) -> list:
        n = len(items)
        if not 1 <= n <= 10:
            raise ValueError("آلبوم باید ۱ تا ۱۰ فایل داشته باشد")
        if not self.room_for(n):
            raise QueueFull(f"جا برای {n} پیام نیست (صف {len(self.queue)}، جای خالی {self.free_space()})")

        if self.dry_run and not self.client:
            self.run_used += n
            return [1000 + i for i in range(n)]

        files = [self._named(b, nm) for b, nm in items]
        msgs = self._run(self._send(files, when, caption, as_doc))
        self.run_used += len(msgs)
        self.refresh()
        return [m.id for m in msgs]

    def schedule_photos(self, when, photos: list, caption: str = "") -> list:
        return self._schedule(photos, when, caption, as_doc=False)

    def delete_scheduled(self, ids: list) -> bool:
        if not ids or not self.client:
            return True
        from telethon.tl import functions
        try:
            self._run(self.client(functions.messages.DeleteScheduledMessagesRequest(
                peer=self.entity, id=list(ids))))
            self.refresh()
            return True
        except Exception as e:
            self.log(f"⚠️ حذف پیام‌های Scheduled {ids} شکست خورد: {type(e).__name__}")
            return False

    # ───────────── مخزن اسناد HD (storage) ─────────────
    async def _ensure_storage(self):
        if self.storage is None:
            self.storage = await self._resolve(config.STORAGE_CHAT_ID)
        return self.storage

    async def _send_docs_to_storage(self, docs):
        """همه‌ی اسناد در «یک» آلبوم گروهی (نه تکی). سقف آلبوم تلگرام ۱۰ تاست."""
        storage = await self._ensure_storage()
        files = [self._named(b, nm) for b, nm in docs]
        res = await self.client.send_file(
            storage, files if len(files) > 1 else files[0], force_document=True)
        return res if isinstance(res, list) else [res]

    @staticmethod
    def _extract_link(msg):
        """لینک بات رو عیناً از متن یا entityهای پیام برمی‌داره (هیچ تغییری روش اعمال نمی‌شه)."""
        texts = [getattr(msg, "raw_text", None) or ""]
        for ent in getattr(msg, "entities", None) or []:
            url = getattr(ent, "url", None)
            if url:
                texts.append(url)
        for t in texts:
            hit = config.STORAGE_LINK_RE.search(t)
            if hit:
                return hit.group(0)
        return None

    async def _wait_bot_link(self, doc_ids: list):
        """منتظر پیام بات توی مخزن می‌مونه. پیام باید ریپلای به یکی از اسناد ما باشه
        (یا لینکش با شناسه‌ی اولین سند ما شروع بشه) تا با آلبوم دیگه‌ای قاطی نشه."""
        import re
        ids = set(doc_ids)
        first, last = min(doc_ids), max(doc_ids)
        own_start = re.compile(rf"wlart_{first}(?![0-9])")
        loop = asyncio.get_running_loop()
        deadline = loop.time() + config.STORAGE_LINK_TIMEOUT
        while True:
            async for m in self.client.iter_messages(self.storage, min_id=last, limit=30):
                link = self._extract_link(m)
                if not link:
                    continue
                if getattr(m, "reply_to_msg_id", None) in ids or own_start.search(link):
                    return link, m.id
            if loop.time() >= deadline:
                return None, None
            await asyncio.sleep(config.STORAGE_LINK_POLL)

    def send_documents_to_storage(self, docs: list) -> dict:
        """docs: [(bytes, filename), ...] → اسناد فوری و گروهی به مخزن می‌رن و لینک بات برمی‌گرده.
        خروجی: {"link": str, "doc_ids": [...], "link_msg_id": int}
        اگه لینک نیومد، اسناد مخزن پاک می‌شن و StorageLinkError پرتاب می‌شه."""
        n = len(docs)
        if not 1 <= n <= 10:
            raise ValueError("آلبوم اسناد باید ۱ تا ۱۰ فایل داشته باشد")

        if self.dry_run and not self.client:
            return {"link": "https://t.me/littlemask02_bot?start=wlart_DRYRUN",
                    "doc_ids": [], "link_msg_id": None}

        msgs = self._run(self._send_docs_to_storage(docs))
        doc_ids = [m.id for m in msgs]
        self.log(f"اسناد به مخزن رفت (message_id: {doc_ids}) — منتظر لینک بات...")

        link, link_id = self._run(self._wait_bot_link(doc_ids))
        if not link:
            self.delete_storage(doc_ids)
            raise StorageLinkError(
                f"بعد از {config.STORAGE_LINK_TIMEOUT} ثانیه لینک بات نیومد؛ اسناد مخزن پاک شد")
        self.log(f"لینک بات: {link}")
        return {"link": link, "doc_ids": doc_ids, "link_msg_id": link_id}

    def delete_storage(self, ids: list) -> bool:
        """حذف پیام‌های مخزن (برای برگشت وقتی عکس‌ها زمان‌بندی نشدن)."""
        ids = [i for i in (ids or []) if i]
        if not ids or not self.client:
            return True
        try:
            self._run(self.client.delete_messages(self.storage, ids))
            return True
        except Exception as e:
            self.log(f"⚠️ حذف پیام‌های مخزن {ids} شکست خورد: {type(e).__name__}: {e}")
            return False
