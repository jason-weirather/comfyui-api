FROM nvidia/cuda:12.8.1-cudnn-runtime-ubuntu24.04

ARG DEBIAN_FRONTEND=noninteractive
ARG COMFYUI_VERSION=v0.18.0

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    VIRTUAL_ENV=/opt/venv \
    PATH=/opt/venv/bin:$PATH \
    COMFYUI_HOME=/opt/ComfyUI \
    COMFYUI_VERSION=${COMFYUI_VERSION} \
    COMFYUI_HOST=127.0.0.1 \
    COMFYUI_PORT=8188 \
    COMFYUI_INPUT_DIR=/srv/comfy/input \
    COMFYUI_OUTPUT_DIR=/srv/comfy/output \
    COMFYUI_USER_DIR=/srv/comfy/user \
    COMFYUI_MODELS_ROOT=/models \
    COMFYUI_EXTRA_MODEL_PATHS_CONFIG=/srv/comfy/extra_model_paths.yaml \
    COMFYUI_DISABLE_API_NODES=true \
    COMFYUI_STARTUP_TIMEOUT=300 \
    COMFYUI_API_COMFYUI_BASE_URL=http://127.0.0.1:8188 \
    COMFYUI_API_API_HOST=0.0.0.0 \
    COMFYUI_API_API_PORT=8888 \
    COMFYUI_API_COMFYUI_OUTPUT_DIR=/srv/comfy/output \
    COMFYUI_API_DELETE_GENERATED_FILES=true

RUN apt-get update && apt-get install -y --no-install-recommends \
    python3 \
    python3-pip \
    python3-venv \
    python3-dev \
    git \
    curl \
    ca-certificates \
    tini \
    libgl1 \
    libglib2.0-0 \
 && rm -rf /var/lib/apt/lists/* \
 && ln -sf /usr/bin/python3 /usr/bin/python \
 && ln -sf /usr/bin/pip3 /usr/bin/pip

RUN python3 -m venv ${VIRTUAL_ENV}

RUN git clone --depth 1 --branch ${COMFYUI_VERSION} https://github.com/Comfy-Org/ComfyUI.git ${COMFYUI_HOME}

RUN ${VIRTUAL_ENV}/bin/pip install --upgrade pip setuptools wheel && \
    ${VIRTUAL_ENV}/bin/pip install --default-timeout=100 torch torchvision torchaudio --index-url https://download.pytorch.org/whl/cu128 && \
    ${VIRTUAL_ENV}/bin/pip install --default-timeout=100 -r ${COMFYUI_HOME}/requirements.txt

WORKDIR /opt/comfyui-api
COPY pyproject.toml README.md LICENSE MANIFEST.in ./
COPY src ./src
COPY start.sh /usr/local/bin/start-comfyui-stack

RUN mkdir -p /srv/comfy/input /srv/comfy/output /srv/comfy/user /models /cassettes && \
    cp /opt/comfyui-api/src/comfyui_api/Templates/extra_model_paths.yaml /srv/comfy/extra_model_paths.yaml

RUN chmod +x /usr/local/bin/start-comfyui-stack && \
    ${VIRTUAL_ENV}/bin/pip install --no-build-isolation --default-timeout=100 .

RUN mkdir -p /srv/comfy/input /srv/comfy/output /srv/comfy/user /models /cassettes

EXPOSE 8888 8188

HEALTHCHECK --interval=30s --timeout=10s --start-period=90s --retries=5 \
  CMD curl -fsS http://127.0.0.1:${COMFYUI_API_API_PORT:-8888}/healthz || exit 1

ENTRYPOINT ["/usr/bin/tini", "--", "/usr/local/bin/start-comfyui-stack"]
