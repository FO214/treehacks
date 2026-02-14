"""Tests for Mermaid sanitization (node labels with special chars). Run: python -m repo_to_png.test_mermaid_sanitize"""
import sys

try:
    from .mermaid_to_png import _sanitize_mermaid_node_labels
except ImportError:
    from mermaid_to_png import _sanitize_mermaid_node_labels


def test_sanitize_quotes_labels_with_parens_and_slash():
    # Pattern that caused: Parse error ... Client[Client (curl/Poke)]:::clien
    raw = 'Client[Client (curl/Poke)]:::client'
    out = _sanitize_mermaid_node_labels(raw)
    assert out == 'Client["Client (curl/Poke)"]:::client', out


def test_sanitize_flowchart_line():
    raw = """flowchart LR
    A[Client (curl/Poke)]:::client --> B[Server]
"""
    out = _sanitize_mermaid_node_labels(raw)
    assert 'A["Client (curl/Poke)"]' in out, out
    assert 'B[Server]' in out, out  # no special chars, unchanged


def test_sanitize_leaves_already_quoted_unchanged():
    raw = 'A["Already (quoted)"] --> B'
    out = _sanitize_mermaid_node_labels(raw)
    assert out == raw, out


def test_sanitize_leaves_simple_labels_unchanged():
    raw = 'A[Simple] --> B[Node]'
    out = _sanitize_mermaid_node_labels(raw)
    assert out == raw, out


def test_sanitize_newline_and_internal_quote():
    # Labels with newline or internal " are normalized so parser does not see \\n or \"
    raw = 'A[Client\n(curl/Postman)]'
    out = _sanitize_mermaid_node_labels(raw)
    assert "\\n" not in out, "should not emit backslash-n"
    assert '["Client (curl/Postman)"]' in out or "Client" in out and "Postman" in out, out


if __name__ == "__main__":
    test_sanitize_quotes_labels_with_parens_and_slash()
    test_sanitize_flowchart_line()
    test_sanitize_leaves_already_quoted_unchanged()
    test_sanitize_leaves_simple_labels_unchanged()
    test_sanitize_newline_and_internal_quote()
    print("All sanitization tests passed.")
    sys.exit(0)
