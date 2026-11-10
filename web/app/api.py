"""HTTP surface for the web pet and the desktop client."""

from __future__ import annotations

import hmac
import json
import re
import threading
from collections.abc import Iterator
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, HTTPException, Request, Response
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.orm import Session

from tuanzi_shared.activity import normalize_model_steps, plan_steps

from . import nvidia
from .actions import apply_action, due_reminders
from .auth import COOKIE, authorized, nvidia_allowed, require_access, session_token
from .catalog import animation_clips, available_ids, sleep_poses
from .config import ASSETS, WEB_ROOT, access_password, dev_open, nvidia_api_key, probe_limit
from .db import get_setting, init_db, ranked_models, record_probe, session, set_setting

ACTION_RE = re.compile(r"\[\[action:(\{.*?\})\]\]")
_probe_lock = threading.Lock()


class LoginBody(BaseModel):
    password: str = ""


class ActivityBody(BaseModel):
    recent: list[str] = Field(default_factory=list)


class ChatBody(BaseModel):
    messages: list[dict] = Field(default_factory=list)


class ActionBody(BaseModel):
    name: str
    text: str | None = None
    minutes: int | None = None


def _db() -> Iterator[Session]:
    db = session()
    try:
        yield db
    finally:
        db.close()


def create_app() -> FastAPI:
    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        init_db()
        if nvidia_api_key() and (access_password() or dev_open()):
            threading.Thread(target=_probe_safely, name="tuanzi-probe", daemon=True).start()
        yield

    app = FastAPI(title="团子", version="1.1.0", lifespan=lifespan)

    static = WEB_ROOT / "static"
    app.mount("/static", StaticFiles(directory=static), name="static")

    @app.get("/")
    def index() -> FileResponse:
        return FileResponse(static / "index.html")

    @app.get("/manifest.webmanifest")
    def manifest() -> FileResponse:
        return FileResponse(static / "manifest.webmanifest", media_type="application/manifest+json")

    @app.get("/sw.js")
    def service_worker() -> FileResponse:
        return FileResponse(static / "sw.js", media_type="application/javascript")

    @app.get("/api/health")
    def health(db: Session = Depends(_db)) -> dict:
        try:
            db.execute(text("SELECT 1"))
            database = True
        except Exception:
            database = False
        return {
            "ok": database,
            "database": database,
            "chat": "nvidia" if nvidia_api_key() else "dev",
            "password_required": bool(access_password()),
            "dev_open": dev_open(),
        }

    @app.post("/api/session")
    def login(body: LoginBody, request: Request, response: Response) -> dict:
        password = access_password()
        if not password:
            if dev_open():
                return {"ok": True, "open": True}
            raise HTTPException(status_code=401, detail="还没有设置访问口令")
        given = body.password.encode("utf-8")
        expected = password.encode("utf-8")
        if len(given) != len(expected) or not hmac.compare_digest(given, expected):
            raise HTTPException(status_code=401, detail="口令不对")
        response.set_cookie(
            COOKIE, session_token(password), httponly=True, samesite="lax",
            secure=request.url.scheme == "https", max_age=60 * 60 * 24 * 14,
        )
        return {"ok": True}

    @app.get("/api/session")
    def session_state(request: Request) -> dict:
        return {"ok": authorized(request) or not access_password(), "password_required": bool(access_password())}

    @app.get("/api/clips")
    def clips(request: Request) -> dict:
        require_access(request)
        return {"clips": animation_clips(), "sleep_poses": sleep_poses()}

    @app.post("/api/activity/next")
    def activity_next(body: ActivityBody, request: Request, db: Session = Depends(_db)) -> dict:
        require_access(request)
        step = _next_step(db, body.recent, request)
        if step is None:
            raise HTTPException(status_code=404, detail="没有可播的动作")
        return step

    @app.post("/api/chat")
    def chat(body: ChatBody, request: Request, db: Session = Depends(_db)) -> StreamingResponse:
        require_access(request)
        messages = _clean_messages(body.messages)
        if not messages:
            raise HTTPException(status_code=400, detail="说点什么吧")

        def events() -> Iterator[str]:
            if not nvidia_allowed(request) or not nvidia_api_key():
                yield _sse({"delta": "团子这会儿在本地陪你。还没有可用的 NVIDIA_API_KEY，所以先不连外面的模型。", "dev": True})
                yield _sse({"done": True, "dev": True, "model": None})
                return
            order = ranked_models(db)
            if not order:
                threading.Thread(target=_probe_safely, name="tuanzi-probe", daemon=True).start()
                yield _sse({"delta": "团子正在挑这会儿最快的模型，再发一次我就接上。", "dev": True})
                yield _sse({"done": True, "dev": True, "model": None})
                return
            last_error = ""
            for model_name in order[:3]:
                held = ""
                spoken = []
                try:
                    for piece in nvidia.stream_model(model_name, _system() + messages):
                        held += piece
                        visible, actions, held = _drain(held, finished=False)
                        if visible:
                            spoken.append(visible)
                            yield _sse({"delta": visible})
                        for action in actions:
                            yield _sse({"action": _perform(db, action)})
                    visible, actions, _rest = _drain(held, finished=True)
                    if visible:
                        spoken.append(visible)
                        yield _sse({"delta": visible})
                    for action in actions:
                        yield _sse({"action": _perform(db, action)})
                    yield _sse({"done": True, "model": model_name, "dev": False})
                    return
                except Exception as error:
                    record_probe(db, model_name, None, False, str(error))
                    last_error = str(error)
                    if spoken:
                        yield _sse({"delta": "……这句没说完，团子换个模型再试试。"})
            yield _sse({"delta": "这会儿外面的模型没接上。", "error": last_error[:180]})
            yield _sse({"done": True, "model": None, "dev": False})

        return StreamingResponse(events(), media_type="text/event-stream")

    @app.post("/api/actions")
    def actions(body: ActionBody, request: Request, db: Session = Depends(_db)) -> dict:
        require_access(request)
        try:
            return apply_action(db, body.name, body.text, body.minutes)
        except ValueError as error:
            raise HTTPException(status_code=400, detail=str(error)) from error

    @app.get("/api/reminders")
    def reminders(request: Request, db: Session = Depends(_db)) -> dict:
        require_access(request)
        return {"due": due_reminders(db)}

    @app.get("/api/models/status")
    def model_status(request: Request, db: Session = Depends(_db)) -> dict:
        require_access(request)
        order = ranked_models(db)
        return {"fastest": order[0] if order else None, "ranked": order[:8], "nvidia": bool(nvidia_api_key()), "dev": not nvidia_api_key()}

    @app.post("/api/models/probe")
    def probe_now(request: Request) -> dict:
        if not nvidia_allowed(request):
            raise HTTPException(status_code=401, detail="需要访问口令才能测模型")
        if not nvidia_api_key():
            return {"ok": False, "dev": True, "ranked": []}
        count = _probe_safely()
        db = session()
        try:
            return {"ok": True, "probed": count, "ranked": ranked_models(db)[:8]}
        finally:
            db.close()

    if ASSETS.is_dir():
        app.mount("/media", StaticFiles(directory=ASSETS), name="media")
    return app


