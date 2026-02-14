# repo-to-png

Generate a **system architecture diagram as PNG** from a **local directory**. Uses the same 3-step OpenAI pipeline as [GitDiagram](https://github.com/ahmedkhaleel2004/gitdiagram): directory → file tree + README → Mermaid → PNG (1920×1080).

No GitHub, no frontend, no database—just **directory in, PNG out**.

## Requirements

- **Python 3.12+**
- **OpenAI API key** (for diagram generation)
- **Node.js** and **mermaid-cli** (for Mermaid → PNG rendering)

## Install

From the project root, install server deps (`pip install -r server/requirements.txt`).  
Install mermaid-cli (required for PNG output):

```bash
npm install -g @mermaid-js/mermaid-cli
```

## Usage

Call the pipeline from another component via the single function in the server:

```python
from server.diagram import repo_to_png

# Returns (png_bytes, component_positions); optionally writes to file
png_bytes, positions = repo_to_png("/path/to/project", output_path="diagram.png")
```

The directory must contain a README (e.g. `README.md`, `README`).

Lower-level pieces (if you need them) are in `repo_to_png`:

```python
from server.repo_to_png import run_pipeline, mermaid_to_png

result = run_pipeline("/path/to/project")
png_bytes, positions = mermaid_to_png(result.mermaid)
```

## Environment

| Variable        | Description                 |
|-----------------|-----------------------------|
| `OPENAI_API_KEY` | Required for diagram generation |

## What this does

- **Local directory**: builds a file tree (same exclusions as GitDiagram) and reads README from the project root.
- **OpenAI**: 3-step sync pipeline (explanation → component mapping → Mermaid). Click targets in the diagram use `file://` URLs to your local paths.
- **Mermaid → PNG**: subprocess to `mmdc`; output is always **1920×1080**.
