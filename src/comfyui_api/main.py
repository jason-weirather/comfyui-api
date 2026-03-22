import uvicorn

from comfyui_api.settings import get_settings


def main() -> None:
    settings = get_settings()
    uvicorn.run(
        "comfyui_api.app:create_app",
        factory=True,
        host=settings.api_host,
        port=settings.api_port,
        workers=1,
    )


if __name__ == "__main__":
    main()
