from fastapi import FastAPI

from app.core.config import get_settings


def create_app() -> FastAPI:
    get_settings()
    app = FastAPI(title="Belo Vale Ingestion API")

    @app.get("/healthz")
    def healthz() -> dict[str, str]:
        return {"status": "ok"}

    return app
