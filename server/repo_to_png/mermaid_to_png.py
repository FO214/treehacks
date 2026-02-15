"""
Render Mermaid diagram string to SVG using mermaid-cli (mmdc).
Extracts component block positions (nodes and subgraphs) in reference 1920×1080 coords.
Uses mmdc from PATH if present, else npx @mermaid-js/mermaid-cli.
Requires: Node.js + npm (for npx) or global: npm install -g @mermaid-js/mermaid-cli
"""
import json
import re
import shutil
import subprocess
import tempfile
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import NamedTuple

# Reference dimensions for SVG output and position mapping
DEFAULT_WIDTH = 1920
DEFAULT_HEIGHT = 1080

# Single mermaid-cli package; npx runs it without global install
_NPX_MMDC = ["npx", "--yes", "@mermaid-js/mermaid-cli"]

# Mermaid config to encourage 16:9-friendly rendering (flowchart uses viewport well)
_MMDC_16_9_CONFIG = {
    "flowchart": {
        "useMaxWidth": True,
        "diagramPadding": 16,
        "nodeSpacing": 45,
        "rankSpacing": 50,
    },
}


# Characters that require the node label to be quoted in Mermaid (e.g. in [label])
_MERMAID_LABEL_SPECIAL = re.compile(r"[()\[\]/\\;,:]")


def _sanitize_mermaid_click_lines(mermaid_code: str) -> str:
    """
    Remove all click directives so the diagram is a static image with no clickables.
    """
    lines = mermaid_code.splitlines()
    out = [line for line in lines if not line.strip().lower().startswith("click ")]
    return "\n".join(out)


def _sanitize_mermaid_node_labels(mermaid_code: str) -> str:
    """
    Wrap unquoted rectangle node labels that contain special characters in double quotes
    so the Mermaid parser does not fail (e.g. Client[Client (curl/Poke)] -> Client["Client (curl/Poke)"]).
    Newlines in labels are replaced with spaces; only double-quote is escaped to avoid parser issues.
    """
    def repl(m: re.Match) -> str:
        content = m.group(1)
        if content.startswith('"') or content.startswith("["):
            return m.group(0)
        if not _MERMAID_LABEL_SPECIAL.search(content) and "\n" not in content:
            return m.group(0)
        # Normalize newlines to space (avoid \\n escaping which can break Mermaid parser)
        content = content.replace("\r\n", " ").replace("\n", " ").replace("\r", " ")
        content = re.sub(r"  +", " ", content).strip()
        # Use apostrophe for internal double-quotes so we don't emit \" (parser can choke)
        content = content.replace('"', "'")
        return f'["{content}"]'
    return re.sub(r'\[([^\]]+)\]', repl, mermaid_code)


def _mermaid_code_for_16_9(mermaid_code: str) -> str:
    """
    Normalize Mermaid code so the layout tends to fill a 16:9 viewport.
    Replaces top-down flowchart direction with left-right so the same graph
    lays out wide instead of tall.
    """
    lines = mermaid_code.splitlines()
    for i, line in enumerate(lines):
        stripped = line.strip()
        if not stripped or stripped.startswith("%%"):
            continue
        # First non-empty, non-directive line: if it's flowchart/graph TB or TD, use LR
        if re.match(r"^(flowchart|graph)\s+(TB|TD)\b", stripped, re.IGNORECASE):
            lines[i] = re.sub(r"\b(TB|TD)\b", "LR", line, count=1, flags=re.IGNORECASE)
            break
        break
    return "\n".join(lines)


def _get_mmdc_cmd(explicit_path: str | None) -> list[str]:
    """Return command as list: [mmdc] or [npx, --yes, @mermaid-js/mermaid-cli]. Prefer mmdc in PATH."""
    if explicit_path:
        return [explicit_path]
    if shutil.which("mmdc"):
        return ["mmdc"]
    if shutil.which("npx"):
        return _NPX_MMDC.copy()
    raise FileNotFoundError(
        "mermaid-cli (mmdc) not found. Install Node.js and run again (npx will use @mermaid-js/mermaid-cli), "
        "or: npm install -g @mermaid-js/mermaid-cli"
    )


