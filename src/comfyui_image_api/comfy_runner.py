import subprocess
import os
import json
import random
import tempfile
import yaml
import atexit
import sys
import logging
import threading
import time

import importlib.resources as pkg_resources

logging.basicConfig(level=logging.INFO)

class ComfyRunner:
    def __init__(
        self,
        comfyui_path,
        comfyui_host,
        comfyui_port,
        model_path,
        output_directory
    ):
        self.comfyui_path     = comfyui_path
        self.output_directory = output_directory
        self.comfy_host       = comfyui_host
        self.comfy_port       = comfyui_port
        self.proc             = None
        self.start_time       = None
        self._cli_was_launched = False

        # Use a context manager to get the path to the extra_model_paths.yaml file
        with pkg_resources.path("comfyui_image_api.Templates", "extra_model_paths.yaml") as yaml_file_path:
            template_extra_models = yaml.safe_load(open(yaml_file_path).read())
            print(template_extra_models)
            template_extra_models['fluxdev']['base_path'], self.checkpoint_name = os.path.split(model_path)
            template_extra_models['fluxdev']['checkpoints'] = './'

            with tempfile.NamedTemporaryFile(mode='w+', suffix='.yaml', delete=False) as temp_yaml:
                self.temp_yaml_path = temp_yaml.name
                atexit.register(os.remove, self.temp_yaml_path)
                temp_yaml.write(yaml.dump(template_extra_models,indent=2))
                temp_yaml.flush()
            print(f"Temporary yaml created at: {self.temp_yaml_path}")


            self.extra_model_paths = str(yaml_file_path)
        with pkg_resources.path("comfyui_image_api.Templates.Workflow_api_json", "flex-dev-simple.json") as json_file_path:
            self.model_config_path = str(json_file_path)
        print("Extra model paths:")
        print(self.extra_model_paths)

        # Disable that weird tracking thing
        subprocess.run(["comfy","--skip-prompt","--no-enable-telemetry", "tracking","disable"], 
                       stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)

        # Stop any previously running server
        subprocess.run(["comfy","--skip-prompt","--no-enable-telemetry", "stop"],
                       stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)

        # Start and monitor comfy-cli
        self._launch_cli()
        self.monitor_thread = threading.Thread(target=self._watchdog, daemon=True)
        self.monitor_thread.start()

        threading.Thread(target=self._reap_zombies_forever, daemon=True).start()


    # ───────────────────────────────────────────────────────────────
    # Helper: is the ComfyUI port accepting TCP?
    # ───────────────────────────────────────────────────────────────
    def _port_open(self) -> bool:
        import socket
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.settimeout(1)
            return sock.connect_ex((self.comfy_host, self.comfy_port)) == 0

    # ───────────────────────────────────────────────────────────────
    # Helper: stop any background ComfyUI that may have a stale PID
    # ───────────────────────────────────────────────────────────────
    def _stop_cli(self):
        subprocess.run(
            ["comfy", "--skip-prompt", "--no-enable-telemetry", "stop"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            text=True,
        )

        # also nuke orphaned python main.py (safety net)
        subprocess.run(
            ["pkill", "-f", "main.py.*--listen"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )

    # ───────────────────────────────────────────────────────────────
    # Start ComfyUI only if its port is closed
    # ───────────────────────────────────────────────────────────────
    def _launch_cli(self):
        if self._port_open():
            logging.info("ComfyUI already listening — no launch needed.")
            return

        # make sure nothing stale is holding the port/PID file
        self._stop_cli()

        env = os.environ.copy()
        env["COMFY_CLI_DISABLE_UPDATE_CHECK"] = "1"        # ✋ no phone-home

        cmd = [
            "comfy", "--skip-prompt", "--no-enable-telemetry",
            "--workspace", self.comfyui_path,
            "launch", "--background", "--",
            "--port",  str(self.comfy_port),
            "--listen", self.comfy_host,
            "--extra-model-paths-config", self.temp_yaml_path,
            "--output-directory", self.output_directory
        ]
        logging.info("Launching comfy-cli → %s", " ".join(cmd))
        self.proc = subprocess.Popen(cmd, env=env, start_new_session=True)
        threading.Thread(target=os.wait, daemon=True).start()
        self.start_time = time.time()
        self._cli_was_launched = True

        # Wait (max 30 s) for the port to open once
        for _ in range(30):
            if self._port_open():
                logging.info("ComfyUI is now accepting connections.")
                return
            time.sleep(1)
        logging.warning("ComfyUI failed to open port after 30 s.")

    # ───────────────────────────────────────────────────────────────
    # Watchdog: poll every 20 s; if port is closed try up to 3 times
    # ───────────────────────────────────────────────────────────────
    def _watchdog2(self):
        retries = 0
        while True:
            if self.proc and self._port_open() is None:
                logging.warning("ComfyUI port closed — attempting restart.")
                self._launch_cli()
                retries += 1
                if retries > 3:
                    logging.error("ComfyUI failed to recover after 3 attempts; giving up until next poll")
                    retries = 0                         # reset counter
            else:
                retries = 0                             # healthy ⇒ reset
            time.sleep(20)


    def _watchdog(self):
        retries = 0
        while True:
            if not self._port_open():
                logging.warning("ComfyUI port closed — attempting restart.")

                # If a proc exists and is still running, terminate it
                if self.proc and self.proc.poll() is None:
                    logging.info("Terminating stale comfy process...")
                    self.proc.terminate()
                    try:
                        self.proc.wait(timeout=10)
                    except subprocess.TimeoutExpired:
                        logging.warning("Force-killing unresponsive comfy process.")
                        self.proc.kill()

                self._launch_cli()
                retries += 1

                if retries > 3:
                    logging.error("ComfyUI failed to recover after 3 attempts; giving up until next poll.")
                    retries = 0
            else:
                retries = 0  # healthy — reset counter

            time.sleep(20)


    def is_alive(self) -> bool:
        return self._cli_was_launched and self._port_open()

    def uptime(self) -> float:
        return time.time() - self.start_time if self.is_alive() else 0.0

    def generate_image(self, data):
        print(data)
        # Load the workflow template
        with open(self.model_config_path, 'rt') as f:
            workflow = json.load(f)

        workflow['30']['inputs']['ckpt_name'] = self.checkpoint_name
        workflow['31']['inputs']['seed'] = data['seed']
        workflow['31']['inputs']['steps'] = data['steps']
        workflow['31']['inputs']['denoise'] = data['denoise']
        workflow['35']['inputs']['guidance'] = data['cfg']
        workflow['6']['inputs']['text'] = data['prompt']
        # Set image size
        workflow['27']['inputs']['width'] = data['width']
        workflow['27']['inputs']['height'] = data['height']

        # Create a temporary file for the workflow
        with tempfile.NamedTemporaryFile(mode='w+', suffix='.json', delete=True) as temp_workflow_file:
            # Write the updated workflow to the temp file
            temp_workflow_file.write(json.dumps(workflow, indent=2))
            temp_workflow_file.flush()  # Ensure data is written to disk

            # Run ComfyUI with the temporary workflow file
            cmd = f"comfy run --workflow {temp_workflow_file.name} --wait".split()

            # Capture output only on error
            result = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)

            # If there's an error, raise an exception and show the error output
            if result.returncode != 0:
                raise Exception(f"Error generating image: {result.stderr}")

        return "Image generation completed."

    def _reap_zombies_forever(self):
        """Continuously reaps exited children to avoid zombies."""
        import errno
        while True:
            try:
                # Wait for any child process without blocking
                while True:
                    pid, _ = os.waitpid(-1, os.WNOHANG)
                    if pid == 0:
                        break
            except ChildProcessError:
                break
            except OSError as e:
                if e.errno != errno.ECHILD:
                    raise
            time.sleep(1)
