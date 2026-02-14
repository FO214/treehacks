"""
Single entry point for repo → PNG: call this from another component.
Runs the pipeline (file tree + README → OpenAI → Mermaid → PNG) and returns the result.
"""
import io
from pathlib import Path

from .repo_to_png.mermaid_to_png import ComponentPosition, mermaid_to_png
from .repo_to_png.pipeline import run_pipeline

# PNG size from mermaid_to_png
_DEFAULT_WIDTH = 1920
_DEFAULT_HEIGHT = 1080


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


def _display_result(png_bytes: bytes, component_positions: list[ComponentPosition]) -> None:
    """Show image and xy points with matplotlib."""
    import matplotlib.pyplot as plt
    import matplotlib.image as mpimg

    fig, ax = plt.subplots(figsize=(14, 8))
    img = mpimg.imread(io.BytesIO(png_bytes))
    ax.imshow(img)
    ax.set_axis_off()

    # Overlay component positions (image coords: y down; matplotlib: y up)
    xs = [c.x for c in component_positions]
    ys = [_DEFAULT_HEIGHT - c.y for c in component_positions]
    ax.scatter(xs, ys, c="red", s=40, alpha=0.9, edgecolors="white", linewidths=1, zorder=5)
    for c in component_positions:
        ax.annotate(
            f"{c.label} ({c.x}, {c.y})",
            (c.x, _DEFAULT_HEIGHT - c.y),
            xytext=(8, 8),
            textcoords="offset points",
            fontsize=7,
            color="white",
            bbox=dict(boxstyle="round,pad=0.2", facecolor="black", alpha=0.75),
            zorder=10,
        )
    plt.tight_layout()
    plt.show()


if __name__ == "__main__":
    png_bytes, component_positions = repo_to_png(Path.cwd())
    print(f"Components ({len(component_positions)}):")
    for c in component_positions:
        print(f"  {c.id}: {c.label!r} @ ({c.x}, {c.y})")
    _display_result(png_bytes, component_positions)