class ComponentPosition(NamedTuple):
    """A single core component block from the diagram with its position (reference coords)."""

    id: str
    label: str
    name: str  # Human-readable block name (same as label, for explicit API)
    x: int
    y: int


def _strip_ns(tag: str) -> str:
    """Remove XML namespace from tag if present."""
    if tag and "}" in tag:
        return tag.split("}", 1)[1]
    return tag or ""


def _parse_transform(transform_attr: str | None) -> tuple[float, float]:
    """Parse SVG transform to get translation (tx, ty). Supports translate(...) and matrix(...)."""
    if not transform_attr or not transform_attr.strip():
        return (0.0, 0.0)
    # translate(tx) or translate(tx ty) or translate(tx, ty)
    m = re.search(r"translate\s*\(\s*([-\d.]+)\s*(?:[, ]\s*([-\d.]+)\s*)?\)", transform_attr)
    if m:
        tx = float(m.group(1))
        ty = float(m.group(2)) if m.group(2) is not None else 0.0
        return (tx, ty)
    # matrix(a, b, c, d, e, f): (x,y) -> (a*x + c*y + e, b*x + d*y + f); translation is (e, f)
    m = re.search(
        r"matrix\s*\(\s*([-\d.]+)\s*[, ]\s*([-\d.]+)\s*[, ]\s*([-\d.]+)\s*[, ]\s*([-\d.]+)\s*[, ]\s*([-\d.]+)\s*[, ]\s*([-\d.]+)\s*\)",
        transform_attr,
    )
    if m:
        e, f = float(m.group(5)), float(m.group(6))
        return (e, f)
    return (0.0, 0.0)


def _get_rect_bbox(el: ET.Element) -> tuple[float, float, float, float] | None:
    """Get (x, y, width, height) from an SVG rect element. Returns None if not a rect or missing."""
    if _strip_ns(el.tag) != "rect":
        return None
    try:
        x = float(el.get("x", 0))
        y = float(el.get("y", 0))
        w = float(el.get("width", 0))
        h = float(el.get("height", 0))
        return (x, y, w, h)
    except (TypeError, ValueError):
        return None


def _get_polygon_bbox(el: ET.Element) -> tuple[float, float, float, float] | None:
    """Get bounding box from an SVG polygon/polyline points. Returns (x, y, w, h)."""
    tag = _strip_ns(el.tag)
    if tag not in ("polygon", "polyline", "path"):
        return None
    points_str = el.get("points") or el.get("d")
    if not points_str:
        return None
    if tag == "path":
        # Simple path: only support "M x y" or "Mx,y" style for first point; full bbox would need path parsing
        m = re.search(r"[Mm]\s*([-\d.]+)\s*[, ]\s*([-\d.]+)", points_str)
        if m:
            x, y = float(m.group(1)), float(m.group(2))
            return (x, y, 1.0, 1.0)
        return None
    # polygon/polyline: points="x1,y1 x2,y2 ..."
    parts = re.split(r"[\s,]+", points_str.strip())
    if len(parts) < 4:
        return None
    nums = [float(p) for p in parts if p]
    if len(nums) < 4:
        return None
    xs = nums[0::2]
    ys = nums[1::2]
    return (min(xs), min(ys), max(xs) - min(xs), max(ys) - min(ys))


def _get_group_bbox(g: ET.Element) -> tuple[float, float, float, float] | None:
    """Get bounding box of a group by checking first rect or polygon child."""
    for child in g:
        bbox = _get_rect_bbox(child) or _get_polygon_bbox(child)
        if bbox:
            return bbox
        # Recurse one level for nested groups (e.g. node > g > rect)
        if _strip_ns(child.tag) == "g":
            bbox = _get_group_bbox(child)
            if bbox:
                return bbox
    return None


