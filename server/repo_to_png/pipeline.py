"""
Core pipeline: read directory from disk → 3-step OpenAI → Mermaid diagram string.
"""
import time
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

    api_time_total = 0.0

    # Step 1: explanation
    t0 = time.perf_counter()
    explanation = openai.completion(
        model=model,
        system_prompt=SYSTEM_FIRST_PROMPT,
        data={"file_tree": file_tree, "readme": readme},
        api_key=openai_api_key,
        reasoning_effort="medium",
    )
    api_time_total += time.perf_counter() - t0

    # Step 2: component mapping
    t0 = time.perf_counter()
    full_second = openai.completion(
        model=model,
        system_prompt=SYSTEM_SECOND_PROMPT,
        data={"explanation": explanation, "file_tree": file_tree},
        api_key=openai_api_key,
        reasoning_effort="low",
    )
    api_time_total += time.perf_counter() - t0
    start_tag, end_tag = "<component_mapping>", "</component_mapping>"
    start_idx = full_second.find(start_tag)
    end_idx = full_second.find(end_tag)
    component_mapping_text = (
        full_second[start_idx : end_idx + len(end_tag)]
        if start_idx != -1 and end_idx != -1
        else full_second
    )

    # Step 3: Mermaid diagram
    t0 = time.perf_counter()
    mermaid_code = openai.completion(
        model=model,
        system_prompt=SYSTEM_THIRD_PROMPT,
        data={"explanation": explanation, "component_mapping": component_mapping_text},
        api_key=openai_api_key,
        reasoning_effort="low",
    )
    api_time_total += time.perf_counter() - t0
    mermaid_code = mermaid_code.replace("```mermaid", "").replace("```", "").strip()

    print(f"OpenAI API calls total time: {api_time_total:.2f}s")

    return PipelineResult(
        mermaid=mermaid_code,
        explanation=explanation,
        component_mapping=component_mapping_text,
    )
