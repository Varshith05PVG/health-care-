import asyncio
from io import BytesIO
import logging
from typing import Literal

import httpx
from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from pymongo.collection import Collection
from pymongo.errors import PyMongoError
from starlette.concurrency import run_in_threadpool

from backend.app.db import get_health_records_collection
from backend.app.schemas import AIAnswer, AIQuery
from backend.app.security import get_current_patient
from backend.app.services.speech_recognition import SpeechRecognitionUnavailable, transcribe_audio
from backend.app.services.ai_provider import OllamaModelUnavailable, OllamaProvider, OllamaUnavailable
from backend.app.services.retrieval import (
    build_record_context,
    retrieve_relevant_records,
    validate_extractive_answer,
)
from backend.app.services.translation_service import (
    TranslationService,
    TranslationUnavailable,
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/ai", tags=["record assistance"])
NO_RECORDS_ANSWER = "I could not find that information in your recorded health records."
DISCLAIMER = (
    "This information is based on your recorded health records and is not a medical diagnosis "
    "or a substitute for professional medical advice."
)
MAX_SPEECH_AUDIO_BYTES = 10 * 1024 * 1024


async def translate_assistant_text(
    text: str,
    source_language: str,
    target_language: str,
    provider: OllamaProvider,
    translator: TranslationService,
    request: Request,
) -> str:
    try:
        return await translator.translate(text, source_language, target_language)
    except TranslationUnavailable:
        try:
            await provider.ensure_translation_model_available()
        except OllamaUnavailable as exc:
            raise HTTPException(
                status_code=503,
                detail="Translation is unavailable. Start local Ollama or configure Bhashini or Google Translation.",
            ) from exc
        except OllamaModelUnavailable as exc:
            raise HTTPException(
                status_code=503,
                detail=(
                    "The local translation model "
                    f"'{request.app.state.settings.ollama_translation_model}' is not installed. "
                    "Install it or configure Bhashini or Google Translation."
                ),
            ) from exc
        try:
            return await provider.translate(text, source_language, target_language)
        except httpx.HTTPError as exc:
            logger.warning("Local fallback translation could not reach Ollama.")
            raise HTTPException(
                status_code=503,
                detail="Local translation failed. Check Ollama and try again.",
            ) from exc
        except ValueError as exc:
            logger.warning("Local fallback translation returned an invalid response.")
            raise HTTPException(
                status_code=503,
                detail="The local model could not translate this text. Please try again.",
            ) from exc


@router.get("/health")
async def ai_health(request: Request) -> dict:
    provider: OllamaProvider = request.app.state.ai_provider
    translator: TranslationService = request.app.state.translation_service
    ollama_available, model_available = await provider.health()
    bhashini_available, google_available = await asyncio.gather(
        translator.check_bhashini(),
        translator.check_google(),
    )
    try:
        await provider.ensure_translation_model_available()
        local_translation_available = True
    except (OllamaUnavailable, OllamaModelUnavailable):
        local_translation_available = False
    return {
        "ollama": ollama_available,
        "model": request.app.state.settings.ollama_model,
        "model_available": model_available,
        "translation": bhashini_available or google_available or local_translation_available,
        "local_translation_model": request.app.state.settings.ollama_translation_model,
        "local_translation_model_available": local_translation_available,
        "bhashini": bhashini_available,
        "bhashini_configured": translator.bhashini_configured,
        "google_translation": google_available,
        "google_translation_configured": translator.google_configured,
    }


@router.post("/transcribe")
async def transcribe_question(
    request: Request,
    audio: UploadFile = File(...),
    language: Literal["en", "te", "hi"] = Form(default="en"),
    _patient_id: str = Depends(get_current_patient),
) -> dict[str, str]:
    audio_bytes = await audio.read(MAX_SPEECH_AUDIO_BYTES + 1)
    if not audio_bytes:
        raise HTTPException(status_code=422, detail="Record a voice question before submitting.")
    if len(audio_bytes) > MAX_SPEECH_AUDIO_BYTES:
        raise HTTPException(status_code=413, detail="The voice recording is too large. Record a shorter question.")

    try:
        text = await run_in_threadpool(
            transcribe_audio,
            BytesIO(audio_bytes),
            language,
            request.app.state.settings.whisper_model,
        )
    except SpeechRecognitionUnavailable as exc:
        logger.warning("Local speech recognition is unavailable.")
        raise HTTPException(status_code=503, detail=str(exc)) from exc

    if not text:
        raise HTTPException(status_code=422, detail="No speech was recognized. Try again or type your question.")
    return {"text": text}


@router.post("/interpret")
async def interpret_speech(
    request: Request,
    audio: UploadFile = File(...),
    source_language: Literal["en", "te", "hi"] = Form(...),
    target_language: Literal["en", "te", "hi"] = Form(...),
    _patient_id: str = Depends(get_current_patient),
) -> dict[str, str]:
    if source_language == target_language:
        raise HTTPException(status_code=422, detail="Choose two different languages to interpret.")
    audio_bytes = await audio.read(MAX_SPEECH_AUDIO_BYTES + 1)
    if not audio_bytes:
        raise HTTPException(status_code=422, detail="Record speech before requesting interpretation.")
    if len(audio_bytes) > MAX_SPEECH_AUDIO_BYTES:
        raise HTTPException(status_code=413, detail="The recording is too large. Record a shorter turn.")

    provider: OllamaProvider = request.app.state.ai_provider
    try:
        await provider.ensure_translation_model_available()
    except OllamaUnavailable as exc:
        raise HTTPException(
            status_code=503,
            detail="Local Ollama is unavailable. Start Ollama and try again.",
        ) from exc
    except OllamaModelUnavailable as exc:
        raise HTTPException(
            status_code=503,
            detail=(
                "The configured local translation model "
                f"'{request.app.state.settings.ollama_translation_model}' is not installed."
            ),
        ) from exc

    try:
        transcript = await run_in_threadpool(
            transcribe_audio,
            BytesIO(audio_bytes),
            source_language,
            request.app.state.settings.whisper_model,
        )
        if not transcript:
            raise HTTPException(
                status_code=422,
                detail="No speech was recognized. Try again or type the message.",
            )
        translation = await provider.translate(transcript, source_language, target_language)
    except SpeechRecognitionUnavailable as exc:
        logger.warning("Local speech recognition is unavailable.")
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except httpx.HTTPError as exc:
        logger.warning("The local interpreter could not reach Ollama.")
        raise HTTPException(
            status_code=503,
            detail="Local translation failed. Check Ollama and try again.",
        ) from exc
    except ValueError as exc:
        logger.warning("The local interpreter returned an invalid translation.")
        raise HTTPException(
            status_code=503,
            detail="The local interpreter could not produce a translation. Please try again.",
        ) from exc

    return {"transcript": transcript, "translation": translation}


@router.post("/query", response_model=AIAnswer)
async def query_records(
    query: AIQuery,
    request: Request,
    patient_id: str = Depends(get_current_patient),
    collection: Collection = Depends(get_health_records_collection),
) -> dict:
    provider: OllamaProvider = request.app.state.ai_provider
    translator: TranslationService = request.app.state.translation_service
    search_question = query.question
    if query.language != "en":
        search_question = await translate_assistant_text(
            query.question,
            query.language,
            "en",
            provider,
            translator,
            request,
        )

    try:
        await provider.ensure_model_available()
    except OllamaUnavailable as exc:
        raise HTTPException(
            status_code=503,
            detail="Ollama is unavailable. Start the local Ollama service and try again.",
        ) from exc
    except OllamaModelUnavailable as exc:
        raise HTTPException(
            status_code=503,
            detail=f"The configured Ollama model '{request.app.state.settings.ollama_model}' is not installed.",
        ) from exc

    try:
        records = list(
            collection.find({"$or": [{"patient_id": patient_id}, {"health_id": patient_id}]})
        )
    except PyMongoError as exc:
        logger.exception("MongoDB failed while retrieving AI context.")
        raise HTTPException(status_code=503, detail="Health-record storage is currently unavailable.") from exc

    relevant = retrieve_relevant_records(records, search_question)
    if not relevant:
        answer = NO_RECORDS_ANSWER
        if query.language != "en":
            answer = await translate_assistant_text(
                answer,
                "en",
                query.language,
                provider,
                translator,
                request,
            )
        return {
            "answer": answer,
            "sources": [],
            "language": query.language,
            "translated_question": search_question if query.language != "en" else None,
            "disclaimer": DISCLAIMER,
        }

    try:
        raw_answer = await provider.answer(search_question, build_record_context(relevant))
    except httpx.HTTPError as exc:
        logger.warning("The local Ollama health-record assistant could not answer the request.")
        raise HTTPException(
            status_code=503,
            detail="Ollama became unavailable while preparing the answer. Check the local service and try again.",
        ) from exc
    except ValueError as exc:
        logger.warning("The local Ollama health-record assistant returned an invalid response.")
        raise HTTPException(
            status_code=503,
            detail="The local AI returned an invalid response. Please try again.",
        ) from exc
    answer, sources = validate_extractive_answer(raw_answer, relevant)
    if query.language != "en":
        answer = await translate_assistant_text(
            answer,
            "en",
            query.language,
            provider,
            translator,
            request,
        )
    return {
        "answer": answer,
        "sources": sources,
        "language": query.language,
        "translated_question": search_question if query.language != "en" else None,
        "disclaimer": DISCLAIMER,
    }
