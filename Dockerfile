FROM mambaorg/micromamba:1-jammy-cuda-12.6.0

# Set environment variables for NVIDIA
ENV NVIDIA_VISIBLE_DEVICES all
ENV NVIDIA_DRIVER_CAPABILITIES compute,utility

# Install Python 3.11 in the base environment globally for all users
RUN micromamba install -n base python=3.11 git nano -c conda-forge && \
    micromamba clean --all --yes

USER root

# Add your _activate_current_env.sh to the global profile.d directory
RUN cp /usr/local/bin/_activate_current_env.sh /etc/profile.d/activate_mamba.sh && \
    chmod +x /etc/profile.d/activate_mamba.sh

# Ensure it is sourced for all users by adding it to profile.d (global for bash users)
RUN echo "source /etc/profile.d/activate_mamba.sh" >> /etc/bash.bashrc

# Install Networking Tools
RUN apt-get update && apt-get install -y iputils-ping net-tools && \
    rm -rf /var/lib/apt/lists/*

USER mambauser

# Install PyTorch with CUDA using micromamba run (so we don’t need to activate the base environment manually)
RUN micromamba run -n base pip install \
    torch \
    torchvision \
    torchaudio --extra-index-url https://download.pytorch.org/whl/cu124

# Switch to root to perform privileged operations
USER root

# Create /opt/ComfyUI directory and give permissions
RUN mkdir -p /opt/ComfyUI && \
    chmod -R 777 /opt/ComfyUI
RUN mkdir -p /opt/comfy-cli && \
    chmod -R 777 /opt/comfy-cli

# Switch back to the default user for micromamba
USER mambauser

# Clone ComfyUI repo and install dependencies
RUN micromamba run -n base git clone https://github.com/comfyanonymous/ComfyUI.git /opt/ComfyUI && \
    micromamba run -n base pip install -r /opt/ComfyUI/requirements.txt

# Clone your fork of comfy-cli instead of installing from pip
RUN micromamba run -n base git clone --branch updatetimeoutoption https://github.com/jason-weirather/comfy-cli.git /opt/comfy-cli

# Install comfy-cli
ENV COMFYUI_PATH=/opt/ComfyUI
RUN cd /opt/comfy-cli && micromamba run -n base pip install -e .

# Run for first time and disable tracking
RUN micromamba run -n base comfy \
        --workspace $COMFYUI_PATH \
        --skip-prompt \
        --no-enable-telemetry tracking disable

USER root
# Copy the required repository into the container
ADD ./src /opt/comfyui-image-api/src
ADD pyproject.toml /opt/comfyui-image-api/pyproject.toml
ADD start.sh /opt/comfyui-image-api/start.sh
ADD README.md /opt/comfyui-image-api/README.md
ADD LICENSE /opt/comfyui-image-api/LICENSE


# Set permissions for the copied files
RUN chmod -R 777 /opt/comfyui-image-api

RUN mkdir -p /.cache/mamba/proc && \
    chmod -R 777 /.cache/mamba && \
    mkdir -p /.config && \
    chmod -R 777 /.config

USER mambauser
RUN cd /opt/comfyui-image-api && micromamba run -n base pip install -e .

RUN mkdir -p /home/mambauser/.config/comfy-cli && \
    chmod -R 777 /home/mambauser

ENV COMFYUI_IMAGE_API_DEFAULT_HOST 0.0.0.0

#ENV LOG_LEVEL DEBUG

# Use the wrapper script as the entrypoint
ENTRYPOINT ["/opt/comfyui-image-api/start.sh"]

# Command to start comfy-api
CMD ["--port", "8888", "--host", "$COMFYUI_IMAGE_API_DEFAULT_HOST", "--model-path", "/opt/ComfyUI/models/diffusers"]
