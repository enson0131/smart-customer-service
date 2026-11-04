import json
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, Request, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field, StringConstraints
from typing import Annotated, Literal

from constants import MAX_MESSAGE_LENGTH, PROJECT_ROOT, VISITOR_COOKIE, VISITOR_COOKIE_MAX_AGE

from .domain.knowledge import Knowledge
from .storage.checkpoints import open_checkpointer
from .orchestration.conversation import Conversation
from .orchestration.flow import build_flow
from .model.deepseek import configured_model
from .storage.store import Store
from .task_log import task_logger

class SelectOrder(BaseModel):
    kind: Literal["select_order"]
    order_id: str = Field(pattern=r"^O-[0-9a-f]{16}$")


class CancelPending(BaseModel):
    kind: Literal["cancel_pending"]


ChatId = Annotated[str, Field(pattern=r"^C-[0-9a-f]{16}$")]


class Chat(BaseModel):
    chat_id: ChatId
    action: SelectOrder | CancelPending | None = None
    message: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=MAX_MESSAGE_LENGTH)]


class Confirm(BaseModel):
    chat_id: ChatId
    ticket: str = Field(pattern=r"^P-[0-9a-f]{16}$")


def create_app(store=None, model_factory=configured_model):
    @asynccontextmanager
    async def lifespan(app):
        model = model_factory()
        app.state.db = store or Store()
        log_dir = app.state.db.path.parent / "logs"
        with open_checkpointer(app.state.db) as saver, task_logger(log_dir) as logger:
            graph = build_flow(app.state.db, Knowledge(PROJECT_ROOT / "knowledge"), model, saver)
            app.state.conversation = Conversation(graph, app.state.db, saver, logger)
            yield

    app = FastAPI(title="智能售后客服 · 售后演示", lifespan=lifespan)

    def current_visitor(request: Request, response: Response):
        cookie = request.cookies.get(VISITOR_COOKIE)
        visitor = app.state.db.visitor(cookie)
        response.headers["Cache-Control"] = "no-store"
        if visitor["id"] != cookie:
            response.set_cookie(VISITOR_COOKIE, visitor["id"], httponly=True, samesite="strict",
                                secure=request.url.scheme == "https",
                                max_age=VISITOR_COOKIE_MAX_AGE)
        return visitor

    @app.get("/health")
    def health():
        return {"status": "ok"}

    @app.get("/api/orders")
    def orders(visitor=Depends(current_visitor)):
        return app.state.db.orders(visitor["id"])

    @app.post("/api/chats", status_code=201)
    def create_chat(visitor=Depends(current_visitor)):
        chat = app.state.db.create_chat(visitor["id"])
        return {"id": chat["id"]}

    @app.get("/api/chats")
    def list_chats(visitor=Depends(current_visitor)):
        return app.state.db.chats(visitor["id"])

    @app.get("/api/chats/{chat_id}")
    def read_chat(chat_id: ChatId, visitor=Depends(current_visitor)):
        app.state.db.chat(visitor["id"], chat_id)
        turns = app.state.db.messages(chat_id)
        return {"id": chat_id, "turns": [
            {"message": turn["message"], "reply": json.loads(turn["answer"])} for turn in turns
        ]}

    @app.post("/api/chat")
    def chat(body: Chat, visitor=Depends(current_visitor)):
        action = body.action.model_dump() if body.action else None
        return app.state.conversation.respond(visitor["id"], body.chat_id, body.message, action)

    @app.post("/api/refunds/confirm")
    def confirm(body: Confirm, visitor=Depends(current_visitor)):
        result = app.state.db.confirm(visitor["id"], body.chat_id, body.ticket)
        app.state.db.record_turn(body.chat_id, "确认提交", {"text": result["id"] + " · " + result["status"], "sources": []})
        return result

    @app.get("/api/refunds/{ref}")
    def refund(ref: str, visitor=Depends(current_visitor)):
        return app.state.db.refund(visitor["id"], ref)

    app.mount("/", StaticFiles(directory=PROJECT_ROOT / "service/static", html=True), name="web")
    return app


app = create_app()
