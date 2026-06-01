"""Small helpers (lifted from the prototype)."""
import base64
from pathlib import Path


def encode_image(image_path: str) -> str:
    """Return the base64-encoded contents of an image file."""
    with open(image_path, "rb") as f:
        return base64.b64encode(f.read()).decode("utf-8")


def data_url(b64: str, mime: str = "image/jpeg") -> str:
    """Wrap a base64 string as a data URL for the chat image_url content type."""
    return f"data:{mime};base64,{b64}"
