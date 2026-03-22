from threading import Lock
from uuid import uuid4

from comfyui_image_api.models import JobRecord, utcnow


class JobStore:
    def __init__(self) -> None:
        self._jobs: dict[str, JobRecord] = {}
        self._lock = Lock()

    def create(self, workflow_id: str, request_payload: dict) -> JobRecord:
        with self._lock:
            job = JobRecord(
                job_id=uuid4().hex,
                workflow_id=workflow_id,
                request_payload=request_payload,
            )
            self._jobs[job.job_id] = job
            return job

    def get(self, job_id: str) -> JobRecord | None:
        with self._lock:
            return self._jobs.get(job_id)

    def update(self, job_id: str, **changes) -> JobRecord:
        with self._lock:
            current = self._jobs[job_id]
            updated = current.model_copy(
                update={
                    **changes,
                    "updated_at": utcnow(),
                }
            )
            self._jobs[job_id] = updated
            return updated

    def active_count(self) -> int:
        with self._lock:
            return sum(
                1 for job in self._jobs.values()
                if job.status in {"queued", "running"}
            )
