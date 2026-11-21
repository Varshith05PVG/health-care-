from functools import lru_cache
from typing import BinaryIO, Literal

SpeechLanguage = Literal["en", "te", "hi"]


class SpeechRecognitionUnavailable(RuntimeError):
    pass


@lru_cache(maxsize=1)
def _get_model(model_name: str):
    try:
        from faster_whisper import WhisperModel
    except ImportError as exc:
        raise SpeechRecognitionUnavailable(
            "Local speech recognition is not installed. Install the backend requirements and restart the server."
        ) from exc

    try:
        return WhisperModel(model_name, device="cpu", compute_type="int8")
    except (OSError, RuntimeError, ValueError) as exc:
        raise SpeechRecognitionUnavailable(
            "The local speech model could not be loaded. Check the server connection for its first download, then try again."
        ) from exc


def transcribe_audio(
    audio_file: BinaryIO,
    language: SpeechLanguage,
    model_name: str,
) -> str:
    model = _get_model(model_name)
    try:
        segments, _ = model.transcribe(
            audio_file,
            language=language,
            beam_size=1,
            vad_filter=True,
        )
        return " ".join(segment.text.strip() for segment in segments).strip()
    except (OSError, RuntimeError, ValueError) as exc:
        raise SpeechRecognitionUnavailable(
            "The local speech model could not process this recording. Please try again or type your question."
        ) from exc
