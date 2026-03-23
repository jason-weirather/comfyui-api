#!/usr/bin/env bash
set -Eeuo pipefail

log() {
  printf '[start] %s\n' "$*" >&2
}

COMFYUI_HOME="${COMFYUI_HOME:-/opt/ComfyUI}"
COMFYUI_HOST="${COMFYUI_HOST:-127.0.0.1}"
COMFYUI_PORT="${COMFYUI_PORT:-8188}"
COMFYUI_INPUT_DIR="${COMFYUI_INPUT_DIR:-/srv/comfy/input}"
COMFYUI_OUTPUT_DIR="${COMFYUI_OUTPUT_DIR:-/srv/comfy/output}"
COMFYUI_USER_DIR="${COMFYUI_USER_DIR:-/srv/comfy/user}"
COMFYUI_MODELS_ROOT="${COMFYUI_MODELS_ROOT:-/models}"
COMFYUI_EXTRA_MODEL_PATHS_CONFIG="${COMFYUI_EXTRA_MODEL_PATHS_CONFIG:-/srv/comfy/extra_model_paths.yaml}"
COMFYUI_DISABLE_API_NODES="${COMFYUI_DISABLE_API_NODES:-true}"
COMFYUI_STARTUP_TIMEOUT="${COMFYUI_STARTUP_TIMEOUT:-300}"

export COMFYUI_PORT
export COMFYUI_STARTUP_TIMEOUT

export COMFYUI_API_COMFYUI_BASE_URL="${COMFYUI_API_COMFYUI_BASE_URL:-http://127.0.0.1:${COMFYUI_PORT}}"
export COMFYUI_API_API_HOST="${COMFYUI_API_API_HOST:-0.0.0.0}"
export COMFYUI_API_API_PORT="${COMFYUI_API_API_PORT:-8888}"
export COMFYUI_API_COMFYUI_OUTPUT_DIR="${COMFYUI_API_COMFYUI_OUTPUT_DIR:-${COMFYUI_OUTPUT_DIR}}"
export COMFYUI_API_DELETE_GENERATED_FILES="${COMFYUI_API_DELETE_GENERATED_FILES:-true}"

# Prefer mounted external cassettes if present, otherwise fall back to packaged examples.
if [[ -d "/cassettes" ]] && compgen -G "/cassettes/*/cassette.yaml" > /dev/null; then
  export COMFYUI_API_CASSETTE_DIR="${COMFYUI_API_CASSETTE_DIR:-/cassettes}"
  log "Using mounted cassettes from ${COMFYUI_API_CASSETTE_DIR}"
elif [[ -n "${COMFYUI_API_CASSETTE_DIR:-}" && ! -d "${COMFYUI_API_CASSETTE_DIR}" ]]; then
  log "Configured COMFYUI_API_CASSETTE_DIR does not exist: ${COMFYUI_API_CASSETTE_DIR}"
  exit 1
else
  log "No mounted cassettes detected at /cassettes; using packaged cassettes."
fi

mkdir -p "${COMFYUI_INPUT_DIR}" "${COMFYUI_OUTPUT_DIR}" "${COMFYUI_USER_DIR}"

# Either use a mounted extra_model_paths.yaml or generate one from /models.
if [[ -f "${COMFYUI_EXTRA_MODEL_PATHS_CONFIG}" ]]; then
  log "Using existing extra_model_paths config: ${COMFYUI_EXTRA_MODEL_PATHS_CONFIG}"
else
  mkdir -p "$(dirname "${COMFYUI_EXTRA_MODEL_PATHS_CONFIG}")"
  cat > "${COMFYUI_EXTRA_MODEL_PATHS_CONFIG}" <<EOF
container_models:
  base_path: ${COMFYUI_MODELS_ROOT}
  checkpoints: checkpoints
  text_encoders: text_encoders
  clip: clip
  clip_vision: clip_vision
  configs: configs
  controlnet: controlnet
  diffusion_models: diffusion_models
  diffusers: diffusers
  embeddings: embeddings
  gligen: gligen
  hypernetworks: hypernetworks
  loras: loras
  photomaker: photomaker
  style_models: style_models
  upscale_models: upscale_models
  vae: vae
  vae_approx: vae_approx
  audio_encoders: audio_encoders
  model_patches: model_patches
EOF
  log "Generated extra_model_paths config at ${COMFYUI_EXTRA_MODEL_PATHS_CONFIG}"
fi

if [[ ! -d "${COMFYUI_MODELS_ROOT}" ]]; then
  log "Warning: models root does not exist yet: ${COMFYUI_MODELS_ROOT}"
fi

cleanup() {
  local exit_code=$?

  if [[ -n "${api_pid:-}" ]] && kill -0 "${api_pid}" 2>/dev/null; then
    kill "${api_pid}" 2>/dev/null || true
    wait "${api_pid}" 2>/dev/null || true
  fi

  if [[ -n "${comfy_pid:-}" ]] && kill -0 "${comfy_pid}" 2>/dev/null; then
    kill "${comfy_pid}" 2>/dev/null || true
    wait "${comfy_pid}" 2>/dev/null || true
  fi

  exit "${exit_code}"
}
trap cleanup EXIT SIGINT SIGTERM

cd "${COMFYUI_HOME}"

comfy_args=(
  python main.py
  --listen "${COMFYUI_HOST}"
  --port "${COMFYUI_PORT}"
  --extra-model-paths-config "${COMFYUI_EXTRA_MODEL_PATHS_CONFIG}"
  --input-directory "${COMFYUI_INPUT_DIR}"
  --output-directory "${COMFYUI_OUTPUT_DIR}"
  --user-directory "${COMFYUI_USER_DIR}"
)

if [[ "${COMFYUI_DISABLE_API_NODES,,}" == "true" ]]; then
  comfy_args+=(--disable-api-nodes)
fi

log "Starting ComfyUI ${COMFYUI_VERSION:-unknown} ..."
"${comfy_args[@]}" &
comfy_pid=$!

python - <<'PY'
import os
import sys
import time
import urllib.request

base = f"http://127.0.0.1:{os.environ.get('COMFYUI_PORT', '8188')}/system_stats"
timeout = int(os.environ.get("COMFYUI_STARTUP_TIMEOUT", "300"))
deadline = time.time() + timeout
last_exc = None

while time.time() < deadline:
    try:
        with urllib.request.urlopen(base, timeout=5) as resp:
            if resp.status == 200:
                sys.exit(0)
    except Exception as exc:
        last_exc = exc
    time.sleep(1)

print(f"ComfyUI did not become ready within {timeout}s: {last_exc}", file=sys.stderr)
sys.exit(1)
PY

log "ComfyUI is ready; starting comfyui-api ..."
cd /opt/comfyui-api
comfyui-api &
api_pid=$!

wait -n "${comfy_pid}" "${api_pid}"
status=$?
log "A process exited with status ${status}"
exit "${status}"
