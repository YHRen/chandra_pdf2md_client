# Changelog

## 0.2.0 - 2026-09-06

### Added
- Hybrid figure recovery: `detect_missing_figures`, `recover_figures`, `render_pdf_page`,
  `inject_figures` MCP tools (`src/chandra_mcp/figures.py`). No LLM calls inside the server; the
  calling agent makes the judgement calls.
- `hybrid_parse` MCP prompt and a portable `SKILL.md` (Agent Skills format) describing the workflow.
- Claude Code plugin manifest and single-plugin marketplace (`.claude-plugin/`).
- `chandra-mcp` CLI flags: `--server-url`, `--host`, `--port`, `--api-key`, `--timeout`, `--version`.
- pytest suite and GitHub Actions CI.

### Fixed
- The MCP server crashed on startup (`stdio_server` was not used as a context manager).
- Pinned `mcp>=1.25,<2`: the 2.x SDK removed the low-level `Server` decorator API, so `uvx --from git+...` installs were failing.
