"""
관찰리스트 영속화 (JSON 파일).

종목별로 펀더멘털 + 메모 저장. 분석/백테스트의 입력 소스.
"""
from __future__ import annotations

import json
from dataclasses import asdict
from threading import RLock
from typing import Any

from buffett_strategy import Fundamentals
from config import get_runtime_data_dir


_DATA_DIR = get_runtime_data_dir()
_WATCH_FILE = _DATA_DIR / "watchlist.json"

_lock = RLock()


def _load() -> dict[str, dict[str, Any]]:
    if not _WATCH_FILE.exists():
        return {}
    with _WATCH_FILE.open("r", encoding="utf-8") as fp:
        return json.load(fp)


def _save(data: dict[str, dict[str, Any]]) -> None:
    with _WATCH_FILE.open("w", encoding="utf-8") as fp:
        json.dump(data, fp, ensure_ascii=False, indent=2)


def list_watchlist() -> list[dict[str, Any]]:
    with _lock:
        return list(_load().values())


def get_entry(ticker: str) -> dict[str, Any] | None:
    with _lock:
        return _load().get(ticker)


def upsert_entry(fundamentals: Fundamentals, memo: str = "") -> dict[str, Any]:
    with _lock:
        data = _load()
        entry = {
            "ticker": fundamentals.ticker,
            "name": fundamentals.name,
            "industry": fundamentals.industry,
            "fundamentals": asdict(fundamentals),
            "memo": memo,
        }
        data[fundamentals.ticker] = entry
        _save(data)
    return entry


def remove_entry(ticker: str) -> bool:
    with _lock:
        data = _load()
        if ticker in data:
            del data[ticker]
            _save(data)
            return True
    return False
