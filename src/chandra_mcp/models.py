"""Pydantic models for MCP tool parameters and responses."""

from pydantic import BaseModel, Field
from typing import Optional, Literal, Dict


class ConvertPdfParams(BaseModel):
    """Parameters for convert_pdf tool."""

    file_path: str = Field(
        ...,
        description="Path to PDF or image file to convert"
    )
    output_dir: str = Field(
        default="./output",
        description="Directory to save output files"
    )
    page_range: Optional[str] = Field(
        default=None,
        description="Page range to process (e.g., '1,3,5-10'). If not provided, processes all pages."
    )
    include_headers_footers: bool = Field(
        default=False,
        description="Include page headers and footers in the output"
    )
    include_images: bool = Field(
        default=True,
        description="Include images and figures in the output"
    )
    output_format: Literal["markdown", "html", "both"] = Field(
        default="both",
        description="Output format: 'markdown', 'html', or 'both'"
    )
    image_dpi: int = Field(
        default=192,
        description="DPI for PDF page rendering (higher = better quality, slower processing)"
    )
    server_url: Optional[str] = Field(
        default=None,
        description="Override the default Chandra server URL"
    )


class ConvertPdfResponse(BaseModel):
    """Response from convert_pdf tool."""

    status: Literal["success", "error"]
    markdown_path: Optional[str] = None
    html_path: Optional[str] = None
    images_dir: Optional[str] = None
    num_pages: int = 0
    num_images: int = 0
    error: Optional[str] = None
    message: Optional[str] = None


class ConvertPageParams(BaseModel):
    """Parameters for convert_page_to_markdown tool."""

    file_path: str = Field(
        ...,
        description="Path to PDF or image file"
    )
    page_number: int = Field(
        default=1,
        description="Page number to process (1-based index)"
    )
    include_headers_footers: bool = Field(
        default=False,
        description="Include page headers and footers in the output"
    )
    include_images: bool = Field(
        default=True,
        description="Include images and figures in the output"
    )
    return_format: Literal["markdown", "html", "both"] = Field(
        default="markdown",
        description="Format to return: 'markdown', 'html', or 'both'"
    )
    server_url: Optional[str] = Field(
        default=None,
        description="Override the default Chandra server URL"
    )


class ConvertPageResponse(BaseModel):
    """Response from convert_page_to_markdown tool."""

    status: Literal["success", "error"]
    markdown: Optional[str] = None
    html: Optional[str] = None
    extracted_images: Dict[str, str] = Field(
        default_factory=dict,
        description="Mapping of image names to base64-encoded image data"
    )
    error: Optional[str] = None
    message: Optional[str] = None


class ExtractMetadataParams(BaseModel):
    """Parameters for extract_pdf_metadata tool."""

    file_path: str = Field(
        ...,
        description="Path to PDF or image file"
    )


class ExtractMetadataResponse(BaseModel):
    """Response from extract_pdf_metadata tool."""

    status: Literal["success", "error"]
    num_pages: int = 0
    file_type: Optional[str] = None
    file_size_bytes: int = 0
    estimated_processing_time: Optional[str] = None
    error: Optional[str] = None
    message: Optional[str] = None


class ConfigureServerParams(BaseModel):
    """Parameters for configure_server tool."""

    server_url: str = Field(
        ...,
        description="Base URL for the Chandra vLLM server (e.g., 'http://localhost:8001/v1')"
    )
    api_key: str = Field(
        default="chandra",
        description="API key for the server (typically 'chandra' for vLLM)"
    )
    max_tokens: int = Field(
        default=12384,
        description="Maximum tokens for OCR response"
    )
    temperature: float = Field(
        default=0.0,
        description="Sampling temperature (0.0 for deterministic)"
    )
    top_p: float = Field(
        default=0.1,
        description="Top-p sampling parameter"
    )
    timeout: int = Field(
        default=300,
        description="Request timeout in seconds"
    )


class ConfigureServerResponse(BaseModel):
    """Response from configure_server tool."""

    status: Literal["success", "error"]
    message: str
    connection_verified: bool = False
    server_url: Optional[str] = None
    error: Optional[str] = None


# ---------------------------------------------------------------------------
# Hybrid figure-recovery tools
# ---------------------------------------------------------------------------

from typing import List  # noqa: E402


class DetectMissingFiguresParams(BaseModel):
    """Parameters for detect_missing_figures tool."""

    markdown_path: str = Field(..., description="Path to the Markdown file produced by convert_pdf")


