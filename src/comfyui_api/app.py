import base64
import binascii
import mimetypes
import secrets
import time
import tempfile
from contextlib import asynccontextmanager
from io import BytesIO
from pathlib import Path
from threading import Lock

from fastapi import Depends, FastAPI, HTTPException, Query, Request

from comfyui_api import __version__
from comfyui_api.comfy_client import ComfyUIClient, AssetUnavailableError
from comfyui_api.job_store import JobStore
from comfyui_api.models import (
    ContentFilterSettings,
    GeneratedAsset,
    GeneratedImage,
    ImageEditRequest,
    ImageToVideoRequest,
    JobRecord,
    TextToImageRequest,
)
from comfyui_api.nsfw_filter import apply_nsfw_filter
from comfyui_api.security import require_api_key
from comfyui_api.settings import Settings, get_settings
from comfyui_api.workflow_registry import WorkflowRegistry


def _normalize_filter_settings(filter_settings) -> dict:
    if hasattr(filter_settings, "model_dump"):
        return filter_settings.model_dump()
    return dict(filter_settings)


def _guess_mime_type(filename: str) -> str:
    return mimetypes.guess_type(filename)[0] or "application/octet-stream"


def _guess_media_kind(mime_type: str) -> str:
    if mime_type.startswith("image/"):
        return "image"
    if mime_type.startswith("video/"):
        return "video"
    if mime_type.startswith("audio/"):
        return "audio"
    return "binary"


def _materialize_assets(
    comfy: ComfyUIClient,
    assets: list[dict],
    filter_settings,
    settings: Settings,
    output_map: dict | None = None,
) -> tuple[list[GeneratedAsset], list[GeneratedImage], dict]:
    filter_settings_dict = _normalize_filter_settings(filter_settings)
    output_map = output_map or {}

    ordered_outputs = list(output_map.items())
    node_order = {
        spec.get("node"): idx
        for idx, (_, spec) in enumerate(ordered_outputs)
        if isinstance(spec, dict) and spec.get("node")
    }
    output_by_node = {
        spec.get("node"): (output_id, spec)
        for output_id, spec in ordered_outputs
        if isinstance(spec, dict) and spec.get("node")
    }

    if output_by_node:
        assets = [
            asset
            for asset in assets
            if str(asset.get("source_node_id")) in output_by_node
        ]


    assets = sorted(
        assets,
        key=lambda a: (
            node_order.get(a.get("source_node_id"), 10**9),
            a.get("source_output_index", 0),
            a.get("filename", ""),
        ),
    )

    rendered_assets: list[GeneratedAsset] = []
    rendered_images: list[GeneratedImage] = []
    max_score = 0
    labels: set[str] = set()
    blurred = False

    for asset in assets:
        output_id = None
        output_spec = None
        source_node_id = asset.get("source_node_id")
        if source_node_id in output_by_node:
            output_id, output_spec = output_by_node[source_node_id]
        output_spec = output_spec or {}
        output_label = output_spec.get("label")
        output_tags = list(output_spec.get("tags") or [])
        output_metadata = dict(output_spec.get("metadata") or {})
        generated_path = None
        if settings.comfyui_output_dir and asset.get("type", "output") == "output":
            generated_path = (
                settings.comfyui_output_dir
                / asset.get("subfolder", "")
                / asset["filename"]
            )

        try:
            raw = comfy.view_file_with_retry(
                filename=asset["filename"],
                subfolder=asset.get("subfolder", ""),
                folder_type=asset.get("type", "output"),
                attempts=settings.view_retry_attempts,
                delay_s=settings.view_retry_delay_seconds,
            )
        except AssetUnavailableError as exc:
            disk_hint = "unknown"
            if generated_path is not None:
                disk_hint = (
                    f"path={generated_path}, exists={generated_path.exists()}"
                )
            raise AssetUnavailableError(
                f"{exc}; asset={asset}; comfyui_output={disk_hint}"
            ) from exc

        suffix = Path(asset["filename"]).suffix or ".bin"
        mime_type = _guess_mime_type(asset["filename"])
        media_kind = _guess_media_kind(mime_type)

        with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
            tmp.write(raw)
            tmp_path = Path(tmp.name)

        try:
            if media_kind == "image":
                score, triggered = apply_nsfw_filter(str(tmp_path), filter_settings_dict)
                max_score = max(max_score, score)
                labels.update(triggered)
                blurred = blurred or (
                    filter_settings_dict["blur"]
                    and filter_settings_dict["level"] > 0
                    and score >= filter_settings_dict["level"]
                )

            encoded = base64.b64encode(tmp_path.read_bytes()).decode("utf-8")
            rendered_assets.append(
                GeneratedAsset(
                    filename=asset["filename"],
                    subfolder=asset.get("subfolder", ""),
                    type=asset.get("type", "output"),
                    source_node_id=source_node_id,
                    output_id=output_id,
                    label=output_label,
                    tags=output_tags,
                    metadata=output_metadata,
                    media_kind=media_kind,
                    mime_type=mime_type,
                    data_base64=encoded,
                )
            )
            if media_kind == "image":
                rendered_images.append(
                    GeneratedImage(
                        filename=asset["filename"],
                        subfolder=asset.get("subfolder", ""),
                        type=asset.get("type", "output"),
                        source_node_id=source_node_id,
                        output_id=output_id,
                        label=output_label,
                        tags=output_tags,
                        metadata=output_metadata,
                        image_base64=encoded,
                    )
                )
        finally:
            tmp_path.unlink(missing_ok=True)
            if settings.delete_generated_files and generated_path is not None:
                generated_path.unlink(missing_ok=True)

    return rendered_assets, rendered_images, {
        "max_score": max_score,
        "labels": sorted(labels),
        "blurred": blurred,
    }