def _get_text_content(g: ET.Element) -> str:
    """Extract first non-empty text from <text> elements in the group."""
    for elem in g.iter():
        if _strip_ns(elem.tag) == "text" and elem.text:
            t = (elem.text or "").strip()
            if t:
                return t
            # TSpan content
            for c in elem:
                if c.text:
                    return c.text.strip()
    return ""


def _parse_svg_root(svg_input: str | bytes | Path) -> ET.Element:
    """Parse SVG from file path, bytes, or string; return root element."""
    if isinstance(svg_input, Path):
        tree = ET.parse(svg_input)
        return tree.getroot()
    if isinstance(svg_input, bytes):
        return ET.fromstring(svg_input)
    return ET.fromstring(svg_input)


def svg_to_component_positions(
    svg_input: str | bytes | Path,
    png_width: int = DEFAULT_WIDTH,
    png_height: int = DEFAULT_HEIGHT,
) -> list[ComponentPosition]:
    """
    Parse Mermaid-generated SVG (from file path, bytes, or string) and return component
    positions in reference pixel coordinates (default 1920×1080).

    Finds node and cluster (subgraph) groups; maps their centers to the given dimensions.
    """
    root = _parse_svg_root(svg_input)

    view_box = root.get("viewBox")
    if view_box:
        parts = view_box.strip().split()
        if len(parts) == 4:
            vb_x, vb_y, vb_w, vb_h = float(parts[0]), float(parts[1]), float(parts[2]), float(parts[3])
        else:
            vb_x, vb_y, vb_w, vb_h = 0.0, 0.0, float(png_width), float(png_height)
    else:
        vb_w = float(root.get("width", png_width))
        vb_h = float(root.get("height", png_height))
        vb_x, vb_y = 0.0, 0.0

    def svg_to_png(sx: float, sy: float) -> tuple[int, int]:
        px = int((sx - vb_x) / vb_w * png_width) if vb_w else 0
        py = int((sy - vb_y) / vb_h * png_height) if vb_h else 0
        return (max(0, min(px, png_width - 1)), max(0, min(py, png_height - 1)))

    result: list[ComponentPosition] = []

    def walk(el: ET.Element, cum_tx: float, cum_ty: float) -> None:
        tx, ty = _parse_transform(el.get("transform"))
        cum_tx += tx
        cum_ty += ty
        if _strip_ns(el.tag) == "g":
            classes = (el.get("class") or "").split()
            is_node = "node" in classes
            is_cluster = "cluster" in classes or "clusterRow" in classes
            if (is_node or is_cluster):
                bbox = _get_group_bbox(el)
                if bbox:
                    x, y, w, h = bbox
                    cx = x + w / 2
                    cy = y + h / 2
                    # Transform local center to root SVG coords, then to output coords
                    sx = cx + cum_tx
                    sy = cy + cum_ty
                    px, py = svg_to_png(sx, sy)
                    label = _get_text_content(el).strip() or ""
                    gid = (el.get("id") or "").strip()
                    if gid and "-" in gid:
                        parts_id = gid.split("-")
                        short_id = parts_id[-2] if (len(parts_id) >= 2 and parts_id[-1].isdigit()) else parts_id[-1]
                    elif gid:
                        short_id = gid
                    else:
                        short_id = label or f"node_{len(result)}"
                    if not label:
                        label = short_id
                    name = label or short_id
                    result.append(ComponentPosition(id=short_id, label=label, name=name, x=px, y=py))
        for child in el:
            walk(child, cum_tx, cum_ty)

    walk(root, 0.0, 0.0)
    return result