class FigureSpec(BaseModel):
    """One figure to recover."""

    figure_id: str = Field(..., description="Figure number as it appears in the caption, e.g. '3' or 'S1'")
    caption: Optional[str] = Field(
        default=None,
        description="Caption text from the Markdown (helps disambiguate). Filled from markdown_path when omitted.",
    )
    page: Optional[int] = Field(default=None, description="1-based page hint. Required when crop_box is given.")
    crop_box: Optional[List[float]] = Field(
        default=None,
        description="Manual crop [left, bottom, right, top] in PDF points (origin bottom-left). Overrides the heuristic.",
    )
    full_width: Optional[bool] = Field(
        default=None,
        description="Force a full-text-width crop (true) or a single-column crop (false). Default: infer from caption width.",
    )
    fallback_height_pt: float = Field(
        default=288.0,
        description="Height in points to crop above the caption when no graphics objects are found (default 4 inches).",
    )
    gap_tolerance_pt: float = Field(
        default=40.0,
        description="Max vertical gap in points between graphics objects that still belong to the same figure.",
    )


class RecoverFiguresParams(BaseModel):
    """Parameters for recover_figures tool."""

    pdf_path: str = Field(..., description="Path to the source PDF")
    markdown_path: Optional[str] = Field(
        default=None,
        description="Markdown from convert_pdf. Used to fill in captions and, when figures is omitted, to pick all missing figures.",
    )
    output_dir: Optional[str] = Field(
        default=None,
        description="Where to write figure images. Defaults to the Markdown file's directory (or the PDF's directory).",
    )
    figures: Optional[List[FigureSpec]] = Field(
        default=None,
        description="Figures to recover. Omit to recover every caption that detect_missing_figures reports as missing.",
    )
    dpi: int = Field(default=200, description="Render resolution for the crops")
    image_format: Literal["webp", "png"] = Field(default="webp", description="Output image format")


class RecoveredFigure(BaseModel):
    """Result for one recovered figure."""

    figure_id: str
    status: Literal["ok", "caption_not_found", "error"]
    page: Optional[int] = Field(default=None, description="1-based page number")
    caption_bbox_pt: Optional[List[float]] = None
    crop_box_pt: Optional[List[float]] = None
    method: Optional[Literal["graphics", "fallback", "manual"]] = None
    n_graphics: int = 0
    image_path: Optional[str] = None
    width_px: int = 0
    height_px: int = 0
    matched_text: Optional[str] = None
    match_score: Optional[float] = None
    note: Optional[str] = None


class RecoverFiguresResponse(BaseModel):
    """Response from recover_figures tool."""

    status: Literal["success", "error"]
    figures: List[RecoveredFigure] = Field(default_factory=list)
    error: Optional[str] = None
    message: Optional[str] = None


class InjectFigureSpec(BaseModel):
    figure_id: str = Field(..., description="Figure number matching the caption")
    image_path: str = Field(..., description="Path to the image to reference (written relative to the document)")


class InjectFiguresParams(BaseModel):
    """Parameters for inject_figures tool."""

    markdown_path: str = Field(..., description="Markdown file to edit in place")
    html_path: Optional[str] = Field(
        default=None,
        description="HTML file to edit in place. Defaults to the sibling .html of the Markdown file if it exists.",
    )
    figures: List[InjectFigureSpec] = Field(..., description="Figures to inject")


class InjectFiguresResponse(BaseModel):
    """Response from inject_figures tool."""

    status: Literal["success", "error"]
    markdown: Dict[str, str] = Field(default_factory=dict, description="figure_id -> injected | already_has_image | caption_not_found")
    html: Dict[str, str] = Field(default_factory=dict)
    html_path: Optional[str] = None
    error: Optional[str] = None
    message: Optional[str] = None


class RenderPageParams(BaseModel):
    """Parameters for render_pdf_page tool."""

    pdf_path: str = Field(..., description="Path to the PDF")
    page: int = Field(default=1, description="1-based page number")
    output_path: Optional[str] = Field(default=None, description="Where to save the PNG. Defaults next to the PDF.")
    dpi: int = Field(default=100, description="Render resolution")
    crop_box: Optional[List[float]] = Field(
        default=None,
        description="Optional [left, bottom, right, top] in PDF points to render only a region.",
    )


class RenderPageResponse(BaseModel):
    """Response from render_pdf_page tool."""

    status: Literal["success", "error"]
    image_path: Optional[str] = None
    width_px: int = 0
    height_px: int = 0
    page_size_pt: Optional[List[float]] = None
    error: Optional[str] = None
    message: Optional[str] = None
