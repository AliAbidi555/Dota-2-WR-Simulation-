"""
Dota 2 Performance Tracker API
Powered by OpenDota (https://docs.opendota.com/)
"""

from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app.client import close_client
from app.probability import get_model
from app.routes import players, matches, friends, dashboard, heroes, analytics
from app.routes import probability as probability_router

STATIC_DIR = Path(__file__).resolve().parent.parent / "static"
DASHBOARD_HTML = STATIC_DIR / "dashboard.html"


@asynccontextmanager
async def lifespan(app: FastAPI):
    import asyncio
    loop = asyncio.get_event_loop()
    await loop.run_in_executor(None, get_model)   # warm up singleton at startup
    yield
    await close_client()


app = FastAPI(
    title="Dota 2 Performance Tracker",
    description=(
        "Track your friends' Dota 2 performance using the OpenDota API. "
        "Add friends by Steam account ID, then hit /dashboard for a full snapshot."
    ),
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(players.router)
app.include_router(matches.router)
app.include_router(friends.router)
app.include_router(dashboard.router)
app.include_router(heroes.router)
app.include_router(analytics.router)
app.include_router(probability_router.router)

if STATIC_DIR.exists():
    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


@app.get("/", include_in_schema=False)
async def root():
    if DASHBOARD_HTML.exists():
        return FileResponse(str(DASHBOARD_HTML))
    return {
        "message": "Dota 2 Performance Tracker API",
        "docs": "/docs",
        "dashboard": "Place dashboard.html in the static/ directory to serve it here.",
    }