def _decode_base64_blob(data: str) -> bytes:
    payload = data.strip()
    if payload.startswith("data:") and "," in payload:
        payload = payload.split(",", 1)[1]
    try:
        return base64.b64decode(payload, validate=True)
    except binascii.Error as exc:
        raise ValueError("image_base64 must be valid base64 data") from exc


def _safe_upload_filename(filename: str) -> str:
    cleaned = Path(filename).name or "input.png"
    stem = Path(cleaned).stem or "input"
    suffix = Path(cleaned).suffix or ".png"
    return f"{stem}-{secrets.token_hex(8)}{suffix}"


def _upload_input_image(
    comfy: ComfyUIClient,
    image_base64: str,
    image_filename: str,
) -> str:
    data = _decode_base64_blob(image_base64)
    upload_name = _safe_upload_filename(image_filename)
    response = comfy.upload_image(
        fileobj=BytesIO(data),
        filename=upload_name,
        overwrite=False,
        image_type="input",
    )
    return response.get("name", upload_name)


def _maybe_upload_input_image(
    comfy: ComfyUIClient,
    image_base64: str | None,
    image_filename: str,
) -> str | None:
    if image_base64 is None:
        return None
    return _upload_input_image(
        comfy=comfy,
        image_base64=image_base64,
        image_filename=image_filename,
    )


def _build_values_from_request_payload(
    request_payload: dict,
    *,
    exclude_keys: set[str] | None = None,
) -> dict:
    exclude = {"workflow_id", "content_filter"}
    if exclude_keys:
        exclude |= set(exclude_keys)
    return {
        k: v
        for k, v in request_payload.items()
        if k not in exclude
    }

def _declared_output_nodes(output_map: dict | None) -> list[str]:
    if not output_map:
        return []
    nodes: list[str] = []
    for _, spec in output_map.items():
        if isinstance(spec, dict) and spec.get("node"):
            nodes.append(str(spec["node"]))
    return nodes

def _filter_and_sort_assets_for_declared_outputs(
    assets: list[dict],
    output_map: dict | None,
) -> list[dict]:
    ordered_nodes = _declared_output_nodes(output_map)
    if not ordered_nodes:
        return list(assets)

    node_order = {node_id: idx for idx, node_id in enumerate(ordered_nodes)}
    return sorted(
        [
            asset
            for asset in assets
            if str(asset.get("source_node_id")) in node_order
        ],
        key=lambda a: (
            node_order[str(a.get("source_node_id"))],
            a.get("source_output_index", 0),
            a.get("filename", ""),
        ),
    )

