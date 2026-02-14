"""
Pipeline internals: file tree + README → OpenAI → Mermaid → PNG.
Call repo_to_png() from server.diagram instead of using this package as entry point.
"""
from .mermaid_to_png import ComponentPosition, mermaid_to_png
from .pipeline import PipelineResult, run_pipeline

__all__ = [
    "ComponentPosition",
    "PipelineResult",
    "mermaid_to_png",
    "run_pipeline",
]