def mermaid_to_svg(
    mermaid_code: str,
    *,
    mmdc_path: str | None = None,
    background: str = "white",
) -> tuple[bytes, list[ComponentPosition]]:
    """
    Render Mermaid diagram to SVG via mmdc and extract component positions.

    Args:
        mermaid_code: Raw Mermaid diagram source.
        mmdc_path: Path to mmdc binary. If None, uses "mmdc" from PATH.
        background: Background color (e.g. "white", "transparent").

    Returns:
        Tuple of (SVG file content as bytes, list of ComponentPosition in reference 1920×1080 coords).
    """
    cmd = _get_mmdc_cmd(mmdc_path)

    with tempfile.TemporaryDirectory() as tmpdir:
        tmp = Path(tmpdir)
        input_mmd = tmp / "diagram.mmd"
        output_svg = tmp / "diagram.svg"
        config_json = tmp / "mermaid_config.json"
        config_json.write_text(json.dumps(_MMDC_16_9_CONFIG), encoding="utf-8")
        sanitized = _sanitize_mermaid_node_labels(mermaid_code)
        sanitized = _sanitize_mermaid_click_lines(sanitized)
        normalized = _mermaid_code_for_16_9(sanitized)
        input_mmd.write_text(normalized, encoding="utf-8")

        def _run_mmdc(args: list[str]) -> None:
            result = subprocess.run(
                args, capture_output=True, timeout=90, text=True
            )
            if result.returncode != 0:
                raise subprocess.CalledProcessError(
                    result.returncode, args, result.stdout, result.stderr
                ) from None

        args_svg = cmd + [
            "-i", str(input_mmd),
            "-o", str(output_svg),
            "-c", str(config_json),
            "-b", background,
            "-w", str(DEFAULT_WIDTH),
            "-H", str(DEFAULT_HEIGHT),
        ]

        def _err_text(e: subprocess.CalledProcessError) -> str:
            out = e.stderr or e.stdout
            if out is None:
                return ""
            if isinstance(out, bytes):
                out = out.decode("utf-8", errors="replace")
            return str(out).strip()

        try:
            _run_mmdc(args_svg)
        except subprocess.CalledProcessError as e:
            raise RuntimeError(
                f"mermaid-cli failed (exit {e.returncode}). {_err_text(e) or 'No output captured.'}"
            ) from e

        positions = svg_to_component_positions(
            output_svg, DEFAULT_WIDTH, DEFAULT_HEIGHT
        )
        return (output_svg.read_bytes(), positions)


def mermaid_to_png(
    mermaid_code: str,
    *,
    mmdc_path: str | None = None,
    background: str = "white",
) -> bytes:
    """
    Render Mermaid diagram to PNG via mmdc. Use this when SVG text (foreignObject)
    is lost during SVG→PNG conversion; mmdc renders directly to PNG with text intact.
    """
    cmd = _get_mmdc_cmd(mmdc_path)

    with tempfile.TemporaryDirectory() as tmpdir:
        tmp = Path(tmpdir)
        input_mmd = tmp / "diagram.mmd"
        output_png = tmp / "diagram.png"
        config_json = tmp / "mermaid_config.json"
        config_json.write_text(json.dumps(_MMDC_16_9_CONFIG), encoding="utf-8")
        sanitized = _sanitize_mermaid_node_labels(mermaid_code)
        sanitized = _sanitize_mermaid_click_lines(sanitized)
        normalized = _mermaid_code_for_16_9(sanitized)
        input_mmd.write_text(normalized, encoding="utf-8")

        args_png = cmd + [
            "-i", str(input_mmd),
            "-o", str(output_png),
            "-c", str(config_json),
            "-b", background,
            "-w", str(DEFAULT_WIDTH),
            "-H", str(DEFAULT_HEIGHT),
        ]

        result = subprocess.run(args_png, capture_output=True, timeout=90, text=True)
        if result.returncode != 0:
            err = (result.stderr or result.stdout or "").strip()
            raise RuntimeError(f"mermaid-cli PNG failed (exit {result.returncode}). {err}")

        return output_png.read_bytes()
