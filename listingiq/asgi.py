"""ASGI entrypoint for production deployment (Render, etc.)."""

from listingiq.config import load_config
from listingiq.api.server import create_app

cfg = load_config()
app = create_app(cfg)
