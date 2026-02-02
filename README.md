# Chandra PDF to Markdown Client

A Python client for converting PDF documents to structured Markdown using OCR with layout detection. This client leverages the [Chandra vision-language model](https://github.com/datalab-to/chandra) to intelligently parse document layouts, extract content, and preserve formatting including tables, equations, figures, and more.

## About Chandra

This client is designed to work with **Chandra**, a specialized vision-language model optimized for document understanding and OCR tasks. Chandra excels at:

- Layout analysis and block segmentation
- Multi-modal content extraction (text, tables, equations, figures)
- High-quality OCR with formatting preservation
- Structured HTML output with semantic labeling

**Learn more**: [Chandra Model Repository](https://github.com/datalab-to/chandra)

## Features

- **Intelligent Layout Detection**: Recognizes 13+ different layout block types including headers, footers, tables, equations, code blocks, and figures
- **Math Support**: Preserves mathematical equations with KaTeX-compatible LaTeX syntax
- **Table Preservation**: Maintains table structure with proper colspan and rowspan handling
- **Image Extraction**: Automatically extracts and saves figures and images with bounding box detection
- **Multi-format Output**: Generates both Markdown and HTML outputs
- **Configurable Processing**: Support for page range selection and custom DPI settings
- **High-Quality Rendering**: Automatic upscaling for optimal OCR quality

## Requirements

- Python 3.8+
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

The client expects the server to be running at `http://localhost:8001/v1` by default. One can map a remote port using ssh tunneling. 

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


## MCP Server

This project also includes an **MCP (Model Context Protocol) server** that exposes Chandra's PDF conversion capabilities through a standardized interface. The MCP server can be used with Claude Desktop or any other MCP-compatible client.

### What is MCP?

MCP is a protocol that allows AI assistants like Claude to interact with external tools and services. The Chandra MCP server exposes four tools:

1. **`convert_pdf`** - Convert entire PDFs to Markdown/HTML
2. **`convert_page_to_markdown`** - Convert a single page (returns content inline)
3. **`extract_pdf_metadata`** - Get PDF metadata without OCR
4. **`configure_server`** - Configure Chandra server connection

### Installation

```bash
# Install dependencies including MCP SDK
uv sync
```

### Configuration

#### Option 1: Install from GitHub with uvx (Recommended)

Create a `.mcp.json` file in your project directory:

```json
{
  "mcpServers": {
    "chandra": {
      "command": "uvx",
      "args": [
        "--from",
        "git+https://github.com/YHRen/chandra_pdf2md_client",
        "chandra-mcp"
      ],
      "env": {
        "CHANDRA_SERVER_URL": "http://localhost:8001/v1",
        "CHANDRA_API_KEY": "chandra"
      }
    }
  }
}
```

**Or** add to your user config at `~/.claude.json`:

```json
{
  "mcpServers": {
    "chandra": {
      "command": "uvx",
      "args": [
        "--from",
        "git+https://github.com/YHRen/chandra_pdf2md_client",
        "chandra-mcp"
      ],
      "env": {
        "CHANDRA_SERVER_URL": "http://localhost:8001/v1",
        "CHANDRA_API_KEY": "chandra"
      }
    }
  }
}
```

This will automatically download and run the MCP server from GitHub without cloning the repository.

#### Option 2: Local Development

If you have the repository cloned locally, create a `.mcp.json` file:

```json
{
  "mcpServers": {
    "chandra": {
      "command": "uvx",
      "args": [
        "--from",
        "/path/to/chandra_pdf2md_client",
        "chandra-mcp"
      ],
      "env": {
        "CHANDRA_SERVER_URL": "http://localhost:8001/v1",
        "CHANDRA_API_KEY": "chandra"
      }
    }
  }
}
```

Replace `/path/to/chandra_pdf2md_client` with the actual path to this repository.

#### Option 3: Claude Desktop App

Add this to your Claude Desktop configuration file:

**macOS**: `~/Library/Application Support/Claude/claude_desktop_config.json`
**Windows**: `%APPDATA%\Claude\claude_desktop_config.json`

```json
{
  "mcpServers": {
    "chandra": {
      "command": "uvx",
      "args": [
        "--from",
        "git+https://github.com/YHRen/chandra_pdf2md_client",
        "chandra-mcp"
      ],
      "env": {
        "CHANDRA_SERVER_URL": "http://localhost:8001/v1",
        "CHANDRA_API_KEY": "chandra"
      }
    }
  }
}
```

### Environment Variables

Configure the MCP server using environment variables:

```bash
# Server configuration
export CHANDRA_SERVER_URL="http://localhost:8001/v1"
export CHANDRA_API_KEY="chandra"
export CHANDRA_MAX_TOKENS="12384"
export CHANDRA_TEMPERATURE="0.0"
export CHANDRA_TOP_P="0.1"

# Output configuration
export CHANDRA_OUTPUT_DIR="./output"
export CHANDRA_IMAGE_FORMAT="webp"

# Image processing
export CHANDRA_IMAGE_DPI="192"
export CHANDRA_MIN_PDF_IMAGE_DIM="1024"
export CHANDRA_MIN_IMAGE_DIM="1536"
```

### Using the MCP Server

Once configured in Claude Desktop, you can use natural language to convert PDFs:

```
"Convert document.pdf to markdown and save it to ./output"
```

Claude will automatically use the appropriate MCP tool to:
1. Connect to your Chandra server
2. Process the PDF pages
3. Generate Markdown/HTML output
4. Extract images

### Testing the MCP Server

#### Test from GitHub

```bash
# Run directly from GitHub
uvx --from git+https://github.com/YHRen/chandra_pdf2md_client chandra-mcp
```

#### Test locally

```bash
# Install dependencies
uv sync

# Run the server (it will listen on stdio)
uvx --from . chandra-mcp
```

The server communicates via stdin/stdout using the MCP protocol. Press Ctrl+C to stop.

### MCP Tools Reference

#### convert_pdf

Convert a PDF to Markdown and/or HTML.

**Parameters:**
- `file_path` (required): Path to PDF or image file
- `output_dir` (default: "./output"): Output directory
- `page_range` (optional): e.g., "1,3,5-10"
- `include_headers_footers` (default: false): Include headers/footers
- `include_images` (default: true): Include images
- `output_format` (default: "both"): "markdown", "html", or "both"
- `image_dpi` (default: 192): DPI for rendering
- `server_url` (optional): Override server URL

**Returns:** JSON with paths to output files, page count, and image count

#### convert_page_to_markdown

Convert a single page, returning content inline.

**Parameters:**
- `file_path` (required): Path to PDF or image file
- `page_number` (default: 1): Page to convert (1-based)
- `include_headers_footers` (default: false): Include headers/footers
- `include_images` (default: true): Include images
- `return_format` (default: "markdown"): "markdown", "html", or "both"
- `server_url` (optional): Override server URL

**Returns:** JSON with markdown/html content and base64-encoded images

#### extract_pdf_metadata

Get PDF metadata without OCR.

**Parameters:**
- `file_path` (required): Path to PDF or image file

**Returns:** JSON with page count, file type, size, and estimated processing time

#### configure_server

Configure Chandra server connection.

**Parameters:**
- `server_url` (required): Chandra server URL
- `api_key` (default: "chandra"): API key
- `max_tokens` (default: 12384): Max tokens
- `temperature` (default: 0.0): Temperature
- `top_p` (default: 0.1): Top-p
- `timeout` (default: 300): Timeout in seconds

**Returns:** JSON with connection status

### Troubleshooting MCP Server

**Server not found in Claude Desktop:**
- Check that the path in `claude_desktop_config.json` is correct
- Verify `uv` is in your PATH
- Restart Claude Desktop after configuration changes

**Connection errors:**
- Ensure Chandra vLLM server is running at the configured URL
- Test with: `curl http://localhost:8001/v1/models`
- Check environment variables are set correctly

**Permission errors:**
- Ensure output directory is writable
- Check file paths are accessible to the MCP server process

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
