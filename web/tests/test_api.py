"""API behavior that does not call NVIDIA or a live database server."""

from __future__ import annotations

import json
import os
import sys
import tempfile
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "web"))

from fastapi.testclient import TestClient

from app import nvidia
from app.api import create_app
from app.db import reset_engine

_HTTP_JSON = nvidia.http_json
_HTTP_STREAM = nvidia.http_stream


class ApiTests(unittest.TestCase):
    def setUp(self):
        self.previous = {key: os.environ.get(key) for key in (
            "DATABASE_URL", "TUANZI_ACCESS_PASSWORD", "NVIDIA_API_KEY", "TUANZI_DEV_OPEN", "TUANZI_MODELS_URL",
        )}
        self.temporary = tempfile.TemporaryDirectory()
        os.environ["DATABASE_URL"] = "sqlite:///" + str(Path(self.temporary.name) / "tuanzi.db")
        os.environ["TUANZI_ACCESS_PASSWORD"] = "secret"
        os.environ["NVIDIA_API_KEY"] = ""
        os.environ["TUANZI_DEV_OPEN"] = "0"
        os.environ["TUANZI_MODELS_URL"] = ""
        reset_engine()
        self.client = TestClient(create_app())
        self.client.__enter__()

    def tearDown(self):
        self.client.__exit__(None, None, None)
        nvidia.http_json = _HTTP_JSON
        nvidia.http_stream = _HTTP_STREAM
        reset_engine()
        self.temporary.cleanup()
        for key, value in self.previous.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value

    def auth(self):
        self.assertEqual(self.client.post("/api/session", json={"password": "secret"}).status_code, 200)

    def test_password_blocks_chat_and_activity(self):
        self.assertEqual(self.client.post("/api/chat", json={"messages": [{"role": "user", "content": "在吗"}]}).status_code, 401)
        self.assertEqual(self.client.post("/api/activity/next", json={"recent": []}).status_code, 401)
        self.assertEqual(self.client.post("/api/session", json={"password": "nope"}).status_code, 401)
        health = self.client.get("/api/health").json()
        self.assertTrue(health["password_required"])
        self.assertEqual(health["chat"], "dev")

    def test_dev_chat_does_not_invent_a_model(self):
        self.auth()
        response = self.client.post("/api/chat", json={"messages": [{"role": "user", "content": "在吗"}]})
        self.assertEqual(response.status_code, 200)
        self.assertIn("NVIDIA_API_KEY", response.text)
        self.assertIn('"dev": true', response.text)
        self.assertNotIn("gpt-", response.text.lower())

    def test_activity_is_irregular_and_only_known_clips(self):
        self.auth()
        pauses = []
        clips = []
        for _ in range(9):
            body = self.client.post("/api/activity/next", json={"recent": clips[-2:]}).json()
            clips.append(body["clip"])
            pauses.append(body["pause_ms"])
            self.assertEqual(body["source"], "library")
            self.assertGreaterEqual(body["pause_ms"], 400)
            self.assertLessEqual(body["pause_ms"], 24000)
        self.assertGreater(len(set(pauses)), 1)
        self.assertGreaterEqual(len(set(clips)), 2)
        catalog = self.client.get("/api/clips").json()
        nest = next(item for item in catalog["clips"] if item["id"] == "nest-breath")
        self.assertTrue(nest["available"])
        self.assertEqual(nest["duration_ms"], 42)
        self.assertEqual(len(nest["frames"]), 120)
        groom = next(item for item in catalog["clips"] if item["id"] == "groom")
        self.assertTrue(groom["available"])
        self.assertEqual(groom["duration_ms"], 42)
        self.assertEqual(len(groom["frames"]), 144)

    def test_actions_are_allowlisted(self):
        self.auth()
        self.assertEqual(self.client.post("/api/actions", json={"name": "shell", "text": "rm -rf"}).status_code, 400)
        groom = self.client.post("/api/actions", json={"name": "groom"}).json()
        self.assertEqual(groom["client_effect"], "groom")
        reminder = self.client.post("/api/actions", json={"name": "remind", "text": "喝水", "minutes": 5}).json()
        self.assertTrue(reminder["ok"])
        self.assertEqual(reminder["text"], "喝水")

    def test_probes_pick_the_fastest_and_chat_falls_back(self):
        self.auth()
        os.environ["NVIDIA_API_KEY"] = "test-key-not-real"
        calls = []

        def fake_json(method, url, payload=None, headers=None, timeout=12):
            calls.append(url)
            return {"data": [{"id": "vendor/fast"}, {"id": "vendor/slow"}, {"id": "vendor/embed-text"}]}

        def probing_stream(url, payload, headers, timeout=12):
            model = payload["model"]
            time.sleep(0.03 if model.endswith("fast") else 0.09)
            yield 'data: {"choices":[{"delta":{"content":"喵"}}]}'

        nvidia.http_json = fake_json
        nvidia.http_stream = probing_stream
        probed = self.client.post("/api/models/probe")
        self.assertEqual(probed.status_code, 200, probed.text)
        ranked = probed.json()["ranked"]
        self.assertEqual(ranked[0], "vendor/fast")
        self.assertIn("vendor/slow", ranked)
        self.assertNotIn("vendor/embed-text", ranked)
        self.assertTrue(calls)

        def failing_fast(url, payload, headers, timeout=45):
            if payload["model"] == "vendor/fast":
                raise TimeoutError("down")
            content = '在呢[[action:{"name":"groom"}]]'
            yield "data: " + json.dumps({"choices": [{"delta": {"content": content}}]})

        nvidia.http_stream = failing_fast
        reply = self.client.post("/api/chat", json={"messages": [{"role": "user", "content": "在吗"}]})
        self.assertEqual(reply.status_code, 200)
        self.assertIn("在呢", reply.text)
        self.assertIn("groom", reply.text)
        self.assertIn("vendor/slow", reply.text)
        status = self.client.get("/api/models/status").json()
        self.assertEqual(status["fastest"], "vendor/slow")


if __name__ == "__main__":
    unittest.main()
