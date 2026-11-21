import logging
from typing import Any

import httpx

from backend.app.config import Settings

logger = logging.getLogger(__name__)
BHASHINI_INFERENCE_URL = "https://dhruva-api.bhashini.gov.in/services/inference/pipeline"
GOOGLE_TRANSLATE_URL = "https://translation.googleapis.com/language/translate/v2"
SUPPORTED_LANGUAGES = {"en", "te", "hi"}


class TranslationUnavailable(Exception):
    pass


class BhashiniUnavailable(TranslationUnavailable):
    pass


class TranslationService:
    def __init__(self, settings: Settings):
        self.settings = settings
        self._pipeline_cache: dict[tuple[str, str], dict[str, Any]] = {}

    @property
    def bhashini_configured(self) -> bool:
        return all(
            (
                self.settings.bhashini_api_url,
                self.settings.bhashini_user_id,
                self.settings.bhashini_api_key,
                self.settings.bhashini_pipeline_id,
            )
        )

    @property
    def google_configured(self) -> bool:
        return bool(self.settings.google_translate_api_key)

    @property
    def configured(self) -> bool:
        return self.bhashini_configured or self.google_configured

    async def translate(self, text: str, source: str, target: str) -> str:
        if source == target:
            return text
        if source not in SUPPORTED_LANGUAGES or target not in SUPPORTED_LANGUAGES:
            raise ValueError("The requested language pair is not supported.")
        failures: list[Exception] = []

        if self.bhashini_configured:
            try:
                return await self._translate_with_bhashini(text, source, target)
            except (httpx.HTTPError, KeyError, TypeError, ValueError) as exc:
                logger.warning("Bhashini translation request failed.")
                failures.append(exc)

        if self.google_configured:
            try:
                return await self._translate_with_google(text, source, target)
            except (httpx.HTTPError, KeyError, TypeError, ValueError) as exc:
                logger.warning("Google Cloud Translation request failed.")
                failures.append(exc)

        if failures:
            raise TranslationUnavailable("Configured translation providers are unavailable.") from failures[-1]
        if self.bhashini_configured:
            raise BhashiniUnavailable("Bhashini is unavailable.")
        raise BhashiniUnavailable("Bhashini is not configured.")

    async def check_bhashini(self) -> bool:
        if not self.bhashini_configured:
            return False
        try:
            await self._get_bhashini_pipeline("en", "te")
        except (httpx.HTTPError, KeyError, TypeError, ValueError):
            logger.warning("Bhashini health check failed.")
            return False
        return True

    async def check_google(self) -> bool:
        if not self.google_configured:
            return False
        try:
            async with httpx.AsyncClient(timeout=self.settings.translation_timeout_seconds) as client:
                response = await client.get(
                    f"{GOOGLE_TRANSLATE_URL}/languages",
                    params={"key": self.settings.google_translate_api_key, "target": "en"},
                )
                response.raise_for_status()
        except httpx.HTTPError:
            logger.warning("Google Translation health check failed.")
            return False
        return True

    async def _get_bhashini_pipeline(self, source: str, target: str) -> dict[str, Any]:
        key = (source, target)
        if key in self._pipeline_cache:
            return self._pipeline_cache[key]

        payload = {
            "pipelineTasks": [
                {
                    "taskType": "translation",
                    "config": {"language": {"sourceLanguage": source, "targetLanguage": target}},
                }
            ],
            "pipelineRequestConfig": {"pipelineId": self.settings.bhashini_pipeline_id},
        }
        async with httpx.AsyncClient(timeout=self.settings.translation_timeout_seconds) as client:
            response = await client.post(
                self.settings.bhashini_api_url,
                json=payload,
                headers={
                    "userID": self.settings.bhashini_user_id,
                    "ulcaApiKey": self.settings.bhashini_api_key,
                    "Content-Type": "application/json",
                },
            )
            response.raise_for_status()
        result = response.json()
        endpoint = result["pipelineInferenceAPIEndPoint"]
        response_config = result["pipelineResponseConfig"]
        service_id = next(
            (
                config.get("serviceId")
                for task in response_config
                if task.get("taskType") == "translation"
                for config in task.get("config", [])
                if config.get("language", {}).get("sourceLanguage") == source
                and config.get("language", {}).get("targetLanguage") == target
            ),
            None,
        )
        if not isinstance(service_id, str) or not service_id:
            raise ValueError("Bhashini has no translation model for this language pair.")
        pipeline = {
            "callback_url": endpoint["callbackUrl"],
            "header_name": endpoint["inferenceApiKey"]["name"],
            "header_value": endpoint["inferenceApiKey"]["value"],
            "service_id": service_id,
        }
        self._pipeline_cache[key] = pipeline
        return pipeline

    async def _translate_with_bhashini(self, text: str, source: str, target: str) -> str:
        pipeline = await self._get_bhashini_pipeline(source, target)
        payload = {
            "pipelineTasks": [
                {
                    "taskType": "translation",
                    "config": {
                        "language": {"sourceLanguage": source, "targetLanguage": target},
                        "serviceId": pipeline["service_id"],
                        "isSentence": True,
                    },
                }
            ],
            "inputData": {"input": [{"source": text}]},
        }
        async with httpx.AsyncClient(timeout=self.settings.translation_timeout_seconds) as client:
            response = await client.post(
                pipeline["callback_url"],
                json=payload,
                headers={
                    pipeline["header_name"]: pipeline["header_value"],
                    "Content-Type": "application/json",
                },
            )
            response.raise_for_status()
        result = response.json()
        translated = result["pipelineResponse"][0]["output"][0]["target"]
        if isinstance(translated, list):
            translated = translated[0] if translated else None
        if not isinstance(translated, str) or not translated.strip():
            raise ValueError("Bhashini returned no translated text.")
        return translated.strip()

    async def _translate_with_google(self, text: str, source: str, target: str) -> str:
        async with httpx.AsyncClient(timeout=self.settings.translation_timeout_seconds) as client:
            response = await client.post(
                GOOGLE_TRANSLATE_URL,
                params={"key": self.settings.google_translate_api_key},
                json={"q": text, "source": source, "target": target, "format": "text"},
            )
            response.raise_for_status()
        translated = response.json()["data"]["translations"][0]["translatedText"]
        if not isinstance(translated, str) or not translated.strip():
            raise ValueError("Google Translation returned no translated text.")
        return translated.strip()
