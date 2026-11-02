from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, Request, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field, StringConstraints
from typing import Annotated

from constants import MAX_MESSAGE_LENGTH, PROJECT_ROOT, VISITOR_COOKIE, VISITOR_COOKIE_MAX_AGE

from .domain.knowledge import Knowledge
from .orchestration.flow import build_flow
from .model.deepseek import configured_model
from .storage.store import Store

class Chat(BaseModel):
    message: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=MAX_MESSAGE_LENGTH)]


class Confirm(BaseModel):
    ticket: str = Field(pattern=r"^P-[0-9a-f]{16}$")


def create_app(store=None, model_factory=configured_model):
    @asynccontextmanager
    async def lifespan(app):
        model = model_factory()
        app.state.db = store or Store()
        app.state.flow = build_flow(app.state.db, Knowledge(PROJECT_ROOT / "knowledge"), model)
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
        return app.state.flow.invoke({"message": body.message, "session": visitor})["result"]

    @app.post("/api/refunds/confirm")
    def confirm(body: Confirm, visitor=Depends(session)):
        return app.state.db.confirm(visitor["id"], body.ticket)

    @app.get("/api/refunds/{ref}")
    def refund(ref: str, visitor=Depends(session)):
        return app.state.db.refund(visitor["id"], ref)

    app.mount("/", StaticFiles(directory=PROJECT_ROOT / "service/static", html=True), name="web")
    return app


app = create_app()