def _declared_outputs_ready(assets: list[dict], output_map: dict | None) -> bool:
    ordered_nodes = _declared_output_nodes(output_map)
    if not ordered_nodes:
        return bool(assets)

    present_nodes = {
        str(asset.get("source_node_id"))
        for asset in assets
        if asset.get("source_node_id") is not None
    }
    return set(ordered_nodes).issubset(present_nodes)


def _refresh_job(request: Request, job: JobRecord) -> JobRecord:
    if job.status in {"succeeded", "failed"} or not job.prompt_id:
        return job

    comfy: ComfyUIClient = request.app.state.comfy
    jobs: JobStore = request.app.state.jobs

    history = comfy.get_history(job.prompt_id)
    item = history.get(job.prompt_id)

    if not item:
        return job

    definition = request.app.state.registry.get(job.workflow_id)
    declared_output_nodes = _declared_output_nodes(definition.output_map)
    assets = comfy.extract_output_assets(
        item,
        allowed_node_ids=declared_output_nodes or None,
    )
    status = str((item.get("status") or {}).get("status_str", "")).lower()

    if assets and not job.assets and not job.images:
        if not _declared_outputs_ready(assets, definition.output_map):
            return jobs.update(job.job_id, status="running")
        try:
            filtered_assets = _filter_and_sort_assets_for_declared_outputs(
                assets,
                definition.output_map,
            )
            rendered_assets, rendered_images, content_filter = _materialize_assets(
                comfy,
                filtered_assets,
                job.request_payload.get("content_filter", ContentFilterSettings()),
                request.app.state.settings,
                definition.output_map,
            )
        except AssetUnavailableError as exc:
            return jobs.update(job.job_id, status="running", error=str(exc))

        return jobs.update(
            job.job_id,
            status="succeeded",
            output_assets=filtered_assets,
            assets=rendered_assets,
            images=rendered_images,
            content_filter=content_filter,
        )

    if status == "error":
        return jobs.update(
            job.job_id,
            status="failed",
            error=str(item.get("status")),
        )

    return jobs.update(job.job_id, status="running")

def _reconcile_active_jobs(request: Request) -> None:
    jobs: JobStore = request.app.state.jobs
    for active_job in jobs.list_active():
        _refresh_job(request, active_job)


def _submit_job(
    request: Request,
    *,
    workflow_id: str,
    request_payload: dict,
    build_values: dict,
    wait: bool,
    filter_settings,
) -> JobRecord:
    settings: Settings = request.app.state.settings
    jobs: JobStore = request.app.state.jobs
    registry: WorkflowRegistry = request.app.state.registry
    comfy: ComfyUIClient = request.app.state.comfy

    with request.app.state.submit_lock:
        _reconcile_active_jobs(request)
        if jobs.active_count() >= settings.max_pending_jobs:
            raise HTTPException(status_code=429, detail="Job queue is full")

        job = jobs.create(workflow_id=workflow_id, request_payload=request_payload)

        try:
            definition, workflow = registry.build(
                workflow_id=workflow_id,
                values=build_values,
            )

            submission = comfy.submit_prompt(workflow=workflow, client_id=job.job_id)
            job = jobs.update(
                job.job_id,
                prompt_id=submission["prompt_id"],
                queue_number=submission.get("number"),
                status="queued",
            )
        except Exception as exc:
            jobs.update(job.job_id, status="failed", error=str(exc))
            raise HTTPException(status_code=400, detail=str(exc))

    if not wait:
        return job

    job = jobs.update(job.job_id, status="running")
    declared_output_nodes = _declared_output_nodes(definition.output_map)

    try:
        history_item = comfy.wait_for_completion(
            prompt_id=job.prompt_id,
            timeout_s=settings.wait_timeout_seconds,
            poll_interval_s=settings.poll_interval_seconds,
            allowed_node_ids=declared_output_nodes or None,
            require_all_allowed_nodes=bool(declared_output_nodes),
        )
        assets = comfy.extract_output_assets(
            history_item,
            allowed_node_ids=declared_output_nodes or None,
        )
        filtered_assets = _filter_and_sort_assets_for_declared_outputs(
            assets,
            definition.output_map,
        )
        rendered_assets, rendered_images, content_filter = _materialize_assets(
            comfy,
            filtered_assets,
            filter_settings,
            settings,
            definition.output_map,
        )
        job = jobs.update(
            job.job_id,
            status="succeeded",
            output_assets=filtered_assets,
            assets=rendered_assets,
            images=rendered_images,
            content_filter=content_filter,
        )
        return job
    except AssetUnavailableError as exc:
        jobs.update(job.job_id, status="running", error=str(exc))
        raise HTTPException(
            status_code=502,
            detail=f"Output asset not yet fetchable from ComfyUI /view: {exc}",
        )
    except TimeoutError as exc:
        jobs.update(job.job_id, status="running", error=str(exc))
        raise HTTPException(status_code=504, detail=str(exc))
    except Exception as exc:
        jobs.update(job.job_id, status="failed", error=str(exc))
        raise HTTPException(status_code=500, detail=str(exc))


