"""Select video renderer from settings."""

from __future__ import annotations

from src.config import Settings
from src.renderers.faceless import FacelessFfmpegRenderer
from src.renderers.heygen import HeyGenRenderer
from src.renderers.hybrid import HybridRenderer


def get_renderer(settings: Settings):
    mode = settings.renderer.lower()
    if mode == "heygen":
        return HeyGenRenderer(settings)
    if mode == "hybrid":
        return HybridRenderer(settings)
    if mode == "faceless":
        return FacelessFfmpegRenderer()
    raise ValueError(
        f"Unknown RENDERER={settings.renderer!r}. Use 'faceless', 'heygen', or 'hybrid'."
    )
