# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

A Python client for converting PDF documents to structured Markdown using the [Chandra vision-language model](https://github.com/datalab-to/chandra). This is a single-file client that communicates with a Chandra model running on a vLLM server to perform OCR with layout detection, preserving tables, equations, figures, and document structure.

## Development Setup

### Dependencies

Install dependencies using `uv`:

```bash
uv sync
```

The project requires Python 3.13 and uses these key dependencies:
- `openai` - For vLLM server communication
- `pypdfium2` - For PDF rendering
- `pillow` - For image processing
- `beautifulsoup4` - For HTML parsing
- `markdownify` - For Markdown conversion

### Running the Client

The client is currently a script. To process a PDF:

1. Ensure Chandra vLLM server is running at `http://localhost:8001/v1` (or use SSH tunneling to map a remote server)
2. Edit the `pdf_file_path` variable in the `main()` function in `chandra_client.py`
3. Run:
   ```bash
   python chandra_client.py
   ```

Output will be saved to the `output/` directory:
- `<filename>.md` - Markdown output
- `<filename>.html` - HTML output
- `images/` - Extracted figures and images

## Architecture

### Processing Pipeline

The client follows this flow:

1. **PDF Loading** (`load_file()` → `load_pdf_images()`)
   - Renders PDF pages to high-res images using pypdfium2
   - Applies automatic upscaling based on `MIN_PDF_IMAGE_DIM` and `IMAGE_DPI`
   - Flattens form fields and annotations before rendering
   - Supports page range selection via config dict

2. **OCR Processing** (`main()`)
   - Encodes page images as base64 PNG
   - Sends to Chandra model with `OCR_LAYOUT_PROMPT`
   - Receives structured HTML with layout blocks as divs containing `data-label` and `data-bbox` attributes

3. **HTML Parsing** (`parse_html()`)
   - Filters layout blocks based on type (can exclude headers/footers/images)
   - Updates image src attributes to point to extracted images
   - Preserves only top-level divs (each represents one layout block)

4. **Markdown Conversion** (`parse_markdown()`)
   - Custom `Markdownify` subclass handles math expressions and tables
   - Math expressions: inline `$...$` and block `$$...$$`
   - Tables are kept as HTML (not converted to Markdown tables)
   - Escapes special characters appropriately

5. **Image Extraction** (`extract_images()`)
   - Crops image regions from layout blocks labeled "Image" or "Figure"
   - Uses normalized bounding boxes (0-1024 scale) with 5% padding buffer
   - Saves as WebP format with MD5-based filenames

### Configuration Constants

Key constants defined at the top of `chandra_client.py`:

- `IMAGE_DPI = 192` - DPI for PDF page rendering
- `MIN_PDF_IMAGE_DIM = 1024` - Minimum dimension (width or height) for rendered PDF pages; triggers upscaling
- `MIN_IMAGE_DIM = 1536` - Minimum dimension for standalone images
- `BBOX_SCALE = 1024` - Normalization scale for bounding boxes (Chandra outputs 0-1024 coordinates)

### Layout Block Types

The Chandra model recognizes 14 layout block types via the `data-label` attribute:

- Content: `Caption`, `Footnote`, `Text`, `List-Group`, `Code-Block`
- Structure: `Section-Header`, `Page-Header`, `Page-Footer`, `Table-Of-Contents`
- Special: `Equation-Block`, `Table`, `Image`, `Figure`, `Complex-Block`, `Form`

Each type is handled differently during parsing and conversion.

### OCR Prompt

The `OCR_LAYOUT_PROMPT` instructs Chandra to:
- Output HTML with divs containing `data-bbox` (normalized coordinates) and `data-label` attributes
- Use KaTeX-compatible LaTeX for math within `<math>` tags
- Preserve table structure with colspan/rowspan
- Include image descriptions in alt attributes (src is empty, filled in during processing)
- Use only a restricted set of HTML tags and attributes

## Key Implementation Details

### PDF Page Flattening

The `flatten()` function (lines 58-61) flattens annotations and form fields before rendering. This is critical for PDFs with interactive elements, as it converts them to static content for OCR.

### Bounding Box Handling

Bounding boxes from Chandra are normalized to 0-1024 and need to be scaled to actual image dimensions. The `parse_chunks()` function (lines 256-301):
- Scales bboxes to image dimensions using width/height scalers
- Adds 5% padding on all sides to avoid cutoff during cropping
- Handles malformed bbox formats (JSON array or space-separated string)

### Page Range Selection

The `parse_range_str()` function (lines 95-106) parses strings like `"1,3,5-10"` into a deduplicated, sorted list of 0-based page indices for selective processing.

### Image Naming

Images are named using `<html_hash>_<div_idx>_img.webp` where:
- `html_hash` is MD5 of the entire HTML output (ensures uniqueness per page)
- `div_idx` is the 1-based index of the div in the HTML (matches position in document)

### Server Connection

The OpenAI client is configured to connect to the Chandra vLLM server:

```python
client = OpenAI(
    base_url="http://localhost:8001/v1",  # vLLM server URL
    api_key="chandra",  # Required but unused by vLLM
)
```

The model name used in requests must be "chandra".

## MCP Server Architecture

This repository includes an **MCP (Model Context Protocol) server** implementation that exposes Chandra's capabilities through standardized tools.

### Directory Structure

```
src/chandra_mcp/
├── __init__.py       # Package initialization
├── server.py         # MCP server: tool handlers, prompt, stdio entry point
├── core.py           # OCR request + HTML/Markdown/image post-processing
├── figures.py        # Deterministic figure recovery (detect / locate / crop / inject)
├── prompts.py        # MCP prompt templates (hybrid_parse)
├── models.py         # Pydantic models for tool parameters and responses
├── config.py         # Configuration management
└── utils.py          # Helper functions
SKILL.md                               # Agent skill (Agent Skills format) driving the hybrid workflow
.claude-plugin/plugin.json             # Plugin manifest (bundles the MCP server + skill)
.claude-plugin/marketplace.json        # Single-plugin marketplace for `/plugin marketplace add`
tests/test_figures.py                  # pytest suite for figures.py
```

### MCP Tools

The server exposes 4 tools:

1. **convert_pdf** (server.py:handle_convert_pdf)
   - Full PDF conversion with file output
   - Processes all pages or specified range
   - Saves to `output/` directory
   - Returns file paths and statistics

2. **convert_page_to_markdown** (server.py:handle_convert_page)
   - Single page conversion with inline output
   - Returns markdown/html as strings
   - Returns images as base64
   - No disk writes

3. **extract_pdf_metadata** (server.py:handle_extract_metadata)
   - Quick inspection without OCR
   - Uses pypdfium2 for page count
   - Estimates processing time
   - Returns file info

4. **configure_server** (server.py:handle_configure_server)
   - Updates global configuration
   - Verifies server connection
   - Returns connection status

#### Hybrid figure-recovery tools (figures.py)

Chandra sometimes labels a vector diagram or a boxed text panel as a `Text` block, so the caption
survives in the Markdown but no image is cropped. These tools do the deterministic parts of
recovering such figures; the calling agent decides which candidates are real (see the
`hybrid_parse` prompt and `SKILL.md`). Nothing here calls an LLM.

5. **detect_missing_figures** — scans a Markdown file for caption lines (`Figure 3.`, `Fig. 2:`,
   `**Figure 4.**`, or a caption glued to the end of a `$$...$$` line) and attributes each image
   reference to at most one caption (the caption within 4 non-empty lines after it, else the one
   directly before it). Returns all captions with `has_image`, the `missing` ids, and
   `referenced_without_caption` (figure numbers only mentioned in prose).
6. **recover_figures** — for each figure: finds the caption in the PDF text layer (line-start
   matches beat prose references; the caption text breaks ties), estimates the figure box from
   top-level graphics objects (paths, images, shadings, form XObjects) above the caption in the
   same column, clustering upward with a gap tolerance and stopping below header rules; falls back
   to a fixed-height crop when no graphics are found; renders and saves `figure_<id>.webp`.
   Accepts `page` + `crop_box` (PDF points) for manual re-crops.
7. **inject_figures** — inserts `![Figure N](rel/path)` (and `<img>` in the HTML) directly above
   the caption, in place and idempotently.
8. **render_pdf_page** — renders a page or region to PNG so the agent can inspect the layout and
   choose a manual crop box.

**Prompt** `hybrid_parse(pdf_path, output_dir)` (prompts.py) walks a client through the workflow.

Coordinate convention: all boxes are `[left, bottom, right, top]` in PDF points, origin bottom-left
(pypdfium2 convention). `crop_figure` converts to pixel space at render time.

### Configuration System

Multi-layer configuration (server.py and config.py):

1. **Default values**: Hardcoded in `ChandraConfig` class
2. **Environment variables**: Loaded in `config.py:load_from_env()`
   - `CHANDRA_SERVER_URL`, `CHANDRA_API_KEY`, etc.
3. **Runtime updates**: Via `configure_server` tool
4. **Per-call overrides**: Tool parameters (e.g., `server_url` parameter)

Priority: Per-call > Runtime > Environment > Defaults

### Processing Flow

The MCP server follows this flow for PDF conversion:

1. **Tool call received** (server.py:call_tool)
   - Route to appropriate handler
   - Parse parameters with Pydantic models

2. **Validation** (utils.py)
   - Validate file paths exist
   - Ensure output directories are writable
   - Check parameter ranges

3. **Load PDF** (core.py:load_file)
   - Use pypdfium2 to render pages
   - Apply page range filtering
   - Upscale based on MIN_PDF_IMAGE_DIM

4. **OCR Processing** (server.py handler + core.py)
   - Encode each page as base64
   - Send to Chandra via OpenAI client
   - Receive structured HTML with layout blocks

5. **Parse and Convert** (core.py)
   - Filter HTML blocks by type
   - Convert to Markdown with custom Markdownify
   - Extract images using bounding boxes

6. **Save or Return** (core.py:save_outputs)
   - For `convert_pdf`: Save to disk, return paths
   - For `convert_page_to_markdown`: Return inline

7. **Response** (server.py)
   - Format response as JSON
   - Include status, data, or error details

### Error Handling

All errors are caught and formatted consistently (utils.py:format_error):

```json
{
  "error": "FileNotFoundError",
  "message": "File not found: /path/to/doc.pdf",
  "details": {"file_path": "/path/to/doc.pdf"},
  "suggestion": "Verify the file path exists"
}
```

Error types handled:
- **FileNotFoundError**: Missing files
- **ConnectionError**: Server connectivity issues
- **ValueError**: Invalid parameters (page ranges, formats)
- **PermissionError**: File/directory access issues

### Key Implementation Details

#### Global Configuration State

The server maintains a single global `config` instance (server.py:10) that persists across tool calls. This allows:
- The `configure_server` tool to update settings
- Subsequent calls to use updated configuration
- Per-call overrides without mutating global state

#### Pydantic Models

All tool parameters are validated using Pydantic (models.py):
- Type checking and coercion
- Default values
- Field descriptions for documentation
- Automatic JSON schema generation for MCP

#### Async Handlers

All tool handlers are async functions to support:
- Non-blocking I/O operations
- Server connection verification (config.py:verify_connection)
- Future streaming capabilities

#### Stdio Transport

The server uses stdio transport (server.py:main), running `app.run()` inside the
`stdio_server()` context manager:
- Reads MCP requests from stdin
- Writes responses to stdout
- Integrates with Claude Desktop and other MCP clients
- No HTTP server needed

Never print to stdout from tool handlers; it corrupts the protocol stream.

### Differences from Standalone Client

| Feature | Standalone Client | MCP Server |
|---------|------------------|------------|
| Entry point | `chandra_client.py:main()` | `chandra_mcp.server:main()` |
| Input | Hardcoded file path | Tool parameter |
| Output | Always saves to disk | Configurable (disk or inline) |
| Configuration | Constants at top of file | Multi-layer (env, runtime, per-call) |
| Error handling | Print to console | Structured JSON responses |
| Interface | Direct Python API | MCP protocol over stdio |

### Running the MCP Server

**Via Claude Code CLI or Claude Desktop**: Configure in `.mcp.json` or `claude_desktop_config.json`

**Direct invocation from GitHub**:
```bash
uvx --from git+https://github.com/YHRen/chandra_pdf2md_client chandra-mcp
```

**Direct invocation locally**:
```bash
uvx --from . chandra-mcp
```

**Testing a single tool**:
```bash
echo '{"jsonrpc":"2.0","id":1,"method":"tools/call","params":{"name":"extract_pdf_metadata","arguments":{"file_path":"sample.pdf"}}}' | uvx --from . chandra-mcp
```

### Testing

```bash
uv run pytest -q          # unit tests for figures.py (uses 2203.02557v3.pdf for the PDF smoke test)
claude plugin validate .  # manifest + marketplace schema check
```

### Installing as a Claude Code plugin

```text
/plugin marketplace add YHRen/chandra_pdf2md_client
/plugin install chandra-hybrid-parse@yhren-plugins
```

or for local development: `claude --plugin-dir /path/to/chandra_pdf2md_client`. The plugin starts the
MCP server with `uv --directory ${CLAUDE_PLUGIN_ROOT} run chandra-mcp`; set `CHANDRA_SERVER_URL` in
the environment (or call `configure_server`) if the vLLM server is not at `http://localhost:8001/v1`.

### Extending the MCP Server

To add a new tool:

1. **Define Pydantic models** in `models.py`:
   - `NewToolParams` for parameters
   - `NewToolResponse` for responses

2. **Implement handler** in `server.py`:
   ```python
   async def handle_new_tool(arguments: dict) -> list[TextContent]:
       params = NewToolParams(**arguments)
       # ... implementation ...
       response = NewToolResponse(...)
       return [TextContent(type="text", text=json.dumps(response.model_dump()))]
   ```

3. **Add to tool list** in `server.py:list_tools()`:
   ```python
   Tool(name="new_tool", description="...", inputSchema={...})
   ```

4. **Route in dispatcher** in `server.py:call_tool()`:
   ```python
   elif name == "new_tool":
       return await handle_new_tool(arguments)
   ```

### Troubleshooting MCP Server

**Import errors**: Run `uv sync` to install dependencies

**Server not responding**: Check stdin/stdout aren't being used by other code

**Configuration not loading**: Verify environment variables are set before server starts

**Chandra connection fails**: Test with `curl http://localhost:8001/v1/models`

**Type errors**: Ensure tool parameters match Pydantic model definitions
