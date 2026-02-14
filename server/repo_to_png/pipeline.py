"""
Core pipeline: read directory from disk → 3-step OpenAI → Mermaid diagram string.
"""
import re
from pathlib import Path
from typing import NamedTuple

from .local_directory import get_file_tree, get_readme
from .openai_service import OpenAIService
from .prompts import (
    SYSTEM_FIRST_PROMPT,
    SYSTEM_SECOND_PROMPT,
    SYSTEM_THIRD_PROMPT,
)


class PipelineResult(NamedTuple):
    mermaid: str
    explanation: str
    component_mapping: str


def _process_click_events(diagram: str, base_url: str) -> str:
    """Rewrite click paths to full URLs (file:// for local)."""
    def replace_path(match: re.Match) -> str:
        path = match.group(2).strip("\"'")
        full_url = f"{base_url.rstrip('/')}/{path}"
        return f'click {match.group(1)} "{full_url}"'

    click_pattern = r'click ([^\s"]+)\s+"([^"]+)"'
    return re.sub(click_pattern, replace_path, diagram)


def run_pipeline(
    directory: str | Path,
    *,
    openai_api_key: str | None = None,
    model: str = "o4-mini",
    token_limit: int = 195_000,
) -> PipelineResult:
    """
    Read directory from disk (file tree + README), run the 3-step AI pipeline, return Mermaid diagram.
    """
    directory = Path(directory).resolve()
    openai = OpenAIService()

    file_tree = get_file_tree(directory)
    readme = get_readme(directory)

    combined = f"{file_tree}\n{readme}"
    if openai.count_tokens(combined) > token_limit:
        raise ValueError(
            f"Directory too large (>{token_limit} tokens). Use a smaller tree or exclude more paths."
        )

    # Step 1: explanation
    explanation = openai.completion(
        model=model,
        system_prompt=SYSTEM_FIRST_PROMPT,
        data={"file_tree": file_tree, "readme": readme},
        api_key=openai_api_key,
        reasoning_effort="medium",
    )

    # Step 2: component mapping
    full_second = openai.completion(
        model=model,
        system_prompt=SYSTEM_SECOND_PROMPT,
        data={"explanation": explanation, "file_tree": file_tree},
        api_key=openai_api_key,
        reasoning_effort="low",
    )
    start_tag, end_tag = "<component_mapping>", "</component_mapping>"
    start_idx = full_second.find(start_tag)
    end_idx = full_second.find(end_tag)
    component_mapping_text = (
        full_second[start_idx : end_idx + len(end_tag)]
        if start_idx != -1 and end_idx != -1
        else full_second
    )

    # Step 3: Mermaid diagram
    mermaid_code = openai.completion(
        model=model,
        system_prompt=SYSTEM_THIRD_PROMPT,
        data={"explanation": explanation, "component_mapping": component_mapping_text},
        api_key=openai_api_key,
        reasoning_effort="low",
    )
    mermaid_code = mermaid_code.replace("```mermaid", "").replace("```", "").strip()
    file_base_url = directory.as_uri()
    mermaid_code = _process_click_events(mermaid_code, file_base_url)

    return PipelineResult(
        mermaid=mermaid_code,
        explanation=explanation,
        component_mapping=component_mapping_text,
    )