def _sse(payload: dict) -> str:
    return "data: " + json.dumps(payload, ensure_ascii=False) + "\n\n"


def _system() -> list[dict]:
    return [{
        "role": "system",
        "content": (
            "你是桌面上的白猫团子，说简短的中文，温柔，不说教。"
            "你可以建议一个已经存在的动作，而且只能是这四个："
            "sleep、butterfly、groom、remind。"
            "需要时在回复最后另起一行写 [[action:{\"name\":\"groom\"}]] "
            "或 [[action:{\"name\":\"remind\",\"text\":\"喝水\",\"minutes\":20}]]。"
            "不要提终端、文件或控制电脑。"
        ),
    }]


def _clean_messages(messages: list[dict]) -> list[dict]:
    cleaned = []
    for item in messages[-12:]:
        if not isinstance(item, dict):
            continue
        role = item.get("role")
        content = item.get("content")
        if role in {"user", "assistant"} and isinstance(content, str) and content.strip():
            cleaned.append({"role": role, "content": content.strip()[:2000]})
    return cleaned


def _drain(buffer: str, finished: bool) -> tuple[str, list[dict], str]:
    actions = []
    visible = []
    while True:
        start = buffer.find("[[action:")
        if start < 0:
            if finished:
                visible.append(buffer)
                buffer = ""
            elif "[[" in buffer[-12:]:
                keep = buffer.rfind("[[")
                visible.append(buffer[:keep])
                buffer = buffer[keep:]
            else:
                visible.append(buffer)
                buffer = ""
            break
        visible.append(buffer[:start])
        end = buffer.find("]]", start)
        if end < 0:
            buffer = buffer[start:]
            break
        raw = buffer[start + len("[[action:"):end]
        buffer = buffer[end + 2:]
        try:
            payload = json.loads(raw)
        except ValueError:
            continue
        if isinstance(payload, dict) and isinstance(payload.get("name"), str):
            actions.append(payload)
    return "".join(visible), actions, buffer


