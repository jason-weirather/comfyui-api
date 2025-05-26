# ──────────────────────────────────────────────────────────────────────────────
# comfyui-image-api Dockerfile (python:3.11-slim, HTTP-only ComfyRunner)
# ──────────────────────────────────────────────────────────────────────────────

FROM python:3.11-slim

# 1) Install minimal OS packages
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
      git \
      curl \
      nano \
      iputils-ping \
      net-tools \
    && rm -rf /var/lib/apt/lists/*

# 2) Set working dir
WORKDIR /opt/comfyui-image-api

# 3) Copy project files *before* pip install
COPY pyproject.toml poetry.lock* README.md LICENSE ./
COPY src/ src/

# 4) Install Python dependencies & your package, plus CPU-only PyTorch
RUN pip install --upgrade pip setuptools wheel && \
    pip install . && \
    pip install torch torchvision torchaudio --index-url https://download.pytorch.org/whl/cpu

# 6) Default env var for host (can be overridden via --env)
ENV COMFYUI_IMAGE_API_DEFAULT_HOST=0.0.0.0
ENV COMFYUI_API_PORT=8888
ENV COMFYUI_MODEL_PATH=/opt/ComfyUI/models/diffusers

# 7) Entrypoint in shell-form to allow env expansion
ENTRYPOINT ["comfy-api"]
CMD ["--port", "8888", \
     "--host", "0.0.0.0", \
     "--model-path", "/opt/ComfyUI/models/diffusers"]
