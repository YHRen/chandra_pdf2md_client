"""MCP Server implementation for Chandra PDF to Markdown conversion."""

import json
import base64
from pathlib import Path
from typing import Any
import pypdfium2 as pdfium

from mcp.server import Server
from mcp.types import Tool, TextContent, ImageContent, EmbeddedResource
from mcp.server.stdio import stdio_server

from .config import ChandraConfig
from .models import (
    ConvertPdfParams,
    ConvertPdfResponse,
    ConvertPageParams,
    ConvertPageResponse,
    ExtractMetadataParams,
    ExtractMetadataResponse,
    ConfigureServerParams,
    ConfigureServerResponse,
)
from .utils import (
    validate_file_path,
    ensure_output_dir,
    estimate_processing_time,
    format_error,
    get_file_info,
)
from .core import (
    load_file,
    encode_image,
    parse_markdown,
    parse_html,
    parse_chunks,
    extract_images,
    create_openai_client,
    save_outputs,
    OCR_LAYOUT_PROMPT,
)

# Global configuration
config = ChandraConfig()

# Initialize MCP server
app = Server("chandra-mcp-server")


@app.list_tools()
async def list_tools() -> list[Tool]:
    """List available tools."""
    return [
        Tool(
            name="convert_pdf",
            description="Convert a PDF or image file to Markdown and/or HTML using Chandra OCR. "
                       "Processes all pages (or specified page range) and saves output to disk.",
            inputSchema={
                "type": "object",
                "properties": {
                    "file_path": {
                        "type": "string",
                        "description": "Path to PDF or image file to convert"
                    },
                    "output_dir": {
                        "type": "string",
                        "description": "Directory to save output files",
                        "default": "./output"
                    },
                    "page_range": {
                        "type": "string",
                        "description": "Page range to process (e.g., '1,3,5-10'). If not provided, processes all pages."
                    },
                    "include_headers_footers": {
                        "type": "boolean",
                        "description": "Include page headers and footers in the output",
                        "default": False
                    },
                    "include_images": {
                        "type": "boolean",
                        "description": "Include images and figures in the output",
                        "default": True
                    },
                    "output_format": {
                        "type": "string",
                        "enum": ["markdown", "html", "both"],
                        "description": "Output format: 'markdown', 'html', or 'both'",
                        "default": "both"
                    },
                    "image_dpi": {
                        "type": "integer",
                        "description": "DPI for PDF page rendering (higher = better quality, slower)",
                        "default": 192
                    },
                    "server_url": {
                        "type": "string",
                        "description": "Override the default Chandra server URL"
                    }
                },
                "required": ["file_path"]
            }
        ),
        Tool(
            name="convert_page_to_markdown",
            description="Convert a single page from a PDF or image file to Markdown and/or HTML. "
                       "Returns content inline (not saved to disk).",
            inputSchema={
                "type": "object",
                "properties": {
                    "file_path": {
                        "type": "string",
                        "description": "Path to PDF or image file"
                    },
                    "page_number": {
                        "type": "integer",
                        "description": "Page number to process (1-based index)",
                        "default": 1
                    },
                    "include_headers_footers": {
                        "type": "boolean",
                        "description": "Include page headers and footers in the output",
                        "default": False
                    },
                    "include_images": {
                        "type": "boolean",
                        "description": "Include images and figures in the output",
                        "default": True
                    },
                    "return_format": {
                        "type": "string",
                        "enum": ["markdown", "html", "both"],
                        "description": "Format to return: 'markdown', 'html', or 'both'",
                        "default": "markdown"
                    },
                    "server_url": {
                        "type": "string",
                        "description": "Override the default Chandra server URL"
                    }
                },
                "required": ["file_path"]
            }
        ),
        Tool(
            name="extract_pdf_metadata",
            description="Extract metadata from a PDF or image file without performing OCR. "
                       "Returns page count, file type, size, and estimated processing time.",
            inputSchema={
                "type": "object",
                "properties": {
                    "file_path": {
                        "type": "string",
                        "description": "Path to PDF or image file"
                    }
                },
                "required": ["file_path"]
            }
        ),
        Tool(
            name="configure_server",
            description="Configure the Chandra vLLM server connection and verify connectivity. "
                       "Updates server URL, API key, and inference parameters.",
            inputSchema={
                "type": "object",
                "properties": {
                    "server_url": {
                        "type": "string",
                        "description": "Base URL for the Chandra vLLM server (e.g., 'http://localhost:8001/v1')"
                    },
                    "api_key": {
                        "type": "string",
                        "description": "API key for the server (typically 'chandra' for vLLM)",
                        "default": "chandra"
                    },
                    "max_tokens": {
                        "type": "integer",
                        "description": "Maximum tokens for OCR response",
                        "default": 12384
                    },
                    "temperature": {
                        "type": "number",
                        "description": "Sampling temperature (0.0 for deterministic)",
                        "default": 0.0
                    },
                    "top_p": {
                        "type": "number",
                        "description": "Top-p sampling parameter",
                        "default": 0.1
                    },
                    "timeout": {
                        "type": "integer",
                        "description": "Request timeout in seconds",
                        "default": 300
                    }
                },
                "required": ["server_url"]
            }
        )
    ]


