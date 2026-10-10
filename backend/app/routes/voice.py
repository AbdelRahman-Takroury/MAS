"""Optional Azure Arabic voice, ported from Mo3taz; credentials never leave server."""
import html
import re
from collections import OrderedDict
from threading import Lock
from time import monotonic
from urllib.request import Request, urlopen
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Response
from sqlalchemy.orm import Session
from ..config import settings
from ..database import get_db
from ..schemas.ui import VoiceInput
from .ui import recommendations

router = APIRouter(prefix="/api/ui/assistant/voice", tags=["voice"])
_audio = OrderedDict()
_lock = Lock()


@router.post("")
def synthesize(payload: VoiceInput, db: Session = Depends(get_db)):
    match = next((r for r in recommendations(payload.farm_id, db)["recommendations"] if r["id"] == payload.recommendation_id), None)
    if match is None:
        raise HTTPException(404, "Recommendation not found")
    key, region = settings.azure_speech_key, settings.azure_speech_region
    if not key or not region or not re.fullmatch(r"[a-z0-9-]+", region):
        raise HTTPException(503, "Azure Speech key and region are not configured on the server")
    text = " ".join(match[part]["ar"] for part in ("summary", "action", "why"))
    ssml = ("<speak version='1.0' xml:lang='ar-JO'><voice name='ar-JO-TaimNeural'>" + html.escape(text) + "</voice></speak>")
    request = Request(f"https://{region}.tts.speech.microsoft.com/cognitiveservices/v1", data=ssml.encode(),
                      headers={"Ocp-Apim-Subscription-Key": key, "Content-Type": "application/ssml+xml",
                               "X-Microsoft-OutputFormat": "audio-24khz-48kbitrate-mono-mp3"}, method="POST")
    try:
        with urlopen(request, timeout=15) as response:
            audio = response.read(2_000_001)
        if not audio or len(audio) > 2_000_000:
            raise ValueError("Invalid audio")
    except Exception as exc:
        raise HTTPException(503, "Speech provider unavailable; use the browser voice fallback") from exc
    identifier = uuid4().hex
    with _lock:
        _audio[identifier] = (monotonic(), audio)
        while len(_audio) > 32:
            _audio.popitem(last=False)
    return {"audio_url": f"/api/ui/assistant/voice/audio/{identifier}", "text": text,
            "voice_id": payload.voice_id, "demo_mode": False}


@router.get("/audio/{identifier}")
def audio(identifier: str):
    with _lock:
        result = _audio.get(identifier)
        if result is None or monotonic() - result[0] > 600:
            _audio.pop(identifier, None)
            raise HTTPException(404, "Audio expired; request synthesis again")
    return Response(content=result[1], media_type="audio/mpeg", headers={"Cache-Control": "no-store"})
