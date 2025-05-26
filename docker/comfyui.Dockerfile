FROM nvidia/cuda:12.1.1-cudnn8-runtime-ubuntu22.04

# Install basic dependencies
RUN apt-get update && apt-get install -y \
    git python3 python3-pip libgl1 libglib2.0-0 wget curl && \
    apt-get clean

# Set up ComfyUI
WORKDIR /opt
RUN git clone https://github.com/comfyanonymous/ComfyUI.git
WORKDIR /opt/ComfyUI

# Install Python requirements
RUN pip3 install --upgrade pip && \
    pip3 install -r requirements.txt && \
    pip3 install torch torchvision --index-url https://download.pytorch.org/whl/cu121

# Expose port for REST and WebSocket
EXPOSE 8188

# Entry point
CMD ["python3", "main.py", "--listen", "0.0.0.0", "--port", "8188", "--output-directory", "/outputs"]
