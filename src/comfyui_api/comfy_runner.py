import subprocess
import os
import json
import random
import tempfile
import yaml
import atexit
import sys

import importlib.resources as pkg_resources

class ComfyRunner:
    def __init__(self, comfyui_path, comfyui_host, comfyui_port, model_path, output_directory):
        self.comfyui_path = comfyui_path
        self.output_directory = output_directory

        # Use a context manager to get the path to the extra_model_paths.yaml file
        with pkg_resources.path("comfyui_image_api.Templates", "extra_model_paths.yaml") as yaml_file_path:
            template_extra_models = yaml.safe_load(open(yaml_file_path).read())
            print(template_extra_models)
            template_extra_models['fluxdev']['base_path'], self.checkpoint_name = os.path.split(model_path)
            template_extra_models['fluxdev']['checkpoints'] = './'

            with tempfile.NamedTemporaryFile(mode='w+', suffix='.yaml', delete=False) as temp_yaml:
                temp_yaml_path = temp_yaml.name
                atexit.register(os.remove, temp_yaml_path)
                temp_yaml.write(yaml.dump(template_extra_models,indent=2))
                print(yaml.dump(template_extra_models,indent=2))
            print(f"Temporary yaml created at: {temp_yaml_path}")


            self.extra_model_paths = str(yaml_file_path)
        with pkg_resources.path("comfyui_image_api.Templates.Workflow_api_json", "flex-dev-simple.json") as json_file_path:
            self.model_config_path = str(json_file_path)
        print("Extra model paths:")
        print(self.extra_model_paths)

        # Disable that weird tracking thing
        result = subprocess.run(["comfy","--skip-prompt","--no-enable-telemetry", "tracking","disable"], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)

        # Print the output
        print("Output:")
        print(result.stdout)
        # Print any error messages
        if result.stderr:
            print("Error:")
            print(result.stderr)
        # Stop any currently running server
        result = subprocess.run(["comfy","--skip-prompt","--no-enable-telemetry", "stop"], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        # Print the output
        print("Output:")
        print(result.stdout)
        # Print any error messages
        if result.stderr:
            print("Error:")
            print(result.stderr)
        # Start a freshly running server
        cmd = ["comfy","--skip-prompt","--no-enable-telemetry","--workspace",comfyui_path,"launch","--background","--",
               "--port",f"{comfyui_port}",
               "--listen",f"{comfyui_host}",
               "--extra-model-paths-config",temp_yaml_path,
               "--output-directory",output_directory
              ]
        print(f"Starting launch workspace: {' '.join(cmd)}")

        # Run the command and capture the output
        result = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        if result.stderr:
            raise Exception(f"Error generating image: {result.stderr}")

        # Print the output
        print("Output:")
        print(result.stdout)

        # Print any error messages
        if result.stderr:
            print("Error:")
            print(result.stderr)


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

