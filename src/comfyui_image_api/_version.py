# comfyui_image_api/_version.py

import os
import tomllib

def get_version():
    # Get three directories up to get the path to pyproject.toml
    base_dir = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))
    pyproject_path = os.path.join(base_dir, 'pyproject.toml')

    # Read the version from pyproject.toml
    with open(pyproject_path, 'rb') as f:
        pyproject_data = tomllib.load(f)

    # Return the version from the [project] section
    return pyproject_data['project']['version']

# Expose the version as __version__
__version__ = get_version()
