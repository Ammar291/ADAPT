from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

Speaker = Literal["a", "b"]


class Language(BaseModel):
    code: str
    name: str
    input: bool = True
    output: bool = True
    fallback: bool = True
    rtl: bool = False


class Capabilities(BaseModel):
    provider: str = "openai"
    model: str = "gpt-realtime-translate"
    mode: Literal["live", "demo", "unavailable"]
    languages: list[Language]
    fallback_enabled: bool
    source: str = (
        "https://developers.openai.com/cookbook/examples/voice_solutions/realtime_translation_guide"
    )
    note: str = "Arabic is supported as input only; Arabic output uses the recorded fallback."


class SessionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    source: str = Field(default="en", min_length=2, max_length=8)
    target: str = Field(default="ar", min_length=2, max_length=8)
    recorded: bool = False


class SessionReference(BaseModel):
    model_config = ConfigDict(extra="forbid")
    session_id: str = Field(min_length=1, max_length=2048)


class TextRequest(SessionRequest):
    text: str = Field(min_length=1, max_length=6000)
    speaker: Speaker = "a"


class StreamCredential(BaseModel):
    speaker: Speaker
    source: str
    target: str
    transport: Literal["webrtc", "recorded", "demo"]
    client_secret: str | None = Field(default=None, repr=False)
    credential_expires_at: int | None = None
    session_expires_at: int | None = None
    webrtc_url: str | None = None


class SessionOut(BaseModel):
    session_id: str = Field(repr=False)
    mode: Literal["live", "demo"]
    expires_at: int
    streams: list[StreamCredential]


class FallbackOut(BaseModel):
    speaker: Speaker
    original: str
    translation: str
    audio_base64: str | None = None
    audio_mime: str = "audio/mpeg"
    audio_error: str | None = None
