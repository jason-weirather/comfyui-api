# comfyui-api

A FastAPI wrapper around ComfyUI workflows, packaged to run **ComfyUI** and **comfyui-api** in the **same container**.

This project is designed around a simple idea:

- **ComfyUI** is the image engine
- **comfyui-api** is the stable HTTP wrapper
- workflows are onboarded as **cassettes**
- models and cassettes are mounted **from outside the container**
- generated images can be returned through the API and immediately deleted from disk

As of **v0.3.0**, the project includes a working **FLUX.1 dev** text-to-image cassette and a single-container Docker setup that starts both services together.

![Example Output](https://i.imgur.com/Icvj2cr.png)

---

## What it does

- Runs **ComfyUI** and **comfyui-api** together in one container
- Exposes a REST API for running ComfyUI workflows
- Uses **cassettes** to define onboarded workflows
- Supports sequential execution with a wrapper-side admission gate
- Returns images as base64 in the API response
- Optionally deletes generated image files immediately after the response is prepared
- Mounts **models** and **cassettes** from outside the container

---

## Current status

**v0.3.0** includes:

- single-container Docker runtime
- ComfyUI pinned to **v0.18.0**
- a working **FLUX.1 dev** text-to-image cassette
- health check endpoint
- workflow listing
- model listing by ComfyUI folder
- queue inspection
- synchronous and queued text-to-image execution
- optional NSFW post-filtering
- immediate deletion of generated image files when enabled

---

## API docs

When the server is running, the FastAPI docs are available at:

- `/docs` for Swagger UI
- `/redoc` for ReDoc
- `/openapi.json` for the raw OpenAPI schema

Example:

```text
http://127.0.0.1:8888/docs
```

If you set an API key, use the **Authorize** button in Swagger UI and enter:

```text
Bearer YOUR_API_KEY
```

---

## How the container works

At startup, the container:

1. Starts **ComfyUI**
2. Waits for ComfyUI to become ready
3. Starts **comfyui-api**
4. Exposes the API on port **8888**

By default:

- ComfyUI binds internally to `127.0.0.1:8188`
- comfyui-api binds to `0.0.0.0:8888`
- models are expected at `/models`
- cassettes are expected at `/cassettes`
- ComfyUI input/output/user directories live under `/srv/comfy`
- generated output files can be deleted immediately after use

---

## Requirements

- NVIDIA GPU
- NVIDIA Container Toolkit / Docker GPU support
- Docker
- a mounted model directory compatible with the cassette you want to run

For the included **FLUX.1 dev** cassette, the required files are:

- `diffusion_models/flux1-dev-fp8.safetensors`
- `text_encoders/clip_l.safetensors`
- `text_encoders/t5xxl_fp16.safetensors`
- `vae/ae.safetensors`

mounted under your external models root.

---

## Build the container

```bash
docker build -t comfyui-api:local .
```

---

## Run the container

Use placeholder mount paths like these:

```bash
docker run --rm --gpus all \
  -p 8888:8888 \
  -v /path/to/comfyui-models:/models:ro \
  -v /path/to/comfyui-api-cassettes:/cassettes:ro \
  -e COMFYUI_API_API_KEY=dev-key \
  -e COMFYUI_API_CASSETTE_DIR=/cassettes \
  comfyui-api:local
```

### Notes

- `/models` should contain the ComfyUI model folder structure, for example:
  - `/models/diffusion_models`
  - `/models/text_encoders`
  - `/models/vae`
  - `/models/loras`
- `/cassettes` should contain cassette directories such as:
  - `/cassettes/flux-dev-simple/cassette.yaml`
  - `/cassettes/flux-dev-simple/workflow.json`
- the API key is optional, but recommended

If you also want to expose the ComfyUI web UI from the same container:

```bash
docker run --rm --gpus all \
  -p 8888:8888 \
  -p 8188:8188 \
  -v /path/to/comfyui-models:/models:ro \
  -v /path/to/comfyui-api-cassettes:/cassettes:ro \
  -e COMFYUI_HOST=0.0.0.0 \
  -e COMFYUI_API_API_KEY=dev-key \
  -e COMFYUI_API_CASSETTE_DIR=/cassettes \
  comfyui-api:local
```

---

## Configuration

These are the most important environment variables:

| Variable | Purpose | Default |
|---|---|---|
| `COMFYUI_API_API_KEY` | Bearer token required for `/v1/*` routes | unset |
| `COMFYUI_API_API_HOST` | Host for comfyui-api | `0.0.0.0` |
| `COMFYUI_API_API_PORT` | Port for comfyui-api | `8888` |
| `COMFYUI_API_COMFYUI_BASE_URL` | Internal URL for ComfyUI | `http://127.0.0.1:8188` |
| `COMFYUI_API_DEFAULT_WORKFLOW_ID` | Default cassette workflow ID | `flux-dev-simple` |
| `COMFYUI_API_MAX_PENDING_JOBS` | Max queued/running jobs tracked by wrapper | `5` |
| `COMFYUI_API_WAIT_TIMEOUT_SECONDS` | Max synchronous wait time | `900` |
| `COMFYUI_API_POLL_INTERVAL_SECONDS` | Poll interval while waiting on ComfyUI | `0.5` |
| `COMFYUI_API_COMFYUI_OUTPUT_DIR` | ComfyUI output directory for cleanup | `/srv/comfy/output` |
| `COMFYUI_API_DELETE_GENERATED_FILES` | Delete generated files after response prep | `true` |
| `COMFYUI_API_CASSETTE_DIR` | External cassette directory | packaged cassettes unless set |
| `COMFYUI_HOST` | Host ComfyUI binds to | `127.0.0.1` |
| `COMFYUI_PORT` | Port ComfyUI binds to | `8188` |
| `COMFYUI_MODELS_ROOT` | Mounted model root | `/models` |

---

## Endpoints

### Unauthenticated

#### `GET /healthz`

Returns whether `comfyui-api` can reach the bundled ComfyUI server.

---

### Authenticated

All `/v1/*` routes require:

```http
Authorization: Bearer YOUR_API_KEY
```

#### `GET /v1/system`

Return ComfyUI system stats.

#### `GET /v1/workflows`

List available workflow cassettes.

#### `GET /v1/models/{folder}`

List model filenames visible to ComfyUI for a given model folder.

Examples:

- `/v1/models/diffusion_models`
- `/v1/models/text_encoders`
- `/v1/models/vae`

#### `GET /v1/queue`

Return the current ComfyUI queue state.

#### `POST /v1/jobs/text2img`

Run the default text-to-image workflow.

Query parameter:

- `wait=true` waits for completion and returns the image result
- `wait=false` returns immediately with a queued job record

#### `GET /v1/jobs/{job_id}`

Get current job state.

#### `GET /v1/jobs/{job_id}/result`

Return the completed job result.

---

## Example smoke test with Python

This is the working FLUX.1 dev smoke test used against the current stack:

```python
import base64
import io
import json
import requests
from PIL import Image
import matplotlib.pyplot as plt

BASE = "http://127.0.0.1:8888"
HEADERS = {"Authorization": "Bearer dev-key"}

def show_json(resp):
    print("status:", resp.status_code)
    try:
        data = resp.json()
        print(json.dumps(data, indent=2)[:3000])
        return data
    except Exception:
        print(resp.text[:3000])
        return None

# 1) Health
resp = requests.get(f"{BASE}/healthz", timeout=30)
health = show_json(resp)

# 2) Workflows
resp = requests.get(f"{BASE}/v1/workflows", headers=HEADERS, timeout=30)
workflows = show_json(resp)

# 3) Native FLUX model visibility through wrapper
for folder in ["diffusion_models", "text_encoders", "vae"]:
    print(f"\n=== {folder} ===")
    resp = requests.get(f"{BASE}/v1/models/{folder}", headers=HEADERS, timeout=30)
    show_json(resp)

# 4) Run one synchronous FLUX job
payload = {
    "prompt": "instagram photo of fried drumsticks, korean style, huge portion on the dinner table, a cute hungry farm piglet looking at the plate",
    "steps": 20,
    "width": 1024,
    "height": 1024,
    "cfg": 1.0,
    "denoise": 1.0
    # "content_filter": {
    #     "level": 2,
    #     "probability": 0.5,
    #     "blur": True,
    #     "gaussian_blur_minimum": 20.0,
    #     "gaussian_blur_fraction": 0.05
    # }
}

resp = requests.post(
    f"{BASE}/v1/jobs/text2img",
    headers={**HEADERS, "Content-Type": "application/json"},
    params={"wait": "true"},
    json=payload,
    timeout=1800,
)
job = show_json(resp)

# 5) Display the first returned image
img_b64 = job["images"][0]["image_base64"]
img = Image.open(io.BytesIO(base64.b64decode(img_b64)))

plt.figure(figsize=(10, 10))
plt.imshow(img)
plt.axis("off")
plt.show()
```

---

## Example smoke test with curl

```bash
curl -sS http://127.0.0.1:8888/healthz | python -m json.tool

curl -sS -H "Authorization: Bearer dev-key" \
  http://127.0.0.1:8888/v1/workflows | python -m json.tool

curl -sS -H "Authorization: Bearer dev-key" \
  http://127.0.0.1:8888/v1/models/diffusion_models | python -m json.tool

curl -sS -H "Authorization: Bearer dev-key" \
  http://127.0.0.1:8888/v1/models/text_encoders | python -m json.tool

curl -sS -H "Authorization: Bearer dev-key" \
  http://127.0.0.1:8888/v1/models/vae | python -m json.tool

curl -sS -X POST "http://127.0.0.1:8888/v1/jobs/text2img?wait=true" \
  -H "Authorization: Bearer dev-key" \
  -H "Content-Type: application/json" \
  -d '{
    "prompt": "instagram photo of fried drumsticks, korean style, huge portion on the dinner table, a cute hungry farm piglet looking at the plate",
    "steps": 20,
    "width": 1024,
    "height": 1024,
    "cfg": 1.0,
    "denoise": 1.0
  }' | python -m json.tool
```

---

## Workflow cassettes

A cassette is the unit of workflow onboarding.

Each cassette lives in its own directory and contains:

- `cassette.yaml` for workflow metadata, request schema hints, routing aliases, and input mapping
- `workflow.json` for the raw ComfyUI API-format graph export

Example:

```text
src/comfyui_api/Cassettes/flux-dev-simple/
  cassette.yaml
  workflow.json
```

To onboard a new workflow:

1. get it running in raw ComfyUI first
2. export it in **API format**
3. create a cassette directory
4. add `cassette.yaml`
5. add `workflow.json`
6. restart `comfyui-api`
7. smoke test it through the wrapper

---

## File cleanup behavior

By default, generated images are saved by ComfyUI, fetched by the wrapper, filtered if configured, encoded into the API response, and then deleted from disk when:

```text
COMFYUI_API_DELETE_GENERATED_FILES=true
```

This keeps the container from filling up with old image files during API usage.

---

## Development notes

This project currently ships with a working FLUX.1 dev cassette and is evolving toward a more cassette-driven workflow onboarding model.

At the moment:

- the container runtime is current
- the API routes are current
- the README should describe **FastAPI + ComfyUI**, not the older comfy-cli/Flask stack
- cassette request schemas exist, though not every runtime behavior is fully cassette-driven yet

---

## License

This project is licensed under the Apache 2.0 License. See [LICENSE](LICENSE).

Model licenses remain the responsibility of the model providers. For example, **FLUX.1 dev** has its own license terms.

---

## Author

Jason L Weirather
