# repo-to-png

Generate a **system architecture diagram as PNG** from a **local directory**. Uses the same 3-step OpenAI pipeline as [GitDiagram](https://github.com/ahmedkhaleel2004/gitdiagram): directory → file tree + README → Mermaid → PNG (1920×1080).

No GitHub, no frontend, no database—just **directory in, PNG out**.

## Requirements

- **Python 3.12+**
- **OpenAI API key** (for diagram generation)
- **Node.js** and **mermaid-cli** (for Mermaid → PNG rendering)

## Install

```bash
cd repo-to-png
pip install -e .
```

Install mermaid-cli (required for PNG output):

```bash
npm install -g @mermaid-js/mermaid-cli
```

## Usage

### CLI

```bash
# Output to diagram.png (default)
python -m repo_to_png /path/to/your/project

# Custom output path
python -m repo_to_png ./my-app -o arch.png

# With OpenAI key (if not in OPENAI_API_KEY)
python -m repo_to_png . --openai-key sk-xxx
```

The directory must contain a README (e.g. `README.md`, `README`).

### Python API

```python
from repo_to_png import repo_to_png

# Returns PNG bytes, optionally writes to file
png_bytes = repo_to_png("/path/to/project", output_path="diagram.png")
```

Or use the pipeline and renderer separately:

```python
from repo_to_png import run_pipeline, mermaid_to_png

result = run_pipeline("/path/to/project")
png_bytes = mermaid_to_png(result.mermaid)
with open("diagram.png", "wb") as f:
    f.write(png_bytes)
```

## Environment

| Variable        | Description                 |
|-----------------|-----------------------------|
| `OPENAI_API_KEY` | Required for diagram generation |

## What this does

- **Local directory**: builds a file tree (same exclusions as GitDiagram) and reads README from the project root.
- **OpenAI**: 3-step sync pipeline (explanation → component mapping → Mermaid). Click targets in the diagram use `file://` URLs to your local paths.
- **Mermaid → PNG**: subprocess to `mmdc`; output is always **1920×1080**.
