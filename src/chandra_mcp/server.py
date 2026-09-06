"""MCP Server implementation for Chandra PDF to Markdown conversion."""

import json
import base64
from pathlib import Path
from typing import Any
import pypdfium2 as pdfium

from mcp.server import Server
from mcp.types import (
    Tool,
    TextContent,
    Prompt,
    PromptArgument,
    PromptMessage,
    GetPromptResult,
)
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
    DetectMissingFiguresParams,
    FigureSpec,
    RecoverFiguresParams,
    RecoveredFigure,
    RecoverFiguresResponse,
    InjectFiguresParams,
    InjectFiguresResponse,
    RenderPageParams,
    RenderPageResponse,
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
from .figures import (
    detect_figure_captions,
    locate_caption_in_pdf,
    estimate_figure_box,
    crop_figure,
    render_page,
    inject_into_markdown,
    inject_into_html,
)
from .prompts import HYBRID_PARSE_PROMPT

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
        ),
        Tool(
            name="detect_missing_figures",
            description="Scan a Markdown file produced by convert_pdf for figure captions ('Figure 3.', 'Fig. 2:') "
                       "and report which captions have no image adjacent to them. Deterministic heuristic: the "
                       "result is a candidate list for you to review, not a verdict. Also reports figure numbers "
                       "referenced in prose whose caption was not detected.",
            inputSchema=DetectMissingFiguresParams.model_json_schema()
        ),
        Tool(
            name="recover_figures",
            description="Recover figures Chandra missed (typically vector graphics or boxed text parsed as text). "
                       "For each figure: locate its caption in the PDF text layer, estimate the figure box from the "
                       "graphics objects above the caption (falls back to a fixed-height crop), render and save the "
                       "crop. Omit `figures` to recover everything detect_missing_figures flags as missing. Inspect "
                       "the returned images; re-run with `page` + `crop_box` (PDF points, origin bottom-left) to fix "
                       "a bad crop.",
            inputSchema=RecoverFiguresParams.model_json_schema()
        ),
        Tool(
            name="inject_figures",
            description="Insert image references for recovered figures directly above their captions in the "
                       "Markdown (and HTML) files, in place. Skips captions that already have an image.",
            inputSchema=InjectFiguresParams.model_json_schema()
        ),
        Tool(
            name="render_pdf_page",
            description="Render one PDF page (or a region of it, in PDF points) to a PNG so you can look at the "
                       "layout and choose a manual crop_box for recover_figures.",
            inputSchema=RenderPageParams.model_json_schema()
        ),
    ]


@app.list_prompts()
async def list_prompts() -> list[Prompt]:
    """List available prompts."""
    return [
        Prompt(
            name="hybrid_parse",
            description="Convert a PDF with Chandra, then find and recover figures the VLM missed "
                       "using the deterministic figure tools with your judgement in the loop.",
            arguments=[
                PromptArgument(name="pdf_path", description="Path to the PDF to convert", required=True),
                PromptArgument(name="output_dir", description="Directory for the outputs (default ./output)", required=False),
            ],
        )
    ]


@app.get_prompt()
async def get_prompt(name: str, arguments: dict | None) -> GetPromptResult:
    """Return a prompt by name."""
    if name != "hybrid_parse":
        raise ValueError(f"Unknown prompt: {name}")
    args = arguments or {}
    text = HYBRID_PARSE_PROMPT.format(
        pdf_path=args.get("pdf_path", "<pdf_path>"),
        output_dir=args.get("output_dir") or "./output",
    )
    return GetPromptResult(
        description="Hybrid PDF parsing: Chandra + figure recovery",
        messages=[PromptMessage(role="user", content=TextContent(type="text", text=text))],
    )


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


def _json(data) -> list[TextContent]:
    return [TextContent(type="text", text=json.dumps(data, indent=2))]


async def handle_detect_missing_figures(arguments: dict) -> list[TextContent]:
    """Handle detect_missing_figures tool call."""
    try:
        params = DetectMissingFiguresParams(**arguments)
        validate_file_path(params.markdown_path)
        result = detect_figure_captions(params.markdown_path).to_dict()
        result["status"] = "success"
        if result["missing"]:
            result["next_step"] = (
                "Review `captions`: entries with has_image=false are candidates. Confirm they are real "
                "figures (not tables or algorithm boxes labelled as figures), then call recover_figures."
            )
        else:
            result["next_step"] = "Every caption has an adjacent image; nothing to recover."
        return _json(result)
    except Exception as e:
        return _json({"status": "error", "error": e.__class__.__name__, "message": str(e)})


