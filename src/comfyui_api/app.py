import base64
import secrets
import tempfile
from contextlib import asynccontextmanager
from pathlib import Path
from threading import Lock

from fastapi import Depends, FastAPI, HTTPException, Query, Request

from comfyui_api import __version__
from comfyui_api.comfy_client import ComfyUIClient
from comfyui_api.job_store import JobStore
from comfyui_api.models import GeneratedImage, JobRecord, TextToImageRequest
from comfyui_api.nsfw_filter import apply_nsfw_filter
from comfyui_api.security import require_api_key
from comfyui_api.settings import Settings, get_settings
from comfyui_api.workflow_registry import WorkflowRegistry


def _materialize_images(
    comfy: ComfyUIClient,
    assets: list[dict],
    filter_settings,
    settings: Settings,
) -> tuple[list[GeneratedImage], dict]:
    if hasattr(filter_settings, "model_dump"):
        filter_settings_dict = filter_settings.model_dump()
    else:
        filter_settings_dict = dict(filter_settings)

    rendered: list[GeneratedImage] = []
    max_score = 0
    labels: set[str] = set()
    blurred = False

    for asset in assets:
        raw = comfy.view_file(
            filename=asset["filename"],
            subfolder=asset.get("subfolder", ""),
            folder_type=asset.get("type", "output"),
        )

        generated_path = None
        if settings.comfyui_output_dir and asset.get("type", "output") == "output":
            generated_path = (
                settings.comfyui_output_dir
                / asset.get("subfolder", "")
                / asset["filename"]
            )

        suffix = Path(asset["filename"]).suffix or ".png"
        with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
            tmp.write(raw)
            tmp_path = Path(tmp.name)

        try:
            score, triggered = apply_nsfw_filter(str(tmp_path), filter_settings_dict)
            max_score = max(max_score, score)
            labels.update(triggered)
            blurred = blurred or (
                filter_settings_dict["blur"]
                and filter_settings_dict["level"] > 0
                and score >= filter_settings_dict["level"]
            )

            encoded = base64.b64encode(tmp_path.read_bytes()).decode("utf-8")
            rendered.append(
                GeneratedImage(
                    filename=asset["filename"],
                    subfolder=asset.get("subfolder", ""),
                    type=asset.get("type", "output"),
                    image_base64=encoded,
                )
            )
        finally:
            tmp_path.unlink(missing_ok=True)
            if settings.delete_generated_files and generated_path is not None:
                generated_path.unlink(missing_ok=True)

    return rendered, {
        "max_score": max_score,
        "labels": sorted(labels),
        "blurred": blurred,
    }


def _refresh_job(request: Request, job: JobRecord) -> JobRecord:
    if job.status in {"succeeded", "failed"} or not job.prompt_id:
        return job

    comfy: ComfyUIClient = request.app.state.comfy
    jobs: JobStore = request.app.state.jobs

    history = comfy.get_history(job.prompt_id)
    item = history.get(job.prompt_id)

    if not item:
        return job

    assets = comfy.extract_output_assets(item)
    status = str((item.get("status") or {}).get("status_str", "")).lower()

    if assets and not job.images:
        rendered, content_filter = _materialize_images(
            comfy,
            assets,
            job.request_payload["content_filter"],
            request.app.state.settings,
        )
        return jobs.update(
            job.job_id,
            status="succeeded",
            output_assets=assets,
            images=rendered,
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
        jobs: JobStore = request.app.state.jobs
        registry: WorkflowRegistry = request.app.state.registry
        comfy: ComfyUIClient = request.app.state.comfy

        workflow_id = payload.workflow_id or settings.default_workflow_id
        effective_seed = payload.seed if payload.seed is not None else secrets.randbelow(9223372036854775807)

        request_payload = payload.model_dump(exclude_none=True)
        request_payload["seed"] = effective_seed

        with request.app.state.submit_lock:
            _reconcile_active_jobs(request)
            if jobs.active_count() >= settings.max_pending_jobs:
                raise HTTPException(status_code=429, detail="Job queue is full")

            job = jobs.create(workflow_id=workflow_id, request_payload=request_payload)

            try:
                build_values = {
                    k: v
                    for k, v in request_payload.items()
                    if k not in {"workflow_id", "content_filter"}
                }

                _, workflow = registry.build(
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

        try:
            history_item = comfy.wait_for_completion(
                prompt_id=job.prompt_id,
                timeout_s=settings.wait_timeout_seconds,
                poll_interval_s=settings.poll_interval_seconds,
            )
            assets = comfy.extract_output_assets(history_item)
            rendered, content_filter = _materialize_images(
                comfy,
                assets,
                payload.content_filter,
                settings,
            )
            job = jobs.update(
                job.job_id,
                status="succeeded",
                output_assets=assets,
                images=rendered,
                content_filter=content_filter,
            )
            return job
        except TimeoutError as exc:
            jobs.update(job.job_id, status="running", error=str(exc))
            raise HTTPException(status_code=504, detail=str(exc))
        except Exception as exc:
            jobs.update(job.job_id, status="failed", error=str(exc))
            raise HTTPException(status_code=500, detail=str(exc))

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
