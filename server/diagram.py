"""
Single entry point for repo → PNG: call this from another component.
Runs the pipeline (file tree + README → OpenAI → Mermaid → PNG) and returns the result.
"""
from pathlib import Path

from .repo_to_png.mermaid_to_png import ComponentPosition, mermaid_to_png
from .repo_to_png.pipeline import run_pipeline


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
