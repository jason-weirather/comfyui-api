from datetime import datetime, timezone
from typing import Any, Literal, Optional

from pydantic import BaseModel, Field, field_validator, ConfigDict


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class ContentFilterSettings(BaseModel):
    level: int = Field(default=2, ge=0, le=2)
    probability: float = Field(default=0.5, ge=0.0, le=1.0)
    blur: bool = True
    gaussian_blur_minimum: float = Field(default=20.0, ge=0.0)
    gaussian_blur_fraction: float = Field(default=0.05, ge=0.0, le=1.0)

def disabled_content_filter() -> ContentFilterSettings:
    return ContentFilterSettings(level=0, blur=False)

class TextToImageRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    prompt: str = Field(..., min_length=1)
    negative_prompt: str | None = None
    seed: int | None = Field(default=None, ge=0, le=9223372036854775807)
    steps: int | None = Field(default=None, ge=1)
    width: int | None = Field(default=None, ge=64, le=3840)
    height: int | None = Field(default=None, ge=64, le=3840)
    cfg: float | None = Field(default=None, ge=0.0, le=30.0)
    denoise: float | None = Field(default=None, ge=0.0, le=1.0)
    photo_lora_strength: Optional[float] = None
    illustration_lora_strength: Optional[float] = None
    workflow_id: str | None = None
    checkpoint_name: str | None = None
    content_filter: ContentFilterSettings = Field(default_factory=ContentFilterSettings)

    @field_validator("prompt")
    @classmethod
    def prompt_must_not_be_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("prompt must not be empty")
        return value

class ImageToVideoRequest(BaseModel):
    prompt: str = Field(..., min_length=1)
    image_base64: str = Field(..., min_length=1)
    image_filename: str = Field(default="input.png", min_length=1)
    seed: int | None = Field(default=None, ge=0, le=9223372036854775807)
    width: int | None = Field(default=None, ge=64, le=3840)
    height: int | None = Field(default=None, ge=64, le=3840)
    frames: int | None = Field(default=None, ge=1, le=4096)
    fps: int | None = Field(default=None, ge=1, le=120)
    cfg: float | None = Field(default=None, ge=0.0, le=30.0)
    image_strength: float | None = Field(default=None, ge=0.0, le=1.0)
    img_compression: int | None = Field(default=None, ge=0, le=100)
    workflow_id: str | None = None
    content_filter: ContentFilterSettings = Field(default_factory=disabled_content_filter)

    @field_validator("prompt", "image_base64")
    @classmethod
    def value_must_not_be_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("value must not be empty")
        return value


class ImageEditRequest(BaseModel):
    prompt: str | None = Field(default=None, min_length=1)
    image1_base64: str = Field(..., min_length=1)
    image1_filename: str = Field(default="image1.png", min_length=1)
    image2_base64: str | None = None
    image2_filename: str = Field(default="image2.png", min_length=1)
    image3_base64: str | None = None
    image3_filename: str = Field(default="image3.png", min_length=1)
    seed: int | None = Field(default=None, ge=0, le=9223372036854775807)
    steps: int | None = Field(default=None, ge=1)
    cfg: float | None = Field(default=None, ge=0.0, le=30.0)
    denoise: float | None = Field(default=None, ge=0.0, le=1.0)
    unet_name: str | None = None
    clip_name: str | None = None
    vae_name: str | None = None
    lightning_lora_name: str | None = None
    photo_lora_strength: Optional[float] = None
    illustration_lora_strength: Optional[float] = None
    workflow_id: str | None = None
    content_filter: ContentFilterSettings = Field(default_factory=ContentFilterSettings)
    multi_angle_lora_name: str | None = None
    megapixels: float | None = Field(default=None, gt=0)


    @field_validator("image1_base64")
    @classmethod
    def value_must_not_be_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("value must not be empty")
        return value


    @field_validator("prompt")
    @classmethod
    def prompt_must_not_be_blank_if_present(cls, value: str | None) -> str | None:
        if value is not None and not value.strip():
            raise ValueError("prompt must not be empty")
        return value
JobStatus = Literal["created", "queued", "running", "succeeded", "failed"]
MediaKind = Literal["image", "video", "audio", "binary"]

class GeneratedImage(BaseModel):
    filename: str
    subfolder: str = ""
    type: str = "output"
    source_node_id: str | None = None
    output_id: str | None = None
    label: str | None = None
    tags: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)
    image_base64: str


class GeneratedAsset(BaseModel):
    filename: str
    subfolder: str = ""
    type: str = "output"
    source_node_id: str | None = None
    output_id: str | None = None
    label: str | None = None
    tags: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)
    media_kind: MediaKind
    mime_type: str
    data_base64: str

class JobRecord(BaseModel):
    job_id: str
    prompt_id: str | None = None
    workflow_id: str
    status: JobStatus = "created"
    queue_number: int | None = None
    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)
    request_payload: dict[str, Any]
    output_assets: list[dict[str, Any]] = Field(default_factory=list)
    assets: list[GeneratedAsset] = Field(default_factory=list)
    images: list[GeneratedImage] = Field(default_factory=list)
    content_filter: dict[str, Any] | None = None
    error: str | None = None
