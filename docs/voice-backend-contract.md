# Smart Farm AI — Arabic Voice Backend Contract & Integration Guide
**Member 1 (Frontend & UI/UX) → Member 2 (Backend & AI Services)**

This document details the backend requirements for the Natural Jordanian Arabic Voice feature in **Smart Farm AI**, powered by **Microsoft Azure AI Speech**.

---

## 1. Voice Identity & Specifications

* **Cloud Provider:** Microsoft Azure Cognitive Services — Speech Service
* **Mandatory Voice Name:** `ar-JO-TaimNeural`
* **Locale:** `ar-JO` (Arabic - Jordan)
* **Gender & Style:** Male, clear, natural, professional Jordanian Arabic.
* **Persona:** Experienced Jordanian agricultural consultant advising open-field tomato farmers in the Jordan Valley (غور الأردن).
* **Audio Format:** `audio/mpeg` (MP3, 24kHz / 48kHz, mono) or `audio/wav`.

> **Note on Voice Exclusivity:** The frontend strictly enforces `voice_id === 'ar-JO-TaimNeural'`. If the backend returns any other voice ID, the frontend will reject it with a `VOICE_MISMATCH` error and will not play the audio.

---

## 2. API Endpoints Specification

### 2.1. Voice Synthesis Request
* **Endpoint:** `POST /assistant/voice`
* **Headers:**
  * `Content-Type: application/json`
  * `Authorization: Bearer <token>` (if authenticated) or session cookie
* **Request Body:**
  ```json
  {
    "recommendation_id": "rec-irrigation-01",
    "language": "ar-JO",
    "voice_id": "ar-JO-TaimNeural",
    "farm_id": "farm-jv-01"
  }
  ```

* **Response Success (`200 OK`):**
  ```json
  {
    "audio_url": "/api/v1/audio/rec-irrigation-01.mp3",
    "text": "وضع المزرعة. الرطوبة الحالية خمسة وثلاثون بالمئة وهي أقل من المستوى المطلوب. الخطوة المقترحة. ري الحقل صباح الغد بمعدل أربعة ملّيمترات. السبب. الحفاظ على رطوبة التربة خلال مرحلة الإزهار.",
    "voice_id": "ar-JO-TaimNeural",
    "demo_mode": false
  }
  ```
  * `audio_url`: Either a relative path served by the backend or an absolute URL on the same origin. The frontend requires that `audio_url` has the same origin as `API_BASE` for security.
  * `text`: The final normalized Arabic text that was synthesized by Azure Speech. The frontend displays this as the authoritative transcript.
  * `voice_id`: Must be `"ar-JO-TaimNeural"`.
  * `demo_mode`: Boolean flag (`false` for live synthesis, `true` if pre-recorded fallback is used).

* **Expected HTTP Error Responses:**
  * `503 Service Unavailable`: Azure Speech key/region missing, unconfigured, or Azure quota exhausted.
    * The frontend captures `503` and displays: *"خدمة الصوت غير مفعلة في الخادم حالياً"* (Speech service not configured on server).
  * `404 Not Found` / `422 Unprocessable Entity`: Recommendation ID not found or invalid.
    * The frontend captures this and displays: *"لم يتم العثور على التوصية الصوتية المطلوبة"*.
  * `401 Unauthorized` / `403 Forbidden`: Authentication credentials expired or missing.
  * `500 Internal Server Error`: Synthesizer runtime error.

### 2.2. Audio Stream / File Download
* **Endpoint:** `GET` the same-origin URL returned in `audio_url` (the reference implementation returns `/assistant/voice/stream/{filename}`; the frontend validates the origin but does not require a fixed path).
* **Headers:** Standard GET with credentials
* **Response:**
  * `Content-Type: audio/mpeg` (or `audio/wav`)
  * `Content-Disposition: inline`
  * `Cache-Control: public, max-age=86400` (Audio for a specific recommendation ID should be cached to save Azure synthesis costs)

---

## 3. Environment Variables (FastAPI Backend)

Create or update `.env` on the FastAPI server:

```bash
# Azure Cognitive Services Speech
AZURE_SPEECH_KEY="your-azure-speech-service-key-here"
AZURE_SPEECH_REGION="eastus" # or westeurope, qatarcentral, uae-north, etc.
AZURE_SPEECH_VOICE="ar-JO-TaimNeural"

# Audio Cache Storage
AUDIO_CACHE_DIR="./storage/audio_cache"
```

> **Security Rule:** Neither `AZURE_SPEECH_KEY` nor `AZURE_SPEECH_REGION` must ever be exposed to the browser or embedded into frontend source code.

---

## 4. FastAPI Python Implementation Reference

