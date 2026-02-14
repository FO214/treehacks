# repo-to-png (SVG output)

Generate a **system architecture diagram as SVG** from a **local directory**. Uses a 3-step OpenAI pipeline: directory → file tree + README → Mermaid → SVG.

No GitHub, no frontend—just **directory in, SVG out**.

## Setup (from a fresh clone)

From the **repo root**:

1. **Python env**
   ```bash
   cd /path/to/treehacks
   python -m venv .venv
   source .venv/bin/activate   # Windows: .venv\Scripts\activate
   pip install -r server/requirements.txt
   ```

2. **Node.js**  
   Install Node.js (includes `npx`). The script uses `npx @mermaid-js/mermaid-cli` on demand.

3. **OpenAI API key**
   ```bash
   export OPENAI_API_KEY=sk-...
   ```

4. **Run the diagram**
   ```bash
   python -m server.diagram
   ```
   Writes `diagram.svg` in the current directory. The repo must contain a README.

## Requirements

- **Python 3.12+**
- **OpenAI API key**
- **Node.js** (for Mermaid → SVG via `npx`)

## Usage

```python
from server.diagram import repo_to_svg

# Returns (svg_bytes, component_positions); optionally writes to file
svg_bytes, positions = repo_to_svg("/path/to/project", output_path="diagram.svg")
```

Lower-level:

```python
from server.repo_to_png import run_pipeline, mermaid_to_svg

result = run_pipeline("/path/to/project")
svg_bytes, positions = mermaid_to_svg(result.mermaid)
```

## Environment

| Variable         | Description                 |
|------------------|-----------------------------|
| `OPENAI_API_KEY` | Required for diagram generation |

## What this does

- **Local directory**: builds a file tree and reads README from the project root.
- **OpenAI**: 3-step pipeline (explanation → component mapping → Mermaid).
- **Mermaid → SVG**: one `mmdc` run; output dimensions 1920×1080 (reference for component positions).