async def handle_recover_figures(arguments: dict) -> list[TextContent]:
    """Handle recover_figures tool call."""
    try:
        params = RecoverFiguresParams(**arguments)
        validate_file_path(params.pdf_path)

        detected = {}
        if params.markdown_path:
            validate_file_path(params.markdown_path)
            detected = {c.figure_id: c for c in detect_figure_captions(params.markdown_path).captions}

        specs = params.figures
        if not specs:
            if not detected:
                raise ValueError("Provide `figures`, or `markdown_path` so missing figures can be detected.")
            specs = [FigureSpec(figure_id=c.figure_id, caption=c.caption)
                     for c in detected.values() if not c.has_image]

        if params.output_dir:
            output_dir = ensure_output_dir(params.output_dir)
        elif params.markdown_path:
            output_dir = Path(params.markdown_path).resolve().parent
        else:
            output_dir = Path(params.pdf_path).resolve().parent

        pdf = pdfium.PdfDocument(params.pdf_path)
        results: list[RecoveredFigure] = []
        for spec in specs:
            try:
                caption = spec.caption or (detected[spec.figure_id].caption if spec.figure_id in detected else "")
                notes = []
                loc = None
                if spec.crop_box:
                    if not spec.page:
                        raise ValueError("`page` is required when `crop_box` is given.")
                    if len(spec.crop_box) != 4:
                        raise ValueError("`crop_box` must be [left, bottom, right, top].")
                    page_index = spec.page - 1
                    page = pdf[page_index]
                    crop = tuple(float(v) for v in spec.crop_box)
                    method, n_graphics = "manual", 0
                else:
                    pages = [spec.page - 1] if spec.page else None
                    loc = locate_caption_in_pdf(pdf, spec.figure_id, caption, pages)
                    if loc is None:
                        results.append(RecoveredFigure(
                            figure_id=spec.figure_id, status="caption_not_found",
                            note="No 'Figure N.' label found in the PDF text layer. Pass `page` and `crop_box` to crop manually.",
                        ))
                        continue
                    page_index = loc.page_index
                    page = pdf[page_index]
                    est = estimate_figure_box(
                        page, loc.caption_bbox,
                        gap_tolerance=spec.gap_tolerance_pt,
                        fallback_height=spec.fallback_height_pt,
                        full_width=spec.full_width,
                    )
                    crop, method, n_graphics = est.crop_box, est.method, est.n_graphics
                    if method == "fallback":
                        notes.append("No graphics objects found above the caption; used a fixed-height crop. "
                                     "Inspect the image and re-run with `crop_box` if it is wrong.")
                    if not loc.line_start:
                        notes.append("Caption label was only found mid-line (possibly a prose reference); verify the page.")

                image_path = output_dir / f"figure_{spec.figure_id}.{params.image_format}"
                width, height = crop_figure(page, crop, image_path, params.dpi)
                results.append(RecoveredFigure(
                    figure_id=spec.figure_id, status="ok", page=page_index + 1,
                    caption_bbox_pt=[round(v, 1) for v in loc.caption_bbox] if loc else None,
                    crop_box_pt=[round(v, 1) for v in crop],
                    method=method, n_graphics=n_graphics,
                    image_path=str(image_path), width_px=width, height_px=height,
                    matched_text=loc.matched_text if loc else None,
                    match_score=loc.match_score if loc else None,
                    note=" ".join(notes) or None,
                ))
            except Exception as e:  # keep going for the other figures
                results.append(RecoveredFigure(
                    figure_id=spec.figure_id, status="error", note=f"{e.__class__.__name__}: {e}",
                ))

        response = RecoverFiguresResponse(status="success", figures=results)
        return _json(response.model_dump())
    except Exception as e:
        return _json(RecoverFiguresResponse(status="error", error=e.__class__.__name__, message=str(e)).model_dump())


async def handle_inject_figures(arguments: dict) -> list[TextContent]:
    """Handle inject_figures tool call."""
    try:
        params = InjectFiguresParams(**arguments)
        validate_file_path(params.markdown_path)
        html_path = params.html_path
        if html_path is None:
            sibling = Path(params.markdown_path).with_suffix(".html")
            if sibling.exists():
                html_path = str(sibling)
        for spec in params.figures:
            validate_file_path(spec.image_path)

        mapping = {f.figure_id: f.image_path for f in params.figures}
        md_status = inject_into_markdown(params.markdown_path, mapping)
        html_status = {}
        if html_path:
            validate_file_path(html_path)
            html_status = inject_into_html(html_path, mapping)

        response = InjectFiguresResponse(status="success", markdown=md_status, html=html_status, html_path=html_path)
        return _json(response.model_dump())
    except Exception as e:
        return _json(InjectFiguresResponse(status="error", error=e.__class__.__name__, message=str(e)).model_dump())


