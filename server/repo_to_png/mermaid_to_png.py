"""
Render Mermaid diagram string to PNG bytes using mermaid-cli (mmdc).
Also extracts each core component block (nodes and subgraphs) with pixel x,y on the output PNG.
Requires: npm install -g @mermaid-js/mermaid-cli
"""
import re
import shutil
import subprocess
import tempfile
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import NamedTuple

# Default PNG dimensions (width × height)
DEFAULT_WIDTH = 1920
DEFAULT_HEIGHT = 1080


class ComponentPosition(NamedTuple):
    """A single core component block from the diagram with its position on the output PNG."""

    id: str
    label: str
    x: int
    y: int


def _strip_ns(tag: str) -> str:
    """Remove XML namespace from tag if present."""
    if tag and "}" in tag:
        return tag.split("}", 1)[1]
    return tag or ""


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


def _svg_to_component_positions(
    svg_path: Path, png_width: int, png_height: int
) -> list[ComponentPosition]:
    """
    Parse mmdc-generated SVG and return list of component positions in PNG pixel coordinates.
    Finds node and cluster (subgraph) groups and maps their bounding box center to PNG coords.
    """
    tree = ET.parse(svg_path)
    root = tree.getroot()

    # SVG coordinate system
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
    # Walk all groups; collect those with class "node" or "cluster" (and similar) that have a bbox
    for g in root.iter():
        if _strip_ns(g.tag) != "g":
            continue
        classes = (g.get("class") or "").split()
        if not classes:
            continue
        is_node = "node" in classes
        is_cluster = "cluster" in classes or "clusterRow" in classes
        if not is_node and not is_cluster:
            continue
        bbox = _get_group_bbox(g)
        if not bbox:
            continue
        x, y, w, h = bbox
        cx = x + w / 2
        cy = y + h / 2
        px, py = svg_to_png(cx, cy)
        label = _get_text_content(g).strip() or ""
        gid = (g.get("id") or "").strip()
        # Derive short id from mermaid node id (e.g. flowchart-Frontend-0 -> Frontend)
        if gid:
            if "-" in gid:
                parts_id = gid.split("-")
                if len(parts_id) >= 2:
                    short_id = parts_id[-2] if parts_id[-1].isdigit() else parts_id[-1]
                else:
                    short_id = gid
            else:
                short_id = gid
        else:
            short_id = label or f"node_{len(result)}"
        if not label:
            label = short_id
        result.append(ComponentPosition(id=short_id, label=label, x=px, y=py))

    return result


def mermaid_to_png(
    mermaid_code: str,
    *,
    mmdc_path: str | None = None,
    background: str = "white",
) -> tuple[bytes, list[ComponentPosition]]:
    """
    Render Mermaid diagram to PNG bytes via mmdc and extract component positions.
    Output PNG is always DEFAULT_WIDTH×DEFAULT_HEIGHT (1920×1080).

    Args:
        mermaid_code: Raw Mermaid diagram source.
        mmdc_path: Path to mmdc binary. If None, uses "mmdc" from PATH.
        background: Background color (e.g. "white", "transparent").

    Returns:
        Tuple of (PNG file content as bytes, list of ComponentPosition for each core component block
        with id, label, and pixel x,y on the output PNG).

    Raises:
        FileNotFoundError: If mmdc is not installed.
        subprocess.CalledProcessError: If mmdc fails.
    """
    cmd = mmdc_path or "mmdc"
    if not shutil.which(cmd):
        raise FileNotFoundError(
            "mermaid-cli (mmdc) not found. Install with: npm install -g @mermaid-js/mermaid-cli"
        )

    with tempfile.TemporaryDirectory() as tmpdir:
        tmp = Path(tmpdir)
        input_mmd = tmp / "diagram.mmd"
        output_png = tmp / "diagram.png"
        output_svg = tmp / "diagram.svg"
        input_mmd.write_text(mermaid_code, encoding="utf-8")

        args_png = [
            cmd,
            "-i", str(input_mmd),
            "-o", str(output_png),
            "-b", background,
            "-w", str(DEFAULT_WIDTH),
            "-H", str(DEFAULT_HEIGHT),
        ]
        subprocess.run(args_png, check=True, capture_output=True, timeout=60)

        args_svg = [
            cmd,
            "-i", str(input_mmd),
            "-o", str(output_svg),
            "-b", background,
            "-w", str(DEFAULT_WIDTH),
            "-H", str(DEFAULT_HEIGHT),
        ]
        subprocess.run(args_svg, check=True, capture_output=True, timeout=60)

        positions = _svg_to_component_positions(
            output_svg, DEFAULT_WIDTH, DEFAULT_HEIGHT
        )
        return (output_png.read_bytes(), positions)
