"""
ذخیره‌ی وضعیت داخل ریپو (جایگزین Data Table «arts» و static data در n8n).

- SentStore  → data/sent_ids.json  (شناسه‌هایی مثل "zerochan:123" یا "wallhaven:abc")
- StateStore → data/state.json     (کیسه‌ی چرخشی انیمه و ...)
"""

import json
import os
import tempfile
from pathlib import Path


def load_json(path: Path, default):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        return default
    except json.JSONDecodeError as e:
        raise RuntimeError(f"فایل JSON خراب است ({path}): {e}")


def save_json_atomic(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
            f.write("\n")
        os.replace(tmp, path)
    except Exception:
        if os.path.exists(tmp):
            os.remove(tmp)
        raise


class SentStore:
    """مجموعه‌ی شناسه‌های قبلاً ارسال‌شده (برای جلوگیری از تکرار)."""

    def __init__(self, path: Path | None = None, initial_ids: list | set | None = None, sink=None, dry_run: bool = False):
        self.path = path
        self.sink = sink
        self.dry_run = dry_run
        if initial_ids is not None:
            self._ids = set(initial_ids)
        elif path and path.exists():
            data = load_json(path, {"ids": []})
            self._ids = set(data.get("ids", []))
        else:
            self._ids = set()

    def __contains__(self, item_id: str) -> bool:
        return item_id in self._ids

    def __len__(self) -> int:
        return len(self._ids)

    def add(self, *item_ids: str) -> None:
        """فقط بعد از ارسال موفق صدا زده بشه."""
        new_ids = []
        for i in item_ids:
            if i and i not in self._ids:
                self._ids.add(i)
                new_ids.append(i)
        if new_ids:
            if self.sink and not self.dry_run:
                self.sink.sent(new_ids)
            elif self.path and not self.dry_run:
                self.save()

    def save(self) -> None:
        if self.dry_run:
            return
        if self.path:
            save_json_atomic(self.path, {"ids": sorted(self._ids)})


class StateStore:
    """دیکشنری ساده‌ی وضعیت (جایگزین $getWorkflowStaticData)."""

    DEFAULT = {
        "animeBag": [],
        "animePoolVersion": "",
        "animeCycle": 0,
        "lastAnime": None,
        "remaining": 0,
    }

    def __init__(self, path: Path | None = None, initial_data: dict | None = None, sink=None, dry_run: bool = False):
        self.path = path
        self.sink = sink
        self.dry_run = dry_run
        if initial_data is not None:
            self.data = {**self.DEFAULT, **initial_data}
        elif path and path.exists():
            self.data = {**self.DEFAULT, **load_json(path, {})}
        else:
            self.data = dict(self.DEFAULT)

    def get(self, key, default=None):
        return self.data.get(key, default)

    def set(self, key, value) -> None:
        self.data[key] = value

    def save(self) -> None:
        if self.dry_run:
            return
        if self.sink:
            self.sink.blob("st", self.data)
        elif self.path:
            save_json_atomic(self.path, self.data)