def _perform(db: Session, payload: dict) -> dict:
    try:
        return apply_action(db, payload.get("name", ""), payload.get("text"), payload.get("minutes"))
    except ValueError as error:
        return {"ok": False, "detail": str(error)}


def _next_step(db: Session, recent: list[str], request: Request) -> dict | None:
    raw = get_setting(db, "activity_queue", "[]")
    try:
        queue = json.loads(raw)
    except ValueError:
        queue = []
    if not isinstance(queue, list) or not queue:
        queue = _fill_queue(db, recent, request)
        set_setting(db, "activity_queue", json.dumps(queue, ensure_ascii=False))
    if not queue:
        return None
    step = queue.pop(0)
    set_setting(db, "activity_queue", json.dumps(queue, ensure_ascii=False))
    labels = {clip["id"]: clip["label"] for clip in animation_clips()}
    labels.update({"butterfly": "捉蝴蝶", "tail": "轻摇尾巴", "tilt": "歪头看看", "hop": "开心蹦一下", "nest-breath": "猫窝呼吸"})
    step["label"] = labels.get(step["clip"], step["clip"])
    return step


def _fill_queue(db: Session, recent: list[str], request: Request) -> list[dict]:
    available = available_ids()
    if nvidia_allowed(request) and nvidia_api_key() and ranked_models(db):
        model_name = ranked_models(db)[0]
        prompt = (
            "只输出 JSON。从这些已有动作里按不那么死板的顺序挑 3 个："
            + ", ".join(sorted(available))
            + "。最近刚做过：" + ", ".join(recent[-4:])
            + '。格式 {"steps":[{"clip":"groom","pause_ms":6400}]}。'
            + "pause_ms 在 400 到 24000 之间，不要三次都一样。"
        )
        try:
            text = "".join(nvidia.stream_model(model_name, [
                {"role": "system", "content": "你只负责给桌面宠物排已经存在的动作，不发明新动作。"},
                {"role": "user", "content": prompt},
            ]))
            start = text.find("{")
            end = text.rfind("}")
            parsed = json.loads(text[start:end + 1]) if start >= 0 and end > start else {}
            steps = normalize_model_steps(parsed, available)
            if steps:
                return steps
        except Exception as error:
            record_probe(db, model_name, None, False, str(error))
    return plan_steps(recent, 3, available)


def _probe_safely() -> int:
    if not _probe_lock.acquire(blocking=False):
        return 0
    db = session()
    try:
        if not nvidia_api_key():
            return 0
        known = set(ranked_models(db))
        candidates = [model for model in nvidia.candidate_models() if model not in known]
        if len(candidates) < probe_limit():
            candidates = nvidia.candidate_models()
        count = 0
        for model_name in candidates[:probe_limit()]:
            try:
                elapsed = nvidia.probe_first_token(model_name)
                record_probe(db, model_name, elapsed, True)
            except Exception as error:
                record_probe(db, model_name, None, False, str(error))
            count += 1
        return count
    finally:
        db.close()
        _probe_lock.release()
