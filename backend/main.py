"""ASGI application."""

from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from backend.review_routes import router as review_router
from backend.routes import router

app = FastAPI(title="Sure for Sure", version="0.1.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173"],
    allow_methods=["*"],
    allow_headers=["*"],
)
app.include_router(router, prefix="/api")
app.include_router(review_router, prefix="/api/human-review")

_FRONTEND_DIST = Path(__file__).resolve().parents[1] / "frontend" / "dist"
if (_FRONTEND_DIST / "assets").is_dir():
    app.mount("/assets", StaticFiles(directory=_FRONTEND_DIST / "assets"), name="assets")


@app.get("/human-review", include_in_schema=False)
@app.get("/human-review/{path:path}", include_in_schema=False)
def human_review_ui(path: str = "") -> FileResponse:
    index = _FRONTEND_DIST / "index.html"
    if not index.is_file():
        raise HTTPException(
            status_code=503,
            detail="Build the frontend before launching the local human-review UI.",
        )
    return FileResponse(index)
