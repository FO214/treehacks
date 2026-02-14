"""
Pipeline: file tree + README → OpenAI → Mermaid → SVG.
Call repo_to_svg() from server.diagram or use run_pipeline + mermaid_to_svg.
"""
from .mermaid_to_png import (
    ComponentPosition,
    mermaid_to_svg,
    svg_to_component_positions,
)
from .pipeline import PipelineResult, run_pipeline

__all__ = [
    "ComponentPosition",
    "PipelineResult",
    "mermaid_to_svg",
    "run_pipeline",
    "svg_to_component_positions",
]
