"""
Single entry point for repo → SVG diagram. Call from another component.
Runs the pipeline (file tree + README → OpenAI → Mermaid) then renders to SVG.

Run: python -m server.diagram [dir] [-o diagram.svg]
"""
import sys
from pathlib import Path

_this_dir = Path(__file__).resolve().parent
if __name__ == "__main__":
    if str(_this_dir) not in sys.path:
        sys.path.insert(0, str(_this_dir))
    from repo_to_png.mermaid_to_png import ComponentPosition, mermaid_to_png, mermaid_to_svg
    from repo_to_png.pipeline import run_pipeline
else:
    from .repo_to_png.mermaid_to_png import ComponentPosition, mermaid_to_png, mermaid_to_svg
    from .repo_to_png.pipeline import run_pipeline


def repo_to_svg(
    directory: str | Path,
    *,
    output_path: str | None = None,
    openai_api_key: str | None = None,
    model: str = "o4-mini",
) -> tuple[bytes, list[ComponentPosition]]:
    """
    Generate an SVG diagram for a local directory.

    Args:
        directory: Path to the project directory (must contain a README).
        output_path: If set, write SVG to this path as well as returning bytes.
        openai_api_key: Optional OpenAI API key (else OPENAI_API_KEY env).
        model: OpenAI model (default o4-mini).

    Returns:
        Tuple of (SVG file content as bytes, list of ComponentPosition for each block
        with id, label, name, and x,y in reference 1920×1080 coords).
    """
    result = run_pipeline(
        directory,
        openai_api_key=openai_api_key,
        model=model,
    )
    out_path = Path(output_path) if output_path else None
    use_png = out_path and str(out_path).lower().endswith(".png")
    if use_png:
        img_bytes = mermaid_to_png(result.mermaid)
        if output_path:
            Path(output_path).write_bytes(img_bytes)
        return (img_bytes, [])
    svg_bytes, component_positions = mermaid_to_svg(result.mermaid)
    if output_path:
        Path(output_path).write_bytes(svg_bytes)
    return (svg_bytes, component_positions)


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Generate architecture diagram (SVG) from repo")
    parser.add_argument("dir", nargs="?", default=None, help="Directory to diagram (default: cwd)")
    parser.add_argument("-o", "--output", dest="output_path", default="diagram.svg", help="Output path: .svg or .png (default: diagram.svg)")
    args = parser.parse_args()
    directory = Path(args.dir or ".").resolve()

    img_bytes, component_positions = repo_to_svg(
        directory, output_path=args.output_path
    )
    fmt = "PNG" if str(args.output_path).lower().endswith(".png") else "SVG"
    print(f"{fmt} written to {args.output_path} ({len(img_bytes)} bytes).")
    if component_positions:
        print(f"Components ({len(component_positions)}):")
        for c in component_positions:
            print(f"  {c.id}: {c.name!r} @ ({c.x}, {c.y})")
