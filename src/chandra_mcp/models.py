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
