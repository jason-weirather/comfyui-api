# ComfyUI API

### For Black Forest Lab's `FLUX.1 [dev]` Model

The **ComfyUI API** enables GPU users to leverage ComfyUI’s advanced workflow management capabilities for running Black Forest Lab's **`FLUX.1 [dev]`** model. Designed for GPUs with limited memory, this project can run the `fp8` version of **`FLUX.1 [dev]`** in under 20GB of VRAM. The API provides a containerized, RESTful interface for image generation, offering both scalability and ease of use.

This API integrates **ComfyUI**, **comfy-cli**, and **Flask** to allow seamless submission of image generation jobs. It offers a queue system for handling multiple requests while ensuring efficient resource utilization.

## Features

- **HTTP API** to generate images using the **Comfy-Org Flux.1-Dev fp8** model.
- **Job queue** for sequential processing of multiple image generation requests.
- **Configurable queue limits** to control the maximum number of jobs.
- **Status endpoint** to monitor server details such as the API version, current queue size, and workflow information.
- **Dockerized** for easy setup and deployment.

## Quickstart

1. Have a Cuda capable GPU and Docker installed
2. Get the the docker image `docker pull vacation/comfyui-image-api:0.1.0`
3. [Download the model.](https://huggingface.co/Comfy-Org/flux1-dev/blob/main/flux1-dev-fp8.safetensors) Comfy-Org's `fp8` version of Black Forest Lab's `FLUX.1 [dev]` from huggingface
4. Run the server with Docker (This example, for linux/unix users runs it as the current user, windows users may need to omit the `--user` option)

```bash
docker run --rm --user $(id -u):$(id -g) \
  -v /path/to/models:/path/to/models  \
  -p 8888:8888 \
  --gpus all \
  vacation/comfyui-image-api:0.1.0 \
    --model-path /path/to/models/flux1-dev-fp8.safetensors
```

5. Use your server exposed on port 8888 to make an image

```bash
curl -X POST http://127.0.0.1:8888/generate \
-H "Content-Type: application/json" \
-d '{
  "prompt": "instagram photo of fried drumsticks (chicken), korean style, a huge portion on the dinner table, a cute hungry farm piglet is looking at the plate",
  "steps": 50,
  "width": 1024,
  "height": 1024
}' | grep -o '"image":"[^"]*' | sed 's/"image":"//' | base64 --decode > generated_image.png
```

![Example Output](https://i.imgur.com/Icvj2cr.png)

---

## Table of Contents

1. [Requirements](#requirements)
2. [Installation](#installation)
3. [Running the API Server](#running-the-api-server)
4. [API Endpoints](#api-endpoints)
   - [POST /generate](#post-generate)
   - [GET /status](#get-status)
5. [Configuration](#configuration)
6. [Examples](#examples)

---

## Requirements

1. Before running the ComfyUI API, ensure the following dependencies are installed on your system:
  - **Python 3.8+**
  - **PyTorch** with CUDA support (if you are using GPU-based image generation)
  - **ComfyUI**
  - **comfy-cli** (Within an offline/docker environment, the external network calls need to be disable as in [this fork](https://github.com/jason-weirather/comfy-cli/tree/fixhangbug/comfy_cli))
  - **Docker** (optional but recommended for containerized deployments)

2. Download the `fp8` **`FLUX.1 [dev]`** model file [`flux1-dev-fp8.safetensors`](https://huggingface.co/Comfy-Org/flux1-dev/blob/main/flux1-dev-fp8.safetensors) from Comfy-Org on huggingface.

---

## Installation

### Cloning the Repository

```bash
git clone https://github.com/jason-weirather/comfyui-image-api.git
cd comfyui-image-api
```

### Installing Dependencies

You can install dependencies using `pip` or avoid this by using a `Docker` container.

#### Option 2: Docker (Recommended)

1. Build the Docker image:

   ```bash
   docker build -t comfyui-image-api .
   ```

---

## Running the API Server

### Command-line Options

Run the API using `comfy-api`, a CLI script that allows you to configure the server:

```bash
comfy-api --model-path /path/to/your/model
```

| Option           | Description                                                                                            | Default                     |
|------------------|--------------------------------------------------------------------------------------------------------|-----------------------------|
| `--model-path`   | Path to the model you want to use (required).                                                          | N/A                         |
| `--host`         | The host to bind the API server to. You can override the default via `COMFYUI_API_DEFAULT_HOST`. | `127.0.0.1`                 |
| `--port`         | Port for the API server.                                                                               | `8888`                      |
| `--comfyui-path` | Path to the ComfyUI installation. You can override this via the `COMFYUI_PATH` environment variable.   | N/A                         |
| `--comfyui-host` | The host to bind the ComfyUI server to (for internal use).                                             | `127.0.0.1`                 |
| `--comfyui-port` | Port for the ComfyUI server (for internal use).                                                        | `8188`                      |
| `--output-path`  | Directory to save generated images. If not provided, a temporary directory will be created.            | Temporary directory created |
| `--max-queue`    | Maximum number of image generation requests allowed in the queue at one time.                          | `5`                         |

#### Example with Docker

You can also run the server via Docker:

```bash
docker run --rm --user $(id -u):$(id -g) \
  -v /path/to/models:/path/to/models  \
  -p 8888:8888 \
  --gpus all \
  vacation/comfyui-image-api:0.1.0 \
    --model-path /path/to/models/flux1-dev-fp8.safetensors
```

Where `/path/to/models` contains the [`flux1-dev-fp8.safetensors`](https://huggingface.co/Comfy-Org/flux1-dev/blob/main/flux1-dev-fp8.safetensors) model from Comfy-Org on huggingface.

---

## API Endpoints

### POST `/generate`

This endpoint is used to generate an image based on a text prompt and other optional parameters.

#### Request Payload Schema

| Field     | Type    | Required | Description                                                    |
|-----------|---------|----------|----------------------------------------------------------------|
| `prompt`  | string  | Yes      | Text prompt for generating the image.                          |
| `steps`   | integer | No       | Number of steps for processing the image. Default: 30.         |
| `seed`    | integer | No       | Random seed for generating the image. Randomized if not given. |
| `width`   | integer | No       | Width of the image in pixels. Default: 512.                    |
| `height`  | integer | No       | Height of the image in pixels. Default: 512.                   |
| `cfg`     | number  | No       | Classifier-free guidance scale. Default: 4.0.                  |
| `denoise` | number  | No       | Denoise strength. Default: 1.0.                                |

#### Example Request

```bash
curl -X POST http://localhost:8888/generate \
-H "Content-Type: application/json" \
-d '{
  "prompt": "A sunset over a mountain range",
  "steps": 50,
  "width": 512,
  "height": 512,
  "cfg": 7.5,
  "denoise": 0.8
}'
```

#### Example Response

```json
{
  "status": "success",
  "image": "base64_encoded_image_data_here"
}
```

### GET `/status`

This endpoint provides the current status of the server, including the version, max queue size, and current number of jobs in the queue.

#### Example Request

```bash
curl -X GET http://localhost:8888/status
```

#### Example Response

```json
{
  "public_configuration": {
    "api_version": "0.1.0",
    "max_queue_size": 5,
    "current_workflow": "Comfy-Org Flux.1-Dev fp8"
  },
  "job_queue": 2
}
```

---

## Configuration

You can configure several settings using environment variables or command-line options. For example:

- **`COMFYUI_API_DEFAULT_HOST`**: Overrides the default host for the API server.
- **`COMFYUI_PATH`**: Path to the ComfyUI installation.

Additionally, the server configuration (such as `max_queue_size`) is exposed via the `/status` endpoint.

---

## Examples

### Python Jupyter Notebook Client Example

You can use Python's `requests` library to interact with the API. Below is an example:

```python
import requests
import json
import base64
from PIL import Image
from io import BytesIO
import matplotlib.pyplot as plt

# Define the URL and payload for image generation
url = "http://localhost:8888/generate"
payload = {
    "prompt": "A futuristic cityscape with flying cars",
    "width": 512,
    "height": 512,
    "steps": 50,
    "cfg": 4.0
}

# Set headers for the request
headers = {
    "Content-Type": "application/json"
}

# Make the POST request
response = requests.post(url, data=json.dumps(payload), headers=headers)

# Check if the request was successful
if response.status_code == 200:
    # Extract the base64-encoded image from the response
    image_base64 = response.json().get("image")

    if image_base64:
        # Decode the base64 string into image bytes
        image_data = base64.b64decode(image_base64)
        
        # Create an image object from the bytes
        image = Image.open(BytesIO(image_data))
        
        # Display the image using matplotlib
        plt.figure(figsize=(10, 10))  # Adjust figure size for better visibility
        plt.imshow(image)
        plt.axis('off')  # Hide axes
        plt.show()
    else:
        print("No image found in the response.")
else:
    print(f"Error: {response.status_code}, {response.text}")
```

---

### License

This project is licensed under the Apache 2.0 License. See the [LICENSE](LICENSE) file for details.

Note, **`FLUX.1 [dev]`** has its own [LICENSE](https://huggingface.co/black-forest-labs/FLUX.1-dev/blob/main/LICENSE.md).

---

### Author

- **Jason Weirather** - [@jason-weirather](https://github.com/jason-weirather)

---
