"""Allowlisted structured actions. No shell, files, or desktop control."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy.orm import Session

from .db import Reminder

ALLOWLIST = frozenset({"sleep", "butterfly", "groom", "remind"})


def apply_action(db: Session, name: str, text: str | None = None, minutes: int | None = None) -> dict:
    if name not in ALLOWLIST:
        raise ValueError("动作不在允许列表里")
    if name == "remind":
        label = (text or "").strip()
        if not label or len(label) > 80:
            raise ValueError("提醒需要一句短话")
        delay = 30 if minutes is None else int(minutes)
        if delay < 1 or delay > 24 * 60:
            raise ValueError("提醒时间要在 1 分钟到 1 天之间")
        due = datetime.now(timezone.utc) + timedelta(minutes=delay)
        row = Reminder(text=label, due_at=due, done=False)
        db.add(row)
        db.commit()
        db.refresh(row)
        return {"ok": True, "name": "remind", "text": label, "due_at": due.isoformat(), "client_effect": "say"}
    effect = {"sleep": "sleep", "butterfly": "butterfly", "groom": "groom"}[name]
    return {"ok": True, "name": name, "client_effect": effect}


def due_reminders(db: Session) -> list[dict]:
    now = datetime.now(timezone.utc)
    rows = db.query(Reminder).filter(Reminder.done.is_(False), Reminder.due_at <= now).order_by(Reminder.due_at).all()
    found = []
    for row in rows:
        row.done = True
        found.append({"id": row.id, "text": row.text})
    if found:
        db.commit()
    return found
