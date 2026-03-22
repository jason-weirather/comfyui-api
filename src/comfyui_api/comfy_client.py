import json
import time
from typing import Any

import httpx


class ComfyUIClient:
    def __init__(self, base_url: str) -> None:
        self.base_url = base_url.rstrip("/")
        self.client = httpx.Client(
            base_url=self.base_url,
            timeout=httpx.Timeout(connect=5.0, read=60.0, write=60.0, pool=60.0),
        )

    def close(self) -> None:
        self.client.close()

    def _get_json(self, path: str, **kwargs) -> dict[str, Any]:
        response = self.client.get(path, **kwargs)
        response.raise_for_status()
        return response.json()

    def _post_json(self, path: str, payload: dict[str, Any], **kwargs) -> dict[str, Any]:
        response = self.client.post(path, json=payload, **kwargs)
        response.raise_for_status()
        return response.json()

    def get_system_stats(self) -> dict[str, Any]:
        return self._get_json("/system_stats")

    def get_features(self) -> dict[str, Any]:
        return self._get_json("/features")

    def list_models(self, folder: str) -> Any:
        return self._get_json(f"/models/{folder}")

    def get_queue(self) -> dict[str, Any]:
        return self._get_json("/queue")

    def get_history(self, prompt_id: str | None = None) -> dict[str, Any]:
        if prompt_id is None:
            return self._get_json("/history")
        return self._get_json(f"/history/{prompt_id}")

    def submit_prompt(self, workflow: dict[str, Any], client_id: str) -> dict[str, Any]:
        payload = {"prompt": workflow, "client_id": client_id}
        data = self._post_json("/prompt", payload)
        if "error" in data:
            raise RuntimeError(
                f"ComfyUI prompt validation failed: {json.dumps(data, ensure_ascii=False)}"
            )
        return data

    def view_file(self, filename: str, subfolder: str = "", folder_type: str = "output") -> bytes:
        params = {"filename": filename, "type": folder_type}
        if subfolder:
            params["subfolder"] = subfolder

        response = self.client.get("/view", params=params)
        response.raise_for_status()
        return response.content

    def upload_image(
        self,
        fileobj,
        filename: str,
        overwrite: bool = False,
        image_type: str = "input",
        subfolder: str | None = None,
    ) -> dict[str, Any]:
        data = {
            "overwrite": "true" if overwrite else "false",
            "type": image_type,
        }
        if subfolder:
            data["subfolder"] = subfolder

        response = self.client.post(
            "/upload/image",
            data=data,
            files={"image": (filename, fileobj)},
        )
        response.raise_for_status()
        return response.json()

    def wait_for_completion(
        self,
        prompt_id: str,
        timeout_s: int,
        poll_interval_s: float,
    ) -> dict[str, Any]:
        deadline = time.monotonic() + timeout_s

        while time.monotonic() < deadline:
            history = self.get_history(prompt_id)
            if prompt_id in history:
                item = history[prompt_id]
                status = (item.get("status") or {}).get("status_str", "")
                outputs = self.extract_output_assets(item)

                if outputs:
                    return item

                if str(status).lower() == "error":
                    raise RuntimeError(
                        f"ComfyUI execution failed: {json.dumps(item.get('status', {}), ensure_ascii=False)}"
                    )

            time.sleep(poll_interval_s)

        raise TimeoutError(f"Timed out waiting for prompt_id={prompt_id}")

    @staticmethod
    def extract_output_assets(history_item: dict[str, Any]) -> list[dict[str, Any]]:
        assets: list[dict[str, Any]] = []
        for _, node_output in (history_item.get("outputs") or {}).items():
            for key in ("images", "gifs", "audio"):
                for asset in node_output.get(key, []):
                    if isinstance(asset, dict) and "filename" in asset:
                        assets.append(asset)
        return assets
