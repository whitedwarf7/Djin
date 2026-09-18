"""Server-side speech: transcription and synthesis via an OpenAI-compatible audio API.

Only used when DJIN_STT_PROVIDER / DJIN_TTS_PROVIDER are set to "openai". The default
"browser" mode keeps all audio inside the page using the Web Speech API.
"""

from __future__ import annotations

import httpx

from djin.config import Settings, get_settings


class VoiceError(RuntimeError):
    """Raised when speech input or output cannot be produced."""


# Extension is what most transcription APIs key off, so map the mime type we trust.
AUDIO_TYPES = {
    "audio/webm": "webm",
    "audio/ogg": "ogg",
    "audio/wav": "wav",
    "audio/x-wav": "wav",
    "audio/wave": "wav",
    "audio/mpeg": "mp3",
    "audio/mp4": "mp4",
    "audio/m4a": "m4a",
    "audio/x-m4a": "m4a",
    "audio/flac": "flac",
}

TTS_FORMATS = {"mp3": "audio/mpeg", "opus": "audio/ogg", "wav": "audio/wav"}
MAX_TTS_CHARS = 4000


def _headers(settings: Settings) -> dict[str, str]:
    return {"Authorization": f"Bearer {settings.voice_key}"}


def _check_response(response: httpx.Response, what: str) -> None:
    if response.status_code >= 400:
        detail = response.text[:300] if response.content else ""
        raise VoiceError(f"{what} failed ({response.status_code}): {detail}")


def transcribe(
    audio: bytes,
    content_type: str,
    language: str | None = None,
    settings: Settings | None = None,
) -> str:
    settings = settings or get_settings()
    if not settings.server_stt_ready:
        raise VoiceError(
            "Server-side transcription is off. Set DJIN_STT_PROVIDER=openai and DJIN_VOICE_API_KEY."
        )
    if not audio:
        raise VoiceError("No audio was received.")
    if len(audio) > settings.max_audio_bytes:
        raise VoiceError(f"Audio is larger than the {settings.max_audio_bytes} byte limit.")

    base_type = (content_type or "").split(";")[0].strip().lower()
    extension = AUDIO_TYPES.get(base_type)
    if extension is None:
        raise VoiceError(f"Unsupported audio type '{base_type or 'unknown'}'.")

    data = {"model": settings.stt_model}
    if code := (language or settings.voice_language):
        data["language"] = code.split("-")[0]

    try:
        response = httpx.post(
            f"{settings.voice_base_url.rstrip('/')}/audio/transcriptions",
            headers=_headers(settings),
            data=data,
            files={"file": (f"speech.{extension}", audio, base_type)},
            timeout=settings.voice_timeout,
        )
    except httpx.HTTPError as exc:
        raise VoiceError(f"Could not reach the transcription service: {exc}") from exc

    _check_response(response, "Transcription")
    try:
        text = response.json().get("text", "")
    except ValueError:
        text = response.text
    return text.strip()


def synthesise(
    text: str,
    voice: str | None = None,
    fmt: str = "mp3",
    settings: Settings | None = None,
) -> tuple[bytes, str]:
    """Returns (audio bytes, media type)."""
    settings = settings or get_settings()
    if not settings.server_tts_ready:
        raise VoiceError(
            "Server-side speech is off. Set DJIN_TTS_PROVIDER=openai and DJIN_VOICE_API_KEY."
        )
    spoken = text.strip()
    if not spoken:
        raise VoiceError("Nothing to speak.")
    if len(spoken) > MAX_TTS_CHARS:
        spoken = spoken[:MAX_TTS_CHARS]

    media_type = TTS_FORMATS.get(fmt)
    if media_type is None:
        raise VoiceError(f"Unsupported audio format '{fmt}'.")

    try:
        response = httpx.post(
            f"{settings.voice_base_url.rstrip('/')}/audio/speech",
            headers=_headers(settings),
            json={
                "model": settings.tts_model,
                "voice": voice or settings.tts_voice,
                "input": spoken,
                "response_format": fmt,
            },
            timeout=settings.voice_timeout,
        )
    except httpx.HTTPError as exc:
        raise VoiceError(f"Could not reach the speech service: {exc}") from exc

    _check_response(response, "Speech synthesis")
    return response.content, media_type


def client_config(settings: Settings | None = None) -> dict[str, object]:
    """What the browser needs to decide how to capture and play speech."""
    settings = settings or get_settings()
    return {
        "enabled": settings.voice_enabled,
        "stt": settings.stt_provider,
        "tts": settings.tts_provider,
        "language": settings.voice_language,
        "voice": settings.tts_voice,
        "server_stt_ready": settings.server_stt_ready,
        "server_tts_ready": settings.server_tts_ready,
        "max_audio_bytes": settings.max_audio_bytes,
    }