async def handle_render_pdf_page(arguments: dict) -> list[TextContent]:
    """Handle render_pdf_page tool call."""
    try:
        params = RenderPageParams(**arguments)
        validate_file_path(params.pdf_path)
        pdf = pdfium.PdfDocument(params.pdf_path)
        if not 1 <= params.page <= len(pdf):
            raise ValueError(f"page must be between 1 and {len(pdf)}")
        page = pdf[params.page - 1]
        pdf_path = Path(params.pdf_path)
        output_path = Path(params.output_path) if params.output_path else \
            pdf_path.resolve().parent / f"{pdf_path.stem}_page{params.page}.png"
        if params.crop_box:
            if len(params.crop_box) != 4:
                raise ValueError("`crop_box` must be [left, bottom, right, top].")
            width, height = crop_figure(page, tuple(params.crop_box), output_path, params.dpi)
        else:
            image = render_page(page, params.dpi)
            output_path.parent.mkdir(parents=True, exist_ok=True)
            image.save(output_path)
            width, height = image.size
        response = RenderPageResponse(
            status="success", image_path=str(output_path), width_px=width, height_px=height,
            page_size_pt=[round(v, 1) for v in page.get_size()],
        )
        return _json(response.model_dump())
    except Exception as e:
        return _json(RenderPageResponse(status="error", error=e.__class__.__name__, message=str(e)).model_dump())


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
        elif name == "detect_missing_figures":
            return await handle_detect_missing_figures(arguments)
        elif name == "recover_figures":
            return await handle_recover_figures(arguments)
        elif name == "inject_figures":
            return await handle_inject_figures(arguments)
        elif name == "render_pdf_page":
            return await handle_render_pdf_page(arguments)
        else:
            error_msg = format_error(
                ValueError(f"Unknown tool: {name}"),
                details={"tool_name": name}
            )
            return [TextContent(type="text", text=error_msg)]
    except Exception as e:
        error_msg = format_error(e)
        return [TextContent(type="text", text=error_msg)]


async def _run() -> None:
    async with stdio_server() as (read_stream, write_stream):
        await app.run(read_stream, write_stream, app.create_initialization_options())


def _parse_args(argv=None):
    import argparse
    from importlib.metadata import version, PackageNotFoundError

    try:
        ver = version("chandra-mcp-server")
    except PackageNotFoundError:
        ver = "unknown"

    parser = argparse.ArgumentParser(
        prog="chandra-mcp",
        description="MCP server for Chandra PDF-to-Markdown conversion with hybrid figure recovery. "
                    "Precedence for the vLLM endpoint: flags > CHANDRA_* environment variables > defaults.",
    )
    parser.add_argument("--server-url", metavar="URL",
                        help="Full base URL of the Chandra vLLM server, e.g. http://localhost:8001/v1 "
                             "(env: CHANDRA_SERVER_URL)")
    parser.add_argument("--host", metavar="HOST",
                        help="vLLM host; combined with --port into http://HOST:PORT/v1 (default localhost)")
    parser.add_argument("--port", type=int, metavar="PORT",
                        help="vLLM port; combined with --host into http://HOST:PORT/v1")
    parser.add_argument("--api-key", metavar="KEY", help="API key sent to vLLM (env: CHANDRA_API_KEY)")
    parser.add_argument("--timeout", type=int, metavar="SECONDS",
                        help="Per-page OCR request timeout (env: CHANDRA_TIMEOUT)")
    parser.add_argument("--version", action="version", version=f"%(prog)s {ver}")
    args = parser.parse_args(argv)

    if args.server_url and (args.host or args.port):
        parser.error("use either --server-url or --host/--port, not both")
    return args


def apply_cli_args(args) -> None:
    """Override the global config from parsed CLI arguments."""
    server_url = args.server_url
    if args.host or args.port:
        host = args.host or "localhost"
        port = args.port or 8001
        server_url = f"http://{host}:{port}/v1"
    config.update(server_url=server_url, api_key=args.api_key, timeout=args.timeout)


def main(argv=None):
    """Main entry point for the MCP server."""
    import asyncio
    apply_cli_args(_parse_args(argv))
    asyncio.run(_run())


if __name__ == "__main__":
    main()
