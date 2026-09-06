# Chandra PDF to Markdown Client for Academic Papers

A Python client and MCP server around the [Chandra](https://github.com/datalab-to/chandra) OCR
vision-language model, tuned for **scientific papers**. It converts a paper PDF into clean Markdown
and HTML with math, tables and figures, and it fixes the one systematic gap we hit when parsing
papers with Chandra: **vector-based figures are skipped**.

## The problem this solves

Chandra crops the figures it recognises as `Image` or `Figure` layout blocks. Many figures in
papers are not raster images but vector drawings (workflow diagrams, plots exported from
matplotlib or TikZ, boxed text panels). Chandra frequently reads those as ordinary text blocks:
the caption ("Figure 1. ...") survives in the Markdown, but the figure itself is gone, and often
the box's inner text is dumped as paragraphs. For a paper with five figures we saw four disappear
this way.

This client adds a **hybrid recovery step** that does not depend on the vision model:

1. `detect_missing_figures` scans the Markdown for captions that have no image next to them.
2. `recover_figures` finds each caption in the PDF text layer, gathers the vector graphics objects
   sitting above it in the same column, and crops that region from a rendered page (with a
   fixed-height fallback and manual crop-box override).
3. `inject_figures` places the recovered image above its caption in the Markdown and HTML.

The tools are deterministic and inspectable. The judgement calls (is this candidate really a
figure, does the crop look right) are left to whoever drives them: a person, or an AI agent
through the bundled MCP server and skill. No LLM is called inside the client and no API keys are
needed.

## What is Chandra

Chandra is a specialised vision-language model for document OCR and layout analysis. It produces
structured HTML with semantic block labels (text, section headers, tables, equations, figures,
captions, footnotes), which this client turns into Markdown and HTML. See the
[Chandra repository](https://github.com/datalab-to/chandra) for the model and the vLLM server
setup.

## Features

- **Paper-oriented conversion**: text, section structure, KaTeX-compatible math (`$...$`, `$$...$$`),
  tables with colspan/rowspan, and figure crops with alt text
- **Vector-figure recovery**: caption-driven detection and PDF-level cropping of figures Chandra
  missed, including two-column layouts and figures glued to equation lines
- **Agent-ready**: an MCP server exposing every step as a tool, a `hybrid_parse` prompt, and a
  portable `SKILL.md` for Claude Code, Codex CLI, Gemini CLI, Hermes and other agents
- **Configurable endpoint**: point at any vLLM instance via flag, environment variable or runtime tool
- **Standalone use**: a plain Python CLI (`chandra_client.py`) for batch conversion without an agent

## Requirements

- Python 3.10+
- [Chandra model](https://github.com/datalab-to/chandra) running via vLLM server
- Required Python packages (see Installation)

## Installation

### 1. Install Client Dependencies

```bash
# Clone the repository
git clone https://github.com/YHRen/chandra_pdf2md_client.git
cd chandra_pdf2md_client

# Install dependencies
uv sync
```

### 2. Set Up Chandra Model Server

Follow the instructions at the [Chandra repository](https://github.com/datalab-to/chandra) to:

1. Download or access the Chandra model weights
2. Install vLLM server
3. Start the vLLM server with Chandra model

The client expects the server to be running at `http://localhost:8001/v1` by default. One can map a remote port using ssh tunneling (for example `ssh -L 8000:localhost:8000 gpu-host`, then pass `--server-url http://localhost:8000/v1`).

## Configuration

### vLLM Server Setup

Start your vLLM server with the Chandra model following chandra's [instructions](https://github.com/datalab-to/chandra?tab=readme-ov-file#vllm-server-optional).

### Client Configuration

Key configuration constants in `chandra_client.py`:

```python
IMAGE_DPI = 192              # DPI for PDF rendering
MIN_PDF_IMAGE_DIM = 1024     # Minimum dimension for PDF pages
MIN_IMAGE_DIM = 1536         # Minimum dimension for images
BBOX_SCALE = 1024            # Bounding box normalization scale
```

The server connection can be configured via the `--server-url` CLI argument:

```bash
# Use a remote or custom server
python chandra_client.py document.pdf --server-url http://remote-server:8001/v1
```

## Usage

### Command Line

```bash
# Basic usage - process entire PDF
python chandra_client.py document.pdf

# Process specific pages (1-based indexing)
python chandra_client.py document.pdf --page-range "1,3,5-10"

# Custom output directory
python chandra_client.py document.pdf --output-dir my_output

# Use remote Chandra server
python chandra_client.py document.pdf --server-url http://remote-server:8001/v1

# Combine options
python chandra_client.py document.pdf --page-range "1-5" --output-dir results

# See all options
python chandra_client.py --help
```

The script will:
1. Load the PDF and convert pages to images
2. Send each page to the Chandra model for OCR
3. Parse the structured HTML output
4. Generate Markdown and HTML files
5. Extract and save images to the output directory

### Python API

```python
from pathlib import Path
from chandra_client import load_file, encode_image, parse_markdown, extract_images

# Load PDF
images = load_file("document.pdf", {})

# Process specific pages (1-based indexing)
config = {"page_range": "1,3,5-10"}
images = load_file("document.pdf", config)

# See main() function for complete example
```

## MCP server and hybrid figure recovery

The package ships a stdio MCP server, `chandra-mcp`, so any MCP-capable agent (Claude Code, Claude
Desktop, Codex CLI, Gemini CLI, Hermes Agent, Cursor, ...) can drive the conversion. Beyond plain
conversion it implements a **hybrid workflow**: Chandra sometimes labels a vector diagram or a boxed
text panel as ordinary text, so the caption survives but no image is cropped. Deterministic tools do
the mechanical work and the agent supplies the judgement. The server itself never calls an LLM and
needs no API keys.

| Tool | Purpose |
|---|---|
| `convert_pdf` | Chandra OCR to Markdown/HTML plus cropped figures, saved to disk |
| `convert_page_to_markdown` | Single page, returned inline |
| `extract_pdf_metadata` | Page count and size without OCR |
| `configure_server` | Point the server at a different vLLM endpoint at runtime |
| `detect_missing_figures` | Find captions in the Markdown with no adjacent image (`Figure 1.`, `Fig. 2:`, `FIG. 3.`) |
| `recover_figures` | Locate each caption in the PDF, estimate the figure box from the graphics objects above it, render the crop |
| `render_pdf_page` | Render a page (or region) to PNG so the agent can inspect the layout and choose a manual crop |
| `inject_figures` | Insert the recovered images above their captions in the Markdown and HTML, idempotently |

The workflow the agent follows is convert → detect → **decide** → recover → **inspect** → inject. It is
described twice, for two kinds of host: the `hybrid_parse` MCP prompt (for hosts that surface MCP
prompts as slash commands) and [`SKILL.md`](SKILL.md) at the repository root (Agent Skills format,
loadable by Claude Code, Codex, Gemini CLI, Hermes, Cursor and others).

### Pointing the server at your vLLM instance

The vLLM server hosting Chandra is usually remote and reached through an SSH tunnel. Tell
`chandra-mcp` where it is with a flag, an environment variable, or the `configure_server` tool.
Precedence: flags > `CHANDRA_*` environment variables > default (`http://localhost:8001/v1`).

```bash
chandra-mcp --server-url http://localhost:8001/v1   # full base URL
chandra-mcp --host localhost --port 8000            # same as --server-url http://localhost:8000/v1
CHANDRA_SERVER_URL=http://localhost:8000/v1 chandra-mcp
chandra-mcp --help                                  # --api-key, --timeout, --version
```

Everywhere below, the launch command is

```bash
uvx --from git+https://github.com/YHRen/chandra_pdf2md_client chandra-mcp --server-url http://localhost:8001/v1
```

`uvx` fetches and caches the package, so nothing needs to be cloned. For a local checkout use
`uv --directory /path/to/chandra_pdf2md_client run chandra-mcp ...` instead.

### Claude Code

**Plugin (server + skill in one step):**

```text
/plugin marketplace add YHRen/chandra_pdf2md_client
/plugin install chandra-hybrid-parse@yhren-plugins
```

The plugin starts the server with `uv`, which must be on your PATH. It reads `CHANDRA_SERVER_URL`
from your shell environment; export it before launching `claude` if your endpoint is not the default.

**MCP server only:**

```bash
claude mcp add chandra -s user -- uvx --from git+https://github.com/YHRen/chandra_pdf2md_client chandra-mcp --server-url http://localhost:8001/v1
```

Then install the skill (see [Installing the skill](#installing-the-skill)) or use the
`hybrid_parse` prompt, which Claude Code exposes as `/mcp__chandra__hybrid_parse`.

### Claude Desktop

`~/Library/Application Support/Claude/claude_desktop_config.json` (macOS) or
`%APPDATA%\Claude\claude_desktop_config.json` (Windows):

```json
{
  "mcpServers": {
    "chandra": {
      "command": "uvx",
      "args": ["--from", "git+https://github.com/YHRen/chandra_pdf2md_client", "chandra-mcp",
               "--server-url", "http://localhost:8001/v1"]
    }
  }
}
```

### Codex CLI

```bash
codex mcp add chandra -- uvx --from git+https://github.com/YHRen/chandra_pdf2md_client chandra-mcp --server-url http://localhost:8001/v1
```

or in `~/.codex/config.toml`:

```toml
[mcp_servers.chandra]
command = "uvx"
args = ["--from", "git+https://github.com/YHRen/chandra_pdf2md_client", "chandra-mcp",
        "--server-url", "http://localhost:8001/v1"]
```

### Gemini CLI

```bash
gemini mcp add -s user chandra uvx -- --from git+https://github.com/YHRen/chandra_pdf2md_client chandra-mcp --server-url http://localhost:8001/v1
```

or in `~/.gemini/settings.json`:

```json
{
  "mcpServers": {
    "chandra": {
      "command": "uvx",
      "args": ["--from", "git+https://github.com/YHRen/chandra_pdf2md_client", "chandra-mcp",
               "--server-url", "http://localhost:8001/v1"],
      "timeout": 600000
    }
  }
}
```

### Hermes Agent

`~/.hermes/config.yaml`, then `/reload-mcp`:

```yaml
mcp_servers:
  chandra:
    command: "uvx"
    args: ["--from", "git+https://github.com/YHRen/chandra_pdf2md_client", "chandra-mcp",
           "--server-url", "http://localhost:8001/v1"]
    timeout: 600
```

### Cursor and other MCP clients

Any client that accepts the standard `mcpServers` JSON (Cursor `.cursor/mcp.json`, Windsurf,
Cline, Continue, ...) can use the Claude Desktop snippet above unchanged.

### Installing the skill

`SKILL.md` follows the open Agent Skills format (YAML frontmatter plus a Markdown playbook), so one
file serves every host. The quickest route is the `skills` CLI, which installs into the directories
each agent reads (`.claude/skills`, `.agents/skills` for Codex/Gemini CLI/Cursor, `.hermes/skills`, ...):

```bash
npx skills add YHRen/chandra_pdf2md_client          # pick agents interactively; add -g for global
npx skills add YHRen/chandra_pdf2md_client -a codex -a gemini-cli -g
```

Manual install is a copy or symlink of `SKILL.md` into a directory named after the skill:

| Host | Location |
|---|---|
| Claude Code | `~/.claude/skills/chandra-hybrid-parse/SKILL.md` |
| Codex CLI, Gemini CLI, Cursor (shared) | `~/.agents/skills/chandra-hybrid-parse/SKILL.md` |
| Hermes Agent | `~/.hermes/skills/chandra-hybrid-parse/SKILL.md` |

Then ask the agent to parse a paper, or invoke the skill directly (`/chandra-hybrid-parse paper.pdf`
in Claude Code).

### Environment variables

| Variable | Default | Meaning |
|---|---|---|
| `CHANDRA_SERVER_URL` | `http://localhost:8001/v1` | vLLM base URL (flag `--server-url` or `--host/--port` wins) |
| `CHANDRA_API_KEY` | `chandra` | API key sent to vLLM |
| `CHANDRA_TIMEOUT` | `300` | Per-page OCR request timeout in seconds |
| `CHANDRA_MAX_TOKENS` / `CHANDRA_TEMPERATURE` / `CHANDRA_TOP_P` | `12384` / `0.0` / `0.1` | OCR sampling parameters |
| `CHANDRA_IMAGE_DPI` / `CHANDRA_MIN_PDF_IMAGE_DIM` / `CHANDRA_MIN_IMAGE_DIM` | `192` / `1024` / `1536` | Page rendering |
| `CHANDRA_OUTPUT_DIR` / `CHANDRA_IMAGE_FORMAT` | `./output` / `webp` | Output defaults |

### Tool reference

**convert_pdf** — `file_path` (required), `output_dir` (default `./output`), `page_range` (e.g. `1,3,5-10`),
`include_headers_footers`, `include_images`, `output_format` (`markdown` | `html` | `both`), `image_dpi`,
`server_url`. Returns the output paths, page count and image count.

**convert_page_to_markdown** — `file_path`, `page_number` (1-based), `return_format`; returns content
inline plus base64 images.

**extract_pdf_metadata** — `file_path`; returns page count, file type, size, time estimate.

**configure_server** — `server_url` (required), `api_key`, `max_tokens`, `temperature`, `top_p`, `timeout`;
verifies connectivity.

**detect_missing_figures** — `markdown_path`. Returns every caption with `has_image`, `line`,
`image_ref`; `missing` (figure ids without an image); `referenced_without_caption` (figure numbers only
mentioned in prose).

**recover_figures** — `pdf_path`, optional `markdown_path` (fills captions; when `figures` is omitted,
recovers every missing one), `output_dir`, `dpi`, `image_format`, and `figures`: a list of
`{figure_id, caption?, page?, crop_box?, full_width?, fallback_height_pt?, gap_tolerance_pt?}`. Boxes are
`[left, bottom, right, top]` in PDF points, origin bottom-left. Returns per figure the page, caption
box, crop box, `method` (`graphics` | `fallback` | `manual`), image path and size.

**render_pdf_page** — `pdf_path`, `page`, `output_path`, `dpi`, optional `crop_box`; returns the PNG path
and `page_size_pt`.

**inject_figures** — `markdown_path`, optional `html_path` (defaults to the sibling `.html`), `figures`:
`[{figure_id, image_path}]`. Returns per-figure status `injected` | `already_has_image` | `caption_not_found`.

### Troubleshooting the MCP server

- **Server not found / connection closed:** make sure `uv`/`uvx` is on the PATH of the host application,
  then run the launch command by hand in a terminal; `chandra-mcp --version` should print and the server
  should wait on stdin.
- **`APIConnectionError` from `convert_pdf`:** the vLLM endpoint is unreachable. Check
  `curl http://localhost:8001/v1/models` (adjust the port); if you use an SSH tunnel, it has probably
  dropped.
- **Wrong crop from `recover_figures`:** call `render_pdf_page` for that page, then re-run
  `recover_figures` with `page` and a manual `crop_box`.

## Output Structure

```
output/
├── document.md              # Markdown output
├── document.html           # HTML output
└── images/                 # Extracted images
    ├── <hash>_1_img.webp
    ├── <hash>_2_img.webp
    └── ...
```

## Layout Block Types

The Chandra model recognizes and processes the following layout blocks:

- **Caption**: Image/table captions
- **Footnote**: Footer notes and references
- **Equation-Block**: Mathematical equations
- **List-Group**: Bulleted and numbered lists
- **Page-Header**: Page headers
- **Page-Footer**: Page footers
- **Image**: Inline images
- **Section-Header**: Section titles (h1-h5)
- **Table**: Tabular data
- **Text**: Body text paragraphs
- **Complex-Block**: Multi-element blocks
- **Code-Block**: Code snippets
- **Form**: Form elements
- **Table-Of-Contents**: TOC sections
- **Figure**: Figures with captions

## Processing Options

### Include/Exclude Content

```python
# Exclude headers and footers
markdown = parse_markdown(html, include_headers_footers=False, include_images=True)

# Exclude images
markdown = parse_markdown(html, include_headers_footers=True, include_images=False)
```

## Architecture

1. **PDF Loading** (`load_file`): Converts PDF pages to high-resolution images
2. **OCR Processing**: Sends images to Chandra model via vLLM with structured layout prompt
3. **HTML Parsing** (`parse_html`): Filters and processes layout blocks
4. **Markdown Conversion** (`parse_markdown`): Converts HTML to clean Markdown
5. **Image Extraction** (`extract_images`): Crops and saves figures using bounding boxes

## API Reference

### Main Functions

#### `load_file(filepath: str, config: dict) -> List[Image.Image]`
Loads a PDF or image file and returns a list of PIL Images.

**Parameters:**
- `filepath`: Path to PDF or image file
- `config`: Dictionary with optional `page_range` key

**Returns:** List of PIL Image objects

#### `parse_markdown(html: str, include_headers_footers: bool, include_images: bool) -> str`
Converts HTML to Markdown with custom math and table handling.

**Parameters:**
- `html`: HTML string from OCR
- `include_headers_footers`: Include page headers/footers
- `include_images`: Include figure references

**Returns:** Markdown string

#### `extract_images(html: str, chunks: list, image: Image.Image) -> dict`
Extracts images from layout blocks using bounding boxes.

**Parameters:**
- `html`: HTML string with layout blocks
- `chunks`: List of parsed chunks with bboxes
- `image`: Original page image

**Returns:** Dictionary mapping image names to PIL Images

## Customization

### Custom Markdown Converter

The `Markdownify` class can be extended to customize markdown conversion:

```python
md_cls = Markdownify(
    heading_style="ATX",
    bullets="-",
    inline_math_delimiters=("$", "$"),
    block_math_delimiters=("$$", "$$"),
)
```

### OCR Layout Prompt

Modify `OCR_LAYOUT_PROMPT` in `chandra_client.py` to adjust the OCR behavior and output format. The prompt guides the Chandra model on how to structure the HTML output.

## Limitations

- Requires a running vLLM server with the Chandra model
- Performance depends on model configuration and server resources
- Large PDFs may require significant processing time
- Complex layouts may occasionally be misinterpreted

## Troubleshooting

### Connection Issues
- Verify vLLM server is running at `http://localhost:8001/v1`
- Check API key is set to "chandra" or update in code
- Test connection: `curl http://localhost:8001/v1/models`

### Poor OCR Quality
- Increase `IMAGE_DPI` for higher resolution rendering
- Adjust `MIN_PDF_IMAGE_DIM` for better page quality
- Ensure source PDF is not a scanned image with low resolution
- Verify Chandra model is loaded correctly in vLLM

### Missing Images
- Check bounding box detection is working correctly
- Verify output/images directory exists and is writable
- Ensure the Chandra model is outputting proper data-bbox attributes
- If a caption is present but its figure is not (typical for vector diagrams and boxed text panels),
  use the hybrid workflow: `detect_missing_figures` → `recover_figures` → `inject_figures` via the
  MCP server, or ask an agent with the `chandra-hybrid-parse` skill to do it

### Model Errors
- Check vLLM server logs for detailed error messages
- Verify Chandra model weights are correctly loaded
- Ensure sufficient GPU memory is available

## Example

```python
if __name__ == "__main__":
    from openai import OpenAI

    # Initialize Chandra client
    client = OpenAI(
        base_url="http://localhost:8001/v1",
        api_key="chandra",
    )

    # Load PDF
    pdf_file_path = "document.pdf"
    images = load_file(pdf_file_path, {})

    # Process pages with Chandra
    for page_num, img in enumerate(images):
        encoded_img = encode_image(img)

        response = client.chat.completions.create(
            model="chandra",
            messages=[{
                "role": "user",
                "content": [
                    {"type": "text", "text": OCR_LAYOUT_PROMPT},
                    {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{encoded_img}"}}
                ],
            }],
            max_tokens=12384,
            temperature=0,
        )

        # Process response...
```

## Related Projects

- [Chandra Model](https://github.com/datalab-to/chandra) - The vision-language model powering this client
- [vLLM](https://github.com/vllm-project/vllm) - Fast inference server for LLMs

## License

This code is Apache 2.0


## Standalone Client

The standalone Python client is available in `chandra_client.py`. To use it:

```bash
# Basic usage
python chandra_client.py document.pdf

# With options
python chandra_client.py document.pdf --page-range "1-5" --output-dir results

# See all options
python chandra_client.py --help
```

## Acknowledgments

Built with:
- [Chandra](https://github.com/datalab-to/chandra) for document OCR and layout analysis
- [pypdfium2](https://github.com/pypdfium2-team/pypdfium2) for PDF rendering
- [OpenAI Python SDK](https://github.com/openai/openai-python) for API client
- [BeautifulSoup](https://www.crummy.com/software/BeautifulSoup/) for HTML parsing
- [markdownify](https://github.com/matthewwithanm/python-markdownify) for Markdown conversion
- [MCP](https://modelcontextprotocol.io) for tool integration
