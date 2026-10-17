import logging
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.responses import RedirectResponse
from src.api.routes import router as api_router
from src.api.websocket import router as ws_router
from src.observability.logging_config import setup_logging
from src.config.settings import settings
from src.db.initialization import init_db
from src.agents.checkpointing import init_checkpoint_tables

logger = logging.getLogger(__name__)
setup_logging(settings.log_file, settings.log_level)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup / shutdown lifecycle for the FastAPI application."""
    try:
        await init_db()
    except Exception as exc:
        logger.warning("Database init skipped or failed during startup: %s", exc)
    try:
        init_checkpoint_tables()
    except Exception as exc:
        logger.warning("Checkpoint init skipped or failed during startup: %s", exc)
    yield


app = FastAPI(
    title="Collaborative AI Agent Orchestration",
    lifespan=lifespan,
)

app.include_router(api_router)
app.include_router(ws_router)


@app.get("/", include_in_schema=False)
async def root():
    return RedirectResponse(url="/docs")


@app.get("/health")
async def health():
    return {"status": "ok"}