async def handle_convert_pdf(arguments: dict) -> list[TextContent]:
    """Handle convert_pdf tool call."""
    try:
        # Parse and validate parameters
        params = ConvertPdfParams(**arguments)
        validate_file_path(params.file_path)
        output_dir = ensure_output_dir(params.output_dir)

        # Get configuration
        server_url = params.server_url or config.server_url
        temp_config = config
        if params.server_url:
            temp_config = ChandraConfig()
            temp_config.server_url = params.server_url
        if params.image_dpi != 192:
            temp_config.image_dpi = params.image_dpi

        # Initialize OpenAI client
        client = create_openai_client(temp_config)

        # Load PDF/image
        images = load_file(
            params.file_path,
            {"page_range": params.page_range},
            temp_config
        )

        # Process each page
        all_markdown = []
        all_html = []
        all_images = {}

        for page_num, img in enumerate(images):
            # Encode image
            encoded_img = encode_image(img)

            # Call Chandra OCR
            response = client.chat.completions.create(
                model="chandra",
                messages=[{
                    "role": "user",
                    "content": [
                        {"type": "text", "text": OCR_LAYOUT_PROMPT},
                        {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{encoded_img}"}}
                    ],
                }],
                max_tokens=temp_config.max_tokens,
                temperature=temp_config.temperature,
                top_p=temp_config.top_p,
            )

            html_output = response.choices[0].message.content

            # Process outputs
            if params.output_format in ["markdown", "both"]:
                markdown = parse_markdown(
                    html_output,
                    params.include_headers_footers,
                    params.include_images
                )
                all_markdown.append(markdown)

            if params.output_format in ["html", "both"]:
                html = parse_html(
                    html_output,
                    params.include_headers_footers,
                    params.include_images
                )
                all_html.append(html)

            # Extract images
            if params.include_images:
                chunks = parse_chunks(html_output, img, temp_config.bbox_scale)
                page_images = extract_images(html_output, chunks, img)
                all_images.update(page_images)

        # Save outputs
        output_paths = save_outputs(
            params.file_path,
            output_dir,
            all_markdown,
            all_html,
            all_images,
            params.output_format,
            config.image_format
        )

        # Return results
        response_data = ConvertPdfResponse(
            status="success",
            markdown_path=output_paths.get("markdown"),
            html_path=output_paths.get("html"),
            images_dir=output_paths.get("images_dir"),
            num_pages=len(images),
            num_images=len(all_images),
        )

        return [TextContent(
            type="text",
            text=json.dumps(response_data.model_dump(), indent=2)
        )]

    except Exception as e:
        error_response = ConvertPdfResponse(
            status="error",
            error=e.__class__.__name__,
            message=str(e)
        )
        return [TextContent(
            type="text",
            text=json.dumps(error_response.model_dump(), indent=2)
        )]


async def handle_convert_page(arguments: dict) -> list[TextContent]:
    """Handle convert_page_to_markdown tool call."""
    try:
        # Parse and validate parameters
        params = ConvertPageParams(**arguments)
        validate_file_path(params.file_path)

        # Get configuration
        temp_config = config
        if params.server_url:
            temp_config = ChandraConfig()
            temp_config.server_url = params.server_url

        # Initialize OpenAI client
        client = create_openai_client(temp_config)

        # Load PDF/image - get specific page
        page_range_str = str(params.page_number)
        images = load_file(
            params.file_path,
            {"page_range": page_range_str},
            temp_config
        )

        if not images:
            raise ValueError(f"Page {params.page_number} not found in document")

        img = images[0]  # Should only be one page

        # Encode image
        encoded_img = encode_image(img)

        # Call Chandra OCR
        response = client.chat.completions.create(
            model="chandra",
            messages=[{
                "role": "user",
                "content": [
                    {"type": "text", "text": OCR_LAYOUT_PROMPT},
                    {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{encoded_img}"}}
                ],
            }],
            max_tokens=temp_config.max_tokens,
            temperature=temp_config.temperature,
            top_p=temp_config.top_p,
        )

        html_output = response.choices[0].message.content

        # Process outputs
        result_data = {}
        if params.return_format in ["markdown", "both"]:
            markdown = parse_markdown(
                html_output,
                params.include_headers_footers,
                params.include_images
            )
            result_data["markdown"] = markdown

        if params.return_format in ["html", "both"]:
            html = parse_html(
                html_output,
                params.include_headers_footers,
                params.include_images
            )
            result_data["html"] = html

        # Extract images and encode as base64
        extracted_images = {}
        if params.include_images:
            chunks = parse_chunks(html_output, img, temp_config.bbox_scale)
            page_images = extract_images(html_output, chunks, img)
            for img_name, pil_image in page_images.items():
                extracted_images[img_name] = encode_image(pil_image)

        # Return results
        response_data = ConvertPageResponse(
            status="success",
            markdown=result_data.get("markdown"),
            html=result_data.get("html"),
            extracted_images=extracted_images
        )

        return [TextContent(
            type="text",
            text=json.dumps(response_data.model_dump(), indent=2)
        )]

    except Exception as e:
        error_response = ConvertPageResponse(
            status="error",
            error=e.__class__.__name__,
            message=str(e)
        )
        return [TextContent(
            type="text",
            text=json.dumps(error_response.model_dump(), indent=2)
        )]


async def handle_extract_metadata(arguments: dict) -> list[TextContent]:
    """Handle extract_pdf_metadata tool call."""
    try:
        # Parse and validate parameters
        params = ExtractMetadataParams(**arguments)
        validate_file_path(params.file_path)

        # Get file info
        file_info = get_file_info(params.file_path)

        # Get page count for PDFs
        num_pages = 1
        if file_info["file_type"] == "pdf":
            doc = pdfium.PdfDocument(params.file_path)
            num_pages = len(doc)
            doc.close()

        # Estimate processing time
        estimated_time = estimate_processing_time(num_pages)

        # Return results
        response_data = ExtractMetadataResponse(
            status="success",
            num_pages=num_pages,
            file_type=file_info["file_type"],
            file_size_bytes=file_info["file_size_bytes"],
            estimated_processing_time=estimated_time
        )

        return [TextContent(
            type="text",
            text=json.dumps(response_data.model_dump(), indent=2)
        )]

    except Exception as e:
        error_response = ExtractMetadataResponse(
            status="error",
            error=e.__class__.__name__,
            message=str(e)
        )
        return [TextContent(
            type="text",
            text=json.dumps(error_response.model_dump(), indent=2)
        )]


async def handle_configure_server(arguments: dict) -> list[TextContent]:
    """Handle configure_server tool call."""
    try:
        # Parse parameters
        params = ConfigureServerParams(**arguments)

        # Update global configuration
        config.update(
            server_url=params.server_url,
            api_key=params.api_key,
            max_tokens=params.max_tokens,
            temperature=params.temperature,
            top_p=params.top_p,
            timeout=params.timeout
        )

        # Verify connection
        connection_ok, message = await config.verify_connection()

        # Return results
        response_data = ConfigureServerResponse(
            status="success" if connection_ok else "error",
            message=message,
            connection_verified=connection_ok,
            server_url=config.server_url,
            error=None if connection_ok else "ConnectionError"
        )

        return [TextContent(
            type="text",
            text=json.dumps(response_data.model_dump(), indent=2)
        )]

    except Exception as e:
        error_response = ConfigureServerResponse(
            status="error",
            message=str(e),
            connection_verified=False,
            error=e.__class__.__name__
        )
        return [TextContent(
            type="text",
            text=json.dumps(error_response.model_dump(), indent=2)
        )]


@app.call_tool()
async def call_tool(name: str, arguments: Any) -> list[TextContent]:
    """Handle tool calls."""
    try:
        if name == "convert_pdf":
            return await handle_convert_pdf(arguments)
        elif name == "convert_page_to_markdown":
            return await handle_convert_page(arguments)
        elif name == "extract_pdf_metadata":
            return await handle_extract_metadata(arguments)
        elif name == "configure_server":
            return await handle_configure_server(arguments)
        else:
            error_msg = format_error(
                ValueError(f"Unknown tool: {name}"),
                details={"tool_name": name}
            )
            return [TextContent(type="text", text=error_msg)]
    except Exception as e:
        error_msg = format_error(e)
        return [TextContent(type="text", text=error_msg)]


def main():
    """Main entry point for the MCP server."""
    import asyncio
    asyncio.run(stdio_server(app))


if __name__ == "__main__":
    main()
