from contextlib import asynccontextmanager
import logging
from collections.abc import AsyncIterator

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import RedirectResponse
from pymongo import MongoClient
from pymongo.collection import Collection
from pymongo.errors import PyMongoError

from backend.app.config import Settings, get_request_settings, get_settings
from backend.app.routes.ai import router as ai_router
from backend.app.routes.auth import router as auth_router
from backend.app.routes.patients import router as patients_router
from backend.app.routes.records import router as records_router
from backend.app.security import require_signing_key
from backend.app.services.ai_provider import OllamaProvider
from backend.app.services.qr import patient_page_url
from backend.app.services.translation_service import TranslationService

logger = logging.getLogger(__name__)


def create_app(
    settings: Settings | None = None,
    patients_collection: object | None = None,
    health_records_collection: object | None = None,
    ai_provider: object | None = None,
    health_id_counter_collection: object | None = None,
    translation_service: object | None = None,
) -> FastAPI:
    app_settings = settings or get_settings()

    @asynccontextmanager
    async def lifespan(application: FastAPI) -> AsyncIterator[None]:
        client = None
        if patients_collection is None:
            client = MongoClient(app_settings.mongodb_uri, serverSelectionTimeoutMS=3000)
            database = client[app_settings.mongodb_database]
            collection = database["patients"]
            record_collection = database["health_records"]
            health_id_counters = database["counters"]
            application.state.mongo_client = client
            application.state.patient_id_index_ready = False
            application.state.health_record_indexes_ready = False
        else:
            collection = patients_collection
            health_id_counters = health_id_counter_collection
            application.state.patient_id_index_ready = True
        if patients_collection is not None:
            record_collection = health_records_collection
            if health_id_counters is None:
                database = getattr(patients_collection, "database", None)
                if database is None:
                    raise RuntimeError("A Health ID counter collection is required with injected patient storage.")
                health_id_counters = database["counters"]
            application.state.health_record_indexes_ready = record_collection is None
        if record_collection is None:
            raise RuntimeError("Health-record collection is not configured.")
        application.state.patients = collection
        application.state.health_records = record_collection
        application.state.health_id_counters = health_id_counters
        application.state.settings = app_settings
        application.state.ai_provider = ai_provider or OllamaProvider(app_settings)
        application.state.translation_service = translation_service or TranslationService(app_settings)
        if app_settings.jwt_secret_key:
            require_signing_key(app_settings)
        try:
            yield
        finally:
            if client is not None:
                client.close()

    application = FastAPI(
        title="Digital Health Record API",
        version="1.0.0",
        lifespan=lifespan,
    )
    application.add_middleware(
        CORSMiddleware,
        allow_origins=app_settings.allowed_origins,
        allow_credentials=False,
        allow_methods=["GET", "POST"],
        allow_headers=["Authorization", "Content-Type"],
    )
    application.include_router(auth_router)
    application.include_router(patients_router)
    application.include_router(records_router)
    application.include_router(ai_router)

    @application.get("/patient/{patient_id}", include_in_schema=False)
    def legacy_patient_link(patient_id: str, request_settings: Settings = Depends(get_request_settings)) -> RedirectResponse:
        return RedirectResponse(
            patient_page_url(request_settings.frontend_base_url, patient_id),
            status_code=307,
        )

    @application.get("/api/health", tags=["health"])
    def health(request: Request) -> dict[str, str]:
        client = getattr(request.app.state, "mongo_client", None)
        if client is None:
            return {"status": "ok", "database": "test-injected"}
        try:
            client.admin.command("ping")
        except PyMongoError as exc:
            logger.exception("MongoDB health check failed.")
            raise HTTPException(status_code=503, detail="MongoDB is unavailable.") from exc
        return {"status": "ok", "database": "connected"}

    return application


app = create_app()
