#!/usr/bin/env python3
"""Run one AniWall Lab batch handed over by the bot through the private Telegram group.

The repo is public: stdout only gets counters. All pipeline logs go to a buffer and are
sent to the private group (dry runs and errors only). State changes go back as acks:
  /ack <batch> as <id> <id> ...              sent ids
  /ack <batch> blob <kind> <i> <n> <chunk>   state ("st") / tag stats ("tags")
  /ack <batch> done
"""
from __future__ import annotations

import argparse
import asyncio
import io
import json
import logging
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

LOG_BUF = io.StringIO()
_handler = logging.StreamHandler(LOG_BUF)
_handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
logging.getLogger().handlers[:] = [_handler]
logging.getLogger().setLevel(logging.INFO)

from telethon import TelegramClient              # noqa: E402
from telethon.errors import FloodWaitError       # noqa: E402
from telethon.sessions import StringSession      # noqa: E402

CHUNK = 3000        # chars per ack message (Telegram limit is 4096)
ACK_GAP = 1.2       # seconds between messages to the group


async def _connect():
    client = TelegramClient(
        StringSession(os.environ["TG_SESSION_STRING"].strip()),
        int(os.environ["TG_API_ID"].strip()),
        os.environ["TG_API_HASH"].strip(),
    )
    await client.connect()
    return client


async def _resolve(client, chat_id):
    value = int(chat_id) if str(chat_id).lstrip("-").isdigit() else chat_id
    try:
        return await client.get_input_entity(value)
    except ValueError:
        await client.get_dialogs()
        return await client.get_input_entity(value)


async def _fetch_batch(chat_id, message_id):
    client = await _connect()
    try:
        entity = await _resolve(client, chat_id)
        msg = await client.get_messages(entity, ids=int(message_id))
        if not msg or not msg.media:
            raise RuntimeError("batch message not found")
        data = await client.download_media(msg, file=bytes)
        return json.loads(data.decode("utf-8"))
    finally:
        await client.disconnect()


async def _say(chat_id, text):
    client = await _connect()
    try:
        entity = await _resolve(client, chat_id)
        await client.send_message(entity, text, parse_mode=None)
    finally:
        await client.disconnect()


def say(chat_id, text) -> bool:
    for _ in range(3):
        try:
            asyncio.run(_say(chat_id, str(text)[:4000]))
            return True
        except FloodWaitError as e:
            time.sleep(min(e.seconds + 1, 60))
        except Exception as e:
            print(f"say failed: {type(e).__name__}")
            time.sleep(3)
    return False


class AckSink:
    def __init__(self, chat, batch_id):
        self.chat = chat
        self.batch_id = batch_id

    def _send(self, text):
        say(self.chat, text)
        time.sleep(ACK_GAP)

    def sent(self, item_ids: list[str]) -> None:
        cur, size = [], 0
        for i in item_ids:
            if cur and size + len(i) + 1 > CHUNK:
                self._send(f"/ack {self.batch_id} as {' '.join(cur)}")
                cur, size = [], 0
            cur.append(i)
            size += len(i) + 1
        if cur:
            self._send(f"/ack {self.batch_id} as {' '.join(cur)}")

    def blob(self, kind: str, data) -> None:
        raw = json.dumps(data, separators=(",", ":")).replace(" ", "\\u0020")
        parts = [raw[i:i + CHUNK] for i in range(0, len(raw), CHUNK)] or [raw]
        for i, part in enumerate(parts, start=1):
            self._send(f"/ack {self.batch_id} blob {kind} {i} {len(parts)} {part}")


def send_log(chat, header: str, limit: int) -> None:
    text = LOG_BUF.getvalue()[-limit:]
    if not text:
        return
    for i in range(0, len(text), 3800):
        say(chat, f"{header}\n{text[i:i + 3800]}")
        time.sleep(ACK_GAP)


def run(batch: dict, sink: AckSink) -> int:
    from aniwall import config, wallhaven, zerochan
    from aniwall.scheduler import Scheduler
    from aniwall.state import SentStore, StateStore

    dry_run = bool(batch.get("dry"))
    if batch.get("target_chat_id"):
        config.TG_CHAT_ID = str(batch["target_chat_id"])
    if batch.get("storage_chat_id"):
        config.STORAGE_CHAT_ID = str(batch["storage_chat_id"])
    if batch.get("wallhaven_api_key"):
        config.WALLHAVEN_API_KEY = str(batch["wallhaven_api_key"])

    flows_map = {
        "both": [("HD (Wallhaven)", wallhaven), ("Zerochan", zerochan)],
        "hd": [("HD (Wallhaven)", wallhaven)],
        "zerochan": [("Zerochan", zerochan)],
    }
    mode = str(batch.get("mode") or "both").lower()
    flows_to_run = flows_map.get(mode, flows_map["both"])

    sent = SentStore(initial_ids=batch.get("sent"), sink=sink, dry_run=dry_run)
    state = StateStore(initial_data=batch.get("state"), sink=sink, dry_run=dry_run)

    def log(msg: str) -> None:
        logging.info(msg)

    total, errors = 0, 0
    with Scheduler(log, dry_run=dry_run) as sched:
        for flow_label, flow_module in flows_to_run:
            try:
                total += flow_module.run(sent=sent, state=state, dry_run=dry_run, log=log, sched=sched)
            except Exception as e:
                errors += 1
                log(f"❌ {flow_label} failed: {type(e).__name__}: {e}")

    state.save()
    return 1 if errors else 0


def main() -> int:
    sys.stdout.reconfigure(line_buffering=True)
    ap = argparse.ArgumentParser()
    ap.add_argument("--batch-id", required=True)
    ap.add_argument("--message-id", required=True)
    args = ap.parse_args()

    for k in ("TG_API_ID", "TG_API_HASH", "TG_SESSION_STRING", "BATCH_CHAT_ID"):
        if not os.environ.get(k, "").strip():
            print(f"missing env: {k}")
            return 1
    chat = os.environ["BATCH_CHAT_ID"].strip()

    try:
        batch = asyncio.run(_fetch_batch(chat, args.message_id))
        if batch.get("batch_id") != args.batch_id or batch.get("kind") != "aniwall":
            raise RuntimeError("bad batch")
    except Exception as e:
        print(f"batch load failed: {type(e).__name__}")
        say(chat, f"❌ {args.batch_id} could not load: {type(e).__name__}: {str(e)[:300]}")
        return 1

    print(f"batch loaded: mode={batch.get('mode')} dry={bool(batch.get('dry'))}")
    sink = AckSink(chat, args.batch_id)
    err = None
    failed = False
    try:
        failed = bool(run(batch, sink))
    except BaseException as e:
        if isinstance(e, KeyboardInterrupt):
            raise
        err = e

    if batch.get("dry") or err is not None or failed:
        if err is not None:
            head = f"🧾 {args.batch_id} ❌ {type(err).__name__}: {str(err)[:300]}"
        elif failed:
            head = f"🧾 {args.batch_id} ⚠️ یکی از مسیرها خطا داد"
        else:
            head = f"🧾 {args.batch_id} (dry)"
        send_log(chat, head, 12000 if batch.get("dry") else 6000)
    say(chat, f"/ack {args.batch_id} done")
    print(f"finished: error={type(err).__name__ if err else None} failed={failed}")
    return 1 if (err or failed) else 0
  


if __name__ == "__main__":
    sys.exit(main())
