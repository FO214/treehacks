"""
Repo-to-PNG: Generate a system architecture diagram (PNG) from a local directory.
Pipeline: directory → file tree + README → 3-step OpenAI → Mermaid → PNG (1920×1080).
"""
from pathlib import Path

from .mermaid_to_png import ComponentPosition, mermaid_to_png
from .pipeline import PipelineResult, run_pipeline

__all__ = [
    "ComponentPosition",
    "PipelineResult",
    "mermaid_to_png",
    "repo_to_png",
    "run_pipeline",
]


def repo_to_png(
    directory: str | Path,
    *,
    output_path: str | None = None,
    openai_api_key: str | None = None,
    model: str = "o4-mini",
) -> tuple[bytes, list[ComponentPosition]]:
    """
    Generate a PNG diagram for a local directory. Output is always 1920×1080.

    Args:
        directory: Path to the project directory (must contain a README).
        output_path: If set, write PNG to this path as well as returning bytes.
        openai_api_key: Optional OpenAI API key (else OPENAI_API_KEY env).
        model: OpenAI model (default o4-mini).

    Returns:
        Tuple of (PNG file content as bytes, list of ComponentPosition for each core
        component block with id, label, and pixel x,y on the output PNG).
    """
    result = run_pipeline(
        directory,
        openai_api_key=openai_api_key,
        model=model,
    )
    png_bytes, component_positions = mermaid_to_png(result.mermaid)
    if output_path:
        Path(output_path).write_bytes(png_bytes)
    return (png_bytes, component_positions)
