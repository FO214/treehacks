"""
CLI: python -m repo_to_png /path/to/dir [-o diagram.png] [--openai-key KEY]
"""
import argparse
import json
import sys
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Generate a system architecture diagram (PNG) from a local directory."
    )
    parser.add_argument(
        "directory",
        metavar="DIR",
        help="Path to project directory (must contain a README)",
    )
    parser.add_argument(
        "-o", "--output",
        default="diagram.png",
        help="Output PNG path (default: diagram.png)",
    )
    parser.add_argument(
        "--openai-key",
        default=None,
        help="OpenAI API key (or set OPENAI_API_KEY)",
    )
    parser.add_argument(
        "--model",
        default="o4-mini",
        help="OpenAI model (default: o4-mini)",
    )
    parser.add_argument(
        "--components-json",
        default=None,
        metavar="PATH",
        help="Write component positions to JSON (default: <output>.components.json)",
    )
    args = parser.parse_args()

    try:
        from . import repo_to_png
        png_bytes, component_positions = repo_to_png(
            args.directory,
            output_path=args.output,
            openai_api_key=args.openai_key,
            model=args.model,
        )
        print(f"Wrote {args.output}")

        # Component list with pixel x,y
        components_data = [
            {"id": c.id, "label": c.label, "x": c.x, "y": c.y}
            for c in component_positions
        ]
        json_path = args.components_json
        if json_path is None:
            json_path = str(Path(args.output).with_suffix("")) + ".components.json"
        Path(json_path).write_text(
            json.dumps(components_data, indent=2),
            encoding="utf-8",
        )
        print(f"Wrote {json_path} ({len(component_positions)} components)")
        return 0
    except FileNotFoundError as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1
    except ValueError as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
