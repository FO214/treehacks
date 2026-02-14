"""
Read file tree and README from a local directory (same exclusions as GitDiagram).
"""
from pathlib import Path

EXCLUDED_PATTERNS = [
    "node_modules",
    "vendor",
    "venv",
    ".min.",
    ".pyc", ".pyo", ".pyd",
    ".so", ".dll", ".class",
    ".jpg", ".jpeg", ".png", ".gif", ".ico", ".svg",
    ".ttf", ".woff", ".webp",
    "__pycache__",
    ".cache",
    ".tmp",
    "yarn.lock",
    "poetry.lock",
    ".vscode",
    ".idea",
    ".git",
]


def _should_include(path: str) -> bool:
    return not any(p in path.lower() for p in EXCLUDED_PATTERNS)


def get_file_tree(directory: str | Path) -> str:
    """
    Return a newline-separated list of relative file and directory paths under directory,
    excluding the same patterns as GitDiagram.
    """
    root = Path(directory).resolve()
    if not root.is_dir():
        raise ValueError(f"Not a directory: {root}")

    paths: set[str] = set()
    for f in root.rglob("*"):
        rel = f.relative_to(root)
        s = str(rel).replace("\\", "/")
        if _should_include(s):
            paths.add(s)
        # also add parent dirs so structure is visible
        for parent in rel.parents:
            if parent != Path("."):
                p = str(parent).replace("\\", "/")
                if _should_include(p):
                    paths.add(p)
    return "\n".join(sorted(paths))


def get_readme(directory: str | Path) -> str:
    """
    Find README in directory root (README.md, README, readme.md, etc.) and return its content.
    """
    root = Path(directory).resolve()
    if not root.is_dir():
        raise ValueError(f"Not a directory: {root}")

    candidates = [
        "README.md",
        "README",
        "readme.md",
        "Readme.md",
        "README.txt",
    ]
    for name in candidates:
        p = root / name
        if p.is_file():
            return p.read_text(encoding="utf-8", errors="replace")
    raise ValueError(f"No README found in {root}. Tried: {candidates}")
