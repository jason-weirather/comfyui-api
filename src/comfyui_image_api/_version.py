try:
    from importlib.metadata import version
except ImportError:
    from importlib_metadata import version  # Python < 3.8

__version__ = version("comfyui_image_api")