```python
import os
import hashlib
from pathlib import Path
from fastapi import FastAPI, HTTPException, status
from fastapi.responses import FileResponse
from pydantic import BaseModel
import azure.cognitiveservices.speech as speechsdk

app = FastAPI()

AZURE_KEY = os.getenv("AZURE_SPEECH_KEY")
AZURE_REGION = os.getenv("AZURE_SPEECH_REGION")
VOICE_NAME = "ar-JO-TaimNeural"
CACHE_DIR = Path(os.getenv("AUDIO_CACHE_DIR", "./storage/audio_cache"))
CACHE_DIR.mkdir(parents=True, exist_ok=True)

class VoiceRequest(BaseModel):
    recommendation_id: str
    language: str = "ar-JO"
    voice_id: str = "ar-JO-TaimNeural"
    farm_id: str | None = None

class VoiceResponse(BaseModel):
    audio_url: str
    text: str
    voice_id: str
    demo_mode: bool = False

@app.post("/assistant/voice", response_model=VoiceResponse)
async def generate_voice_recommendation(req: VoiceRequest):
    if not AZURE_KEY or not AZURE_REGION:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Azure AI Speech service is not configured on this server."
        )

    if req.voice_id != VOICE_NAME:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Requested voice_id '{req.voice_id}' not supported. Must be '{VOICE_NAME}'."
        )

    # 1. Look up recommendation text for req.recommendation_id
    # e.g., rec = db.get_recommendation(req.recommendation_id)
    spoken_text = "وضع المزرعة. الرطوبة الحالية خمسة وثلاثون بالمئة. الخطوة المقترحة. ري الحقل صباح الغد بمعدل أربعة ملّيمترات."

    # 2. Check cached audio file
    cache_key = hashlib.sha256(f"{req.recommendation_id}:{spoken_text}:{VOICE_NAME}".encode("utf-8")).hexdigest()
    output_filename = f"{cache_key}.mp3"
    output_path = CACHE_DIR / output_filename

    if not output_path.exists():
        speech_config = speechsdk.SpeechConfig(subscription=AZURE_KEY, region=AZURE_REGION)
        speech_config.speech_synthesis_voice_name = VOICE_NAME
        speech_config.set_speech_synthesis_output_format(
            speechsdk.SpeechSynthesisOutputFormat.Audio24Khz48KBitRateMonoMp3
        )

        audio_config = speechsdk.audio.AudioOutputConfig(filename=str(output_path))
        synthesizer = speechsdk.SpeechSynthesizer(speech_config=speech_config, audio_config=audio_config)

        # Synthesize speech
        result = synthesizer.speak_text_async(spoken_text).get()

        if result.reason != speechsdk.ResultReason.SynthesizingAudioCompleted:
            if output_path.exists():
                output_path.unlink()
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Speech synthesis failed: {result.cancellation_details.reason if result.cancellation_details else 'Unknown error'}"
            )

    return VoiceResponse(
        audio_url=f"/assistant/voice/stream/{output_filename}",
        text=spoken_text,
        voice_id=VOICE_NAME,
        demo_mode=False
    )

@app.get("/assistant/voice/stream/{filename}")
async def stream_voice_file(filename: str):
    file_path = CACHE_DIR / filename
    if not file_path.exists():
        raise HTTPException(status_code=404, detail="Audio file not found")
    return FileResponse(file_path, media_type="audio/mpeg")
```

---

## 5. Spoken Text Normalization Rules (Arabic)

The frontend already implements `SFA_SPEECH` (`d:/htu/js/speech-text.js`) for the client transcript preview. The backend should apply matching normalization to spoken sentences so that numbers, dates, and units sound fluent in Jordanian Arabic:

1. **Jordanian Dinars (`JOD` / `JD`):**
   * `1 JOD` → `دينار أردني واحد`
   * `2 JOD` → `ديناران أردنيان`
   * `3–10 JOD` → `ثلاثة دنانير أردنية`
   * `11+ JOD` → `أحد عشر ديناراً أردprocessاً` / `ثمانمئة دينار أردني`
2. **Area (`dunum`):**
   * `1 dunum` → `دونم واحد`
   * `2 dunums` → `دونمان`
   * `3–10 dunums` → `ثلاثة دونمات`
   * `11+ dunums` → `خمسة عشر دونماً`
3. **Irrigation & Water (`mm`, `m³`, `L`):**
   * `4 mm` → `أربعة ملّيمترات`
   * `20 m³` → `عشرون متراً مكعباً`
4. **Temperature (`°C`):**
   * `32°C` → `اثنتان وثلاثون درجة مئوية`
5. **Dates (`YYYY-MM-DD`):**
   * `2026-10-10` → `العاشر من تشرين الأول عام ألفين وستة وعشرين`