def create_app() -> FastAPI:
    settings = get_settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        app.state.settings = settings
        app.state.comfy = ComfyUIClient(settings.comfyui_base_url)
        app.state.jobs = JobStore()
        app.state.submit_lock = Lock()
        app.state.registry = WorkflowRegistry(
            settings.cassette_dir,
            settings.cassette_schema_path,
        )
        yield
        app.state.comfy.close()

    app = FastAPI(
        title="ComfyUI API",
        version=__version__,
        lifespan=lifespan,
    )

    def get_settings_from_request(request: Request) -> Settings:
        return request.app.state.settings

    @app.get("/healthz")
    def healthz(request: Request):
        try:
            stats = request.app.state.comfy.get_system_stats()
            return {"status": "ok", "comfyui_reachable": True, "system": stats}
        except Exception as exc:
            raise HTTPException(status_code=503, detail=f"ComfyUI unavailable: {exc}")

    @app.get("/v1/system", dependencies=[Depends(require_api_key)])
    def system_stats(request: Request):
        return request.app.state.comfy.get_system_stats()

    @app.get("/v1/queue", dependencies=[Depends(require_api_key)])
    def queue_info(request: Request):
        return request.app.state.comfy.get_queue()

    @app.get("/v1/models/{folder}", dependencies=[Depends(require_api_key)])
    def list_models(folder: str, request: Request):
        return request.app.state.comfy.list_models(folder)

    @app.get("/v1/workflows", dependencies=[Depends(require_api_key)])
    def list_workflows(request: Request):
        return request.app.state.registry.summary()

    @app.post("/v1/jobs/text2img", response_model=JobRecord, dependencies=[Depends(require_api_key)])
    def create_text2img_job(
        payload: TextToImageRequest,
        request: Request,
        wait: bool = Query(default=True),
    ):
        settings = get_settings_from_request(request)

        workflow_id = payload.workflow_id or settings.default_workflow_id
        effective_seed = payload.seed if payload.seed is not None else secrets.randbelow(9223372036854775807)

        request_payload = payload.model_dump(exclude_none=True, exclude_unset=True)
        request_payload["seed"] = effective_seed

        build_values = _build_values_from_request_payload(request_payload)

        return _submit_job(
            request,
            workflow_id=workflow_id,
            request_payload=request_payload,
            build_values=build_values,
            wait=wait,
            filter_settings=payload.content_filter,
        )

    @app.post("/v1/jobs/image2video", response_model=JobRecord, dependencies=[Depends(require_api_key)])
    def create_image2video_job(
        payload: ImageToVideoRequest,
        request: Request,
        wait: bool = Query(default=True),
    ):
        settings = get_settings_from_request(request)
        comfy: ComfyUIClient = request.app.state.comfy

        workflow_id = payload.workflow_id or "ltxv-2-distilled-image2video"
        effective_seed = payload.seed if payload.seed is not None else secrets.randbelow(9223372036854775807)

        try:
            uploaded_name = _upload_input_image(
                comfy,
                image_base64=payload.image_base64,
                image_filename=payload.image_filename,
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc))

        request_payload = payload.model_dump(
            exclude_none=True,
            exclude_unset=True,
            exclude={"image_base64"},
        )
        request_payload["image"] = uploaded_name
        request_payload["seed"] = effective_seed

        build_values = _build_values_from_request_payload(
            request_payload,
            exclude_keys={"image_filename"},
        )

        return _submit_job(
            request,
            workflow_id=workflow_id,
            request_payload=request_payload,
            build_values=build_values,
            wait=wait,
            filter_settings=payload.content_filter,
        )


    @app.post("/v1/jobs/image2image", response_model=JobRecord, dependencies=[Depends(require_api_key)])
    @app.post("/v1/jobs/image-edit", response_model=JobRecord, dependencies=[Depends(require_api_key)])
    def create_image_edit_job(
        payload: ImageEditRequest,
        request: Request,
        wait: bool = Query(default=True),
    ):
        comfy: ComfyUIClient = request.app.state.comfy

        workflow_id = payload.workflow_id or "qwen-image-edit-2509"
        effective_seed = payload.seed if payload.seed is not None else secrets.randbelow(9223372036854775807)


        validation_payload = payload.model_dump(
            exclude_none=True,
            exclude_unset=True,
            exclude={"workflow_id", "content_filter", "image1_filename", "image2_filename", "image3_filename"},
        )
        validation_payload["seed"] = effective_seed
        try:
            request.app.state.registry.validate_request(workflow_id, validation_payload)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc))

        try:
            uploaded_image1 = _upload_input_image(
                comfy,
                image_base64=payload.image1_base64,
                image_filename=payload.image1_filename,
            )
            uploaded_image2 = _maybe_upload_input_image(
                comfy,
                image_base64=payload.image2_base64,
                image_filename=payload.image2_filename,
            )
            uploaded_image3 = _maybe_upload_input_image(
                comfy,
                image_base64=payload.image3_base64,
                image_filename=payload.image3_filename,
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc))

        request_payload = payload.model_dump(
            exclude_none=True,
            exclude_unset=True,
            exclude={"image1_base64", "image2_base64", "image3_base64"},
        )
        request_payload["image1"] = uploaded_image1
        if uploaded_image2 is not None:
            request_payload["image2"] = uploaded_image2
        if uploaded_image3 is not None:
            request_payload["image3"] = uploaded_image3
        request_payload["seed"] = effective_seed

        build_values = _build_values_from_request_payload(
            request_payload,
            exclude_keys={"image1_filename", "image2_filename", "image3_filename"},
        )

        return _submit_job(
            request,
            workflow_id=workflow_id,
            request_payload=request_payload,
            build_values=build_values,
            wait=wait,
            filter_settings=payload.content_filter,
        )

    @app.get("/v1/jobs/{job_id}", response_model=JobRecord, dependencies=[Depends(require_api_key)])
    def get_job(job_id: str, request: Request):
        jobs: JobStore = request.app.state.jobs
        job = jobs.get(job_id)
        if job is None:
            raise HTTPException(status_code=404, detail="Unknown job_id")
        return _refresh_job(request, job)

    @app.get("/v1/jobs/{job_id}/result", response_model=JobRecord, dependencies=[Depends(require_api_key)])
    def get_job_result(job_id: str, request: Request):
        jobs: JobStore = request.app.state.jobs
        job = jobs.get(job_id)
        if job is None:
            raise HTTPException(status_code=404, detail="Unknown job_id")

        job = _refresh_job(request, job)

        if job.status == "failed":
            raise HTTPException(status_code=409, detail=job.error or "Job failed")
        if job.status != "succeeded":
            raise HTTPException(status_code=409, detail=f"Job not complete: {job.status}")

        return job

    return app
