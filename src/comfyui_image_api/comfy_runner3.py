import os, time, socket, subprocess, logging, threading, atexit, tempfile, json, yaml
import importlib.resources as pkg_resources

logging.basicConfig(level=logging.INFO)

class ComfyRunner:
    """
    Starts / supervises a background ComfyUI launched via comfy-cli.
    Recovers automatically if the port closes or the process exits.
    """

    # ────────────────────────────────  init  ────────────────────────────────
    def __init__(self, comfyui_path, comfyui_host, comfyui_port,
                 model_path, output_directory):

        self.comfyui_path   = comfyui_path
        self.comfy_host     = comfyui_host
        self.comfy_port     = comfyui_port
        self.output_dir     = output_directory

        self.proc           = None
        self.start_time     = 0.0
        self._cli_started   = False                     # for health endpoint

        # ── build extra-model-paths yaml on the fly ─────────────────────────
        with pkg_resources.path("comfyui_image_api.Templates",
                                "extra_model_paths.yaml") as y_path:
            cfg = yaml.safe_load(y_path.read_text())
        cfg["fluxdev"]["base_path"], self.checkpoint_name = os.path.split(model_path)
        cfg["fluxdev"]["checkpoints"] = "./"


        tmp_yaml = tempfile.NamedTemporaryFile(delete=False, suffix=".yaml", mode="w")
        yaml.dump(cfg, tmp_yaml, indent=2)


        tmp_yaml.close()
        self.temp_yaml_path = tmp_yaml.name
        atexit.register(os.remove, self.temp_yaml_path)

        # locate workflow json
        with pkg_resources.path("comfyui_image_api.Templates.Workflow_api_json",
                                "flex-dev-simple.json") as w_path:
            self.workflow_path = str(w_path)

        # one-time: disable telemetry & stop leftovers
        subprocess.run(["comfy", "--skip-prompt", "--no-enable-telemetry",
                        "tracking", "disable"], stdout=subprocess.DEVNULL)
        self._stop_cli()

        # launch & start watchdog
        self._launch_cli()
        threading.Thread(target=self._watchdog, daemon=True).start()

    # ───────────────────────── internal helpers ────────────────────────────
    def _port_open(self) -> bool:
        """True if tcp port accepts a connection."""
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.settimeout(1)
            return s.connect_ex((self.comfy_host, self.comfy_port)) == 0

    def _stop_cli(self):
        """Best-effort kill for any background ComfyUI."""
        subprocess.run(["comfy", "--skip-prompt", "--no-enable-telemetry",
                        "stop"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        subprocess.run(["pkill", "-f", "main.py.*--listen"],
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    # ─────────────────────────── launch logic ──────────────────────────────
    def _launch_cli(self):
        if self._port_open():
            logging.info("ComfyUI already listening — no launch needed.")
            return

        self._stop_cli()                              # ensure clean slate

        env = os.environ.copy()
        env["COMFY_CLI_DISABLE_UPDATE_CHECK"] = "1"

        cmd = [
            "comfy", "--skip-prompt", "--no-enable-telemetry",
            "--workspace", self.comfyui_path,
            "launch", "--background", "--",
            "--port",  str(self.comfy_port),
            "--listen", self.comfy_host,
            "--extra-model-paths-config", self.temp_yaml_path,
            "--output-directory", self.output_dir
        ]
        logging.info("Launching comfy-cli → %s", " ".join(cmd))
        self.proc = subprocess.Popen(cmd, env=env, start_new_session=True)
        self.start_time  = time.time()
        self._cli_started = True

        # wait up to 30 s for port
        for _ in range(30):
            if self._port_open():
                logging.info("ComfyUI is now accepting connections.")
                return
            time.sleep(1)
        logging.warning("ComfyUI failed to open port after 30 s.")

    # ───────────────────────────── watchdog ────────────────────────────────
    def _watchdog(self):
        retries = 0
        while True:
            dead_proc   = self.proc and self.proc.poll() is not None
            port_closed = not self._port_open()

            if dead_proc or port_closed:
                logging.warning("ComfyUI unhealthy (proc=%s port=%s) — restarting.",
                                dead_proc, port_closed)

                if self.proc and self.proc.poll() is None:
                    self.proc.terminate()
                    try:
                        self.proc.wait(timeout=10)
                    except subprocess.TimeoutExpired:
                        self.proc.kill()

                self._launch_cli()
                retries += 1
                if retries > 3:
                    logging.error("Failed 3 restarts, backing off for 5 min.")
                    retries = 0
                    time.sleep(300)
            else:
                retries = 0                                   # healthy
            time.sleep(20)

    # ─────────────────────── public helpers (health) ───────────────────────
    def is_alive(self) -> bool:
        return self._cli_started and self._port_open()

    def uptime(self) -> float:
        return time.time() - self.start_time if self.is_alive() else 0.0

    # ───────────────────────── image generation ────────────────────────────
    def generate_image(self, data):
        with open(self.workflow_path, "r") as fh:
            wf = json.load(fh)

        wf["30"]["inputs"]["ckpt_name"] = self.checkpoint_name
        wf["31"]["inputs"]["seed"]      = data["seed"]
        wf["31"]["inputs"]["steps"]     = data["steps"]
        wf["31"]["inputs"]["denoise"]   = data["denoise"]
        wf["35"]["inputs"]["guidance"]  = data["cfg"]
        wf["6"]["inputs"]["text"]       = data["prompt"]
        wf["27"]["inputs"]["width"]     = data["width"]
        wf["27"]["inputs"]["height"]    = data["height"]

        with tempfile.NamedTemporaryFile(delete=True, suffix=".json") as tf:
            json.dump(wf, tf, indent=2); tf.flush()
            result = subprocess.run(
                ["comfy", "run", "--workflow", tf.name, "--wait"],
                stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True
            )
            if result.returncode != 0:
                raise RuntimeError(result.stderr)
