"""Optional client for the shared pet API. Offline when TUANZI_API_URL is unset.

LUNA ZHOU, 2026-11-10.
"""

from __future__ import annotations

import json
import os
import threading
import time
import urllib.error
import urllib.request


def api_base() -> str:
    return os.environ.get("TUANZI_API_URL", "").strip().rstrip("/")


def configured() -> bool:
    return bool(api_base())


def _headers() -> dict[str, str]:
    headers = {"Content-Type": "application/json", "Accept": "text/event-stream"}
    password = os.environ.get("TUANZI_ACCESS_PASSWORD", "")
    if password:
        headers["X-Tuanzi-Password"] = password
    return headers


def _request(path: str, payload: dict | None = None, timeout: float = 4) -> dict:
    data = None if payload is None else json.dumps(payload).encode("utf-8")
    method = "GET" if payload is None else "POST"
    request = urllib.request.Request(api_base() + path, data=data, headers=_headers(), method=method)
    with urllib.request.urlopen(request, timeout=timeout) as response:
        body = response.read().decode("utf-8")
    return json.loads(body) if body else {}


def fetch_activity(recent: list[str]) -> dict | None:
    try:
        plan = _request("/api/activity/next", {"recent": recent}, timeout=6)
    except (OSError, urllib.error.URLError, ValueError, TimeoutError):
        return None
    clip = plan.get("clip") if isinstance(plan, dict) else None
    return plan if isinstance(clip, str) else None


def fetch_reminders() -> list[str]:
    try:
        body = _request("/api/reminders", timeout=3)
    except (OSError, urllib.error.URLError, ValueError, TimeoutError):
        return []
    return [item["text"] for item in body.get("due", []) if isinstance(item, dict) and item.get("text")]


def stream_chat(messages: list[dict]):
    """Yield SSE objects. The caller is a worker thread, not the UI thread."""
    payload = json.dumps({"messages": messages}).encode("utf-8")
    request = urllib.request.Request(api_base() + "/api/chat", data=payload, headers=_headers(), method="POST")
    with urllib.request.urlopen(request, timeout=60) as response:
        buffer = ""
        while True:
            chunk = response.read(256)
            if not chunk:
                break
            buffer += chunk.decode("utf-8", errors="replace")
            parts = buffer.split("\n\n")
            buffer = parts.pop()
            for part in parts:
                line = next((item for item in part.split("\n") if item.startswith("data:")), "")
                if not line:
                    continue
                try:
                    yield json.loads(line[5:])
                except ValueError:
                    continue


class RemotePlan:
    """Background poll. The UI thread only reads the fields under the lock."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self.plan = None
        self.reminders: list[str] = []
        self._stop = threading.Event()
        self._thread = None

    def start(self) -> None:
        if not configured() or self._thread is not None:
            return
        self._thread = threading.Thread(target=self._loop, name="tuanzi-api", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()

    def take_plan(self) -> dict | None:
        with self._lock:
            plan, self.plan = self.plan, None
        return plan

    def take_reminders(self) -> list[str]:
        with self._lock:
            found, self.reminders = self.reminders, []
        return found

    def _loop(self) -> None:
        recent: list[str] = []
        while not self._stop.is_set():
            with self._lock:
                needs_plan = self.plan is None
            if needs_plan:
                plan = fetch_activity(recent)
                if plan:
                    recent = (recent + [plan["clip"]])[-6:]
                    with self._lock:
                        self.plan = plan
            notes = fetch_reminders()
            if notes:
                with self._lock:
                    self.reminders.extend(notes)
            self._stop.wait(4 if needs_plan else 12)
            time.sleep(0)
