"""Small chat window. Speech stays in the web pet; this only talks to the API.

LUNA ZHOU, 2026-11-10.
"""

from __future__ import annotations

import threading

from PySide6.QtCore import Signal
from PySide6.QtGui import QTextCursor
from PySide6.QtWidgets import QDialog, QHBoxLayout, QLabel, QLineEdit, QPushButton, QTextEdit, QVBoxLayout

from .remote import configured, stream_chat


class ChatDialog(QDialog):
    chunk = Signal(str)
    finished_reply = Signal()
    remote_action = Signal(dict)

    def __init__(self, pet) -> None:
        super().__init__(pet)
        self.pet = pet
        self.history: list[dict] = []
        self.setWindowTitle("和团子说话")
        self.setModal(False)
        self.resize(360, 420)
        self.transcript = QTextEdit()
        self.transcript.setReadOnly(True)
        self.line = QLineEdit()
        self.line.setPlaceholderText("跟团子说一句")
        send = QPushButton("发送")
        send.clicked.connect(self.submit)
        self.line.returnPressed.connect(self.submit)
        row = QHBoxLayout()
        row.addWidget(self.line)
        row.addWidget(send)
        layout = QVBoxLayout(self)
        if configured():
            hint = "双击团子就能聊。语音在网页里，需要 HTTPS。"
        else:
            hint = "还没有 TUANZI_API_URL。设好以后，桌面团子和网页团子走同一个接口。"
        layout.addWidget(QLabel(hint))
        layout.addWidget(self.transcript)
        layout.addLayout(row)
        self.chunk.connect(self._append)
        self.finished_reply.connect(self._unlock)
        self.remote_action.connect(self._apply_action)
        self._reply = ""
        self._busy = False

    def submit(self) -> None:
        text = self.line.text().strip()
        if not text or self._busy:
            return
        self.line.clear()
        self.transcript.append("你：" + text)
        if not configured():
            self.transcript.append("团子：我还在这台电脑上，云端没接上。")
            return
        self.history.append({"role": "user", "content": text})
        self._reply = ""
        self._busy = True
        self.transcript.append("团子：")
        threading.Thread(target=self._read, args=(list(self.history),), daemon=True).start()

    def _read(self, messages: list[dict]) -> None:
        try:
            for event in stream_chat(messages):
                if event.get("delta"):
                    self._reply += event["delta"]
                    self.chunk.emit(event["delta"])
                if event.get("action"):
                    self.remote_action.emit(event["action"])
        except OSError:
            self.chunk.emit("这会儿没连上。")
        finally:
            if self._reply:
                self.history.append({"role": "assistant", "content": self._reply})
            self.finished_reply.emit()

    def _append(self, text: str) -> None:
        cursor = self.transcript.textCursor()
        cursor.movePosition(QTextCursor.MoveOperation.End)
        cursor.insertText(text)
        self.transcript.setTextCursor(cursor)

    def _unlock(self) -> None:
        self._busy = False

    def _apply_action(self, action: dict) -> None:
        if not action.get("ok"):
            return
        name = action.get("name")
        if name == "sleep":
            if not self.pet.sleeping:
                self.pet.toggle_sleep()
        elif name == "butterfly":
            self.pet.start_butterfly()
        elif name == "groom":
            self.pet.perform_motion("groom")
        elif name == "remind" and action.get("text"):
            self.pet.say(action["text"], 5)
