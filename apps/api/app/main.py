import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, status
from fastapi.responses import JSONResponse

from app.core.config import get_settings
from app.core.login_throttle import build_login_throttle, close_login_throttle
from app.routers.auth import router as auth_router
from app.routers.imports import router as imports_router
from app.routers.measurements import router as measurements_router
from app.routers.dashboard import router as dashboard_router
from app.routers.registry import router as registry_router
from app.routers.users import router as users_router
from app.routers.production import router as production_router
from app.routers.reviews import router as reviews_router
from app.services.approval import (
    ConcurrentReviewError,
    LineNotFoundError,
    MissingMeasurementDateError,
    ReplacementReasonRequiredError,
    UnmatchedAnimalError,
)
from app.services.ingestion import (
    DuplicateImageError,
    ImageTooLargeError,
    ImportAlreadyProcessingError,
    ImportNotFoundError,
    InvalidImageError,
)


def _configure_logging() -> None:
    # uvicorn only configures its own `uvicorn`/`uvicorn.access` loggers, not
    # the root logger — every `logging.getLogger(__name__).info(...)` call
    # in app.services/app.workers was silently dropped without this, found
    # by checking real container logs and seeing only uvicorn's HTTP access
    # lines, none of the domain events.
    app_logger = logging.getLogger("app")
    if not app_logger.handlers:
        handler = logging.StreamHandler()
        handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s"))
        app_logger.addHandler(handler)
    app_logger.setLevel(logging.INFO)
    app_logger.propagate = False


@asynccontextmanager
async def _lifespan(app: FastAPI) -> AsyncIterator[None]:
    # O limitador de login abre um cliente Redis assíncrono, que pertence ao
    # event loop da aplicação: nasce e morre com ela.
    throttle = build_login_throttle(get_settings().redis_url)
    app.state.login_throttle = throttle
    try:
        yield
    finally:
        await close_login_throttle(throttle)


def create_app() -> FastAPI:
    _configure_logging()
    get_settings()
    app = FastAPI(title="Belo Vale Ingestion API", lifespan=_lifespan)
    app.include_router(auth_router)
    app.include_router(imports_router)
    app.include_router(reviews_router)
    app.include_router(measurements_router)
    app.include_router(registry_router)
    app.include_router(users_router)
    app.include_router(dashboard_router)
    app.include_router(production_router)

    @app.get("/healthz")
    def healthz() -> dict[str, str]:
        return {"status": "ok"}

    @app.exception_handler(DuplicateImageError)
    async def handle_duplicate_image(request: Request, exc: DuplicateImageError) -> JSONResponse:
        return JSONResponse(
            status_code=status.HTTP_409_CONFLICT,
            content={"code": "duplicate_image", "existing_import_id": str(exc.existing_import_id)},
        )

    @app.exception_handler(ImportAlreadyProcessingError)
    async def handle_already_processing(
        request: Request, exc: ImportAlreadyProcessingError
    ) -> JSONResponse:
        return JSONResponse(
            status_code=status.HTTP_409_CONFLICT,
            content={"code": "import_already_processing"},
        )

    @app.exception_handler(ImportNotFoundError)
    async def handle_import_not_found(request: Request, exc: ImportNotFoundError) -> JSONResponse:
        return JSONResponse(
            status_code=status.HTTP_404_NOT_FOUND,
            content={"code": "import_not_found"},
        )

    @app.exception_handler(InvalidImageError)
    async def handle_invalid_image(request: Request, exc: InvalidImageError) -> JSONResponse:
        return JSONResponse(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            content={"code": "invalid_image", "detail": str(exc)},
        )

    @app.exception_handler(ImageTooLargeError)
    async def handle_image_too_large(request: Request, exc: ImageTooLargeError) -> JSONResponse:
        return JSONResponse(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            content={"code": "image_too_large", "detail": str(exc)},
        )

    @app.exception_handler(LineNotFoundError)
    async def handle_line_not_found(request: Request, exc: LineNotFoundError) -> JSONResponse:
        return JSONResponse(
            status_code=status.HTTP_404_NOT_FOUND,
            content={"code": "line_not_found"},
        )

    @app.exception_handler(ConcurrentReviewError)
    async def handle_concurrent_review(request: Request, exc: ConcurrentReviewError) -> JSONResponse:
        return JSONResponse(
            status_code=status.HTTP_409_CONFLICT,
            content={"code": "stale_decision"},
        )

    @app.exception_handler(UnmatchedAnimalError)
    async def handle_unmatched_animal(request: Request, exc: UnmatchedAnimalError) -> JSONResponse:
        return JSONResponse(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            content={"code": "unmatched_animal"},
        )

    @app.exception_handler(MissingMeasurementDateError)
    async def handle_missing_measurement_date(
        request: Request, exc: MissingMeasurementDateError
    ) -> JSONResponse:
        return JSONResponse(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            content={"code": "missing_measurement_date"},
        )

    @app.exception_handler(ReplacementReasonRequiredError)
    async def handle_replacement_reason_required(
        request: Request, exc: ReplacementReasonRequiredError
    ) -> JSONResponse:
        return JSONResponse(
            status_code=status.HTTP_409_CONFLICT,
            content={"code": "replacement_reason_required"},
        )

    return app
