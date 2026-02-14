"""
Test pipeline that renders the diagram via mermaid.ink (same service mermaid-py uses)
and prints the image URL. No Node/Chrome required; uses the pipeline to get Mermaid
code then builds the mermaid.ink URL.

Use --positions to fetch SVG from mermaid.ink and run an SVG-based checker for block
render positions (same logic as mmdc path, but no local CLI needed).

Run from repo root: python -m server.diagram_mermaid_ink
Or with a directory: python -m server.diagram_mermaid_ink /path/to/repo

Requires: OPENAI_API_KEY for full pipeline. No pip Mermaid package needed (URLs built with stdlib).
"""
import base64
import json
import sys
import urllib.request
import zlib
from pathlib import Path

# Mermaid.ink base URL (used by mermaid-py by default)
MERMAID_INK_BASE = "https://mermaid.ink"


def mermaid_to_ink_url(
    mermaid_code: str,
    *,
    image_type: str = "png",
    bg_color: str | None = "!white",
) -> str:
    """
    Build a mermaid.ink image URL from raw Mermaid diagram code.
    Uses pako-style encoding: JSON {code: "..."} deflated then base64url.
    """
    # mermaid.ink accepts pako encoding: JSON {code}, deflate (zlib or raw), base64url
    payload = json.dumps({"code": mermaid_code})
    # Use zlib format (with header); some clients expect this
    compressed = zlib.compress(payload.encode("utf-8"))
    b64 = base64.urlsafe_b64encode(compressed).decode("ascii").rstrip("=")
    encoded = f"pako:{b64}"
    params = []
    if bg_color:
        params.append(f"bgColor={bg_color}")
    if image_type == "svg":
        qs = "&".join(params)
        suffix = "?" + qs if qs else ""
        return f"{MERMAID_INK_BASE}/svg/{encoded}{suffix}"
    if image_type and image_type != "jpeg":
        params.append(f"type={image_type}")
    qs = "&".join(params)
    suffix = "?" + qs if qs else ""
    return f"{MERMAID_INK_BASE}/img/{encoded}{suffix}"


def run_pipeline_and_render_url(
    directory: str | Path,
    *,
    openai_api_key: str | None = None,
    model: str = "o4-mini",
    image_type: str = "png",
) -> tuple[str, str]:
    """
    Run the repo → Mermaid pipeline, then return (mermaid_code, image_url).
    The image URL can be opened in a browser or used as img src.
    """
    _this_dir = Path(__file__).resolve().parent
    if str(_this_dir) not in sys.path:
        sys.path.insert(0, str(_this_dir))
    from repo_to_png.pipeline import run_pipeline

    result = run_pipeline(
        directory,
        openai_api_key=openai_api_key,
        model=model,
    )
    url = mermaid_to_ink_url(result.mermaid, image_type=image_type)
    return (result.mermaid, url)


# Sample diagram for testing without running the full pipeline (no OPENAI_API_KEY needed)
SAMPLE_MERMAID = """
flowchart LR
    A[Frontend] --> B[API]
    B --> C[Database]
    A --> D[Cache]
"""


def fetch_svg_positions(
    svg_url: str,
    *,
    png_width: int = 1920,
    png_height: int = 1080,
):
    """
    Fetch SVG from mermaid.ink (or any URL), parse it, and return component positions
    in PNG pixel coordinates (SVG-based checker for block positions).
    """
    _this_dir = Path(__file__).resolve().parent
    if str(_this_dir) not in sys.path:
        sys.path.insert(0, str(_this_dir))
    from repo_to_png.mermaid_to_png import svg_to_component_positions

    req = urllib.request.Request(svg_url, headers={"User-Agent": "Mozilla/5.0 (compatible; diagram_mermaid_ink/1.0)"})
    with urllib.request.urlopen(req, timeout=30) as resp:
        svg_bytes = resp.read()
    return svg_to_component_positions(svg_bytes, png_width=png_width, png_height=png_height)


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(description="Run pipeline and get mermaid.ink image URL")
    parser.add_argument(
        "directory",
        nargs="?",
        default=None,
        help="Repo directory to diagram (default: cwd). Use --sample to skip pipeline.",
    )
    parser.add_argument(
        "--sample",
        action="store_true",
        help="Use a sample diagram only (no pipeline, no API key). Prints image URL.",
    )
    parser.add_argument(
        "--type",
        dest="image_type",
        default="png",
        choices=("png", "svg", "webp", "jpeg"),
        help="Image type for mermaid.ink URL (default: png). Use png for /img/, svg for /svg/.",
    )
    parser.add_argument(
        "--positions",
        action="store_true",
        help="Fetch SVG and run SVG-based checker: print block positions (id, label, x, y).",
    )
    args = parser.parse_args()

    if args.sample:
        mermaid_code = SAMPLE_MERMAID.strip()
        url = mermaid_to_ink_url(mermaid_code, image_type=args.image_type)
        print("--- Sample Mermaid ---")
        print(mermaid_code)
        print("\n--- Image URL (mermaid.ink) ---")
        print(url)
        if args.positions:
            svg_url = mermaid_to_ink_url(mermaid_code, image_type="svg")
            print("\n--- SVG-based block positions (1920×1080 coords) ---")
            try:
                positions = fetch_svg_positions(svg_url)
                for c in positions:
                    print(f"  {c.id}: {c.name!r} @ ({c.x}, {c.y})")
            except Exception as e:
                print(f"  Failed to fetch/parse SVG: {e}", file=sys.stderr)
        else:
            print("\nOpen the URL in a browser to view the diagram.")
        return

    directory = Path(args.directory or ".").resolve()
    print(f"Running pipeline for: {directory}")
    try:
        mermaid_code, image_url = run_pipeline_and_render_url(
            directory, image_type=args.image_type
        )
    except Exception as e:
        print(f"Pipeline failed: {e}", file=sys.stderr)
        sys.exit(1)
    print("\n--- Mermaid code (first 500 chars) ---")
    print(mermaid_code[:500] + ("..." if len(mermaid_code) > 500 else ""))
    print("\n--- Image URL (mermaid.ink) ---")
    print(image_url)
    if args.positions:
        svg_url = mermaid_to_ink_url(mermaid_code, image_type="svg")
        print("\n--- SVG-based block positions (1920×1080 coords) ---")
        try:
            positions = fetch_svg_positions(svg_url)
            for c in positions:
                print(f"  {c.id}: {c.name!r} @ ({c.x}, {c.y})")
        except Exception as e:
            print(f"  Failed to fetch/parse SVG: {e}", file=sys.stderr)
    else:
        print("\nOpen the URL above in a browser to view the diagram.")


if __name__ == "__main__":
    main()
