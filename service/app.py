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


class Chat(BaseModel):
    action: SelectOrder | CancelPending | None = None
    message: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=MAX_MESSAGE_LENGTH)]


class Confirm(BaseModel):
    ticket: str = Field(pattern=r"^P-[0-9a-f]{16}$")


def create_app(store=None, model_factory=configured_model):
    @asynccontextmanager
    async def lifespan(app):
        model = model_factory()
        app.state.db = store or Store()
        log_dir = None if app.state.db.remote else app.state.db.path.parent / "logs"
        with open_checkpointer(app.state.db) as saver, task_logger(log_dir) as logger:
            graph = build_flow(app.state.db, Knowledge(PROJECT_ROOT / "knowledge"), model, saver)
            app.state.conversation = Conversation(graph, app.state.db, saver, logger)
            yield

    app = FastAPI(title="云杉生活 · 售后演示", lifespan=lifespan)

    def session(request: Request, response: Response):
        cookie = request.cookies.get(VISITOR_COOKIE)
        visitor = app.state.db.session(cookie)
        response.headers["Cache-Control"] = "no-store"
        if visitor["id"] != cookie:
            response.set_cookie(VISITOR_COOKIE, visitor["id"], httponly=True, samesite="strict",
                                secure=request.url.scheme == "https" or app.state.db.remote,
                                max_age=VISITOR_COOKIE_MAX_AGE)
        return visitor

    @app.get("/health")
    def health():
        return {"status": "ok"}

    @app.get("/api/orders")
    def orders(visitor=Depends(session)):
        return app.state.db.orders(visitor["id"])

    @app.post("/api/chat")
    def chat(body: Chat, visitor=Depends(session)):
        action = body.action.model_dump() if body.action else None
        return app.state.conversation.respond(visitor, body.message, action)

    @app.post("/api/refunds/confirm")
    def confirm(body: Confirm, visitor=Depends(session)):
        return app.state.db.confirm(visitor["id"], body.ticket)

    @app.get("/api/refunds/{ref}")
    def refund(ref: str, visitor=Depends(session)):
        return app.state.db.refund(visitor["id"], ref)

    app.mount("/", StaticFiles(directory=PROJECT_ROOT / "service/static", html=True), name="web")
    return app


app = create_app()
