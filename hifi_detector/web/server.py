"""FastAPI server for HIFI Detector Web UI."""

from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware

from .routes import router

STATIC_DIR = Path(__file__).parent / "static"

app = FastAPI(
    title="HIFI Detector",
    description="Audio quality and authenticity analysis — interactive web interface",
    version="0.1.0",
)

# CORS — allow all origins for development
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(router)

# Serve static files (SPA)
if STATIC_DIR.exists():
    app.mount("/", StaticFiles(directory=str(STATIC_DIR), html=True), name="static")


def run(host: str = "127.0.0.1", port: int = 8099):
    """Start the uvicorn server."""
    import uvicorn
    uvicorn.run(app, host=host, port=port, log_level="info")
