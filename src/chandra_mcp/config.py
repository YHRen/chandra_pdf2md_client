"""Configuration management for Chandra MCP Server."""

import os
from dataclasses import dataclass, field
from typing import Optional
import httpx


@dataclass
class ChandraConfig:
    """Configuration for Chandra MCP Server."""

    # Server settings
    server_url: str = "http://localhost:8001/v1"
    api_key: str = "chandra"
    max_tokens: int = 12384
    temperature: float = 0.0
    top_p: float = 0.1
    timeout: int = 300

    # Image processing settings
    image_dpi: int = 192
    min_pdf_image_dim: int = 1024
    min_image_dim: int = 1536
    bbox_scale: int = 1024

    # Output settings
    default_output_dir: str = "./output"
    image_format: str = "webp"

    # Processing settings
    include_headers_footers: bool = False
    include_images: bool = True

    def __post_init__(self):
        """Load configuration from environment variables."""
        self.load_from_env()

    def load_from_env(self) -> None:
        """Load configuration from environment variables."""
        # Server settings
        if env_url := os.getenv("CHANDRA_SERVER_URL"):
            self.server_url = env_url
        if env_key := os.getenv("CHANDRA_API_KEY"):
            self.api_key = env_key
        if env_max_tokens := os.getenv("CHANDRA_MAX_TOKENS"):
            try:
                self.max_tokens = int(env_max_tokens)
            except ValueError:
                pass
        if env_temperature := os.getenv("CHANDRA_TEMPERATURE"):
            try:
                self.temperature = float(env_temperature)
            except ValueError:
                pass
        if env_top_p := os.getenv("CHANDRA_TOP_P"):
            try:
                self.top_p = float(env_top_p)
            except ValueError:
                pass
        if env_timeout := os.getenv("CHANDRA_TIMEOUT"):
            try:
                self.timeout = int(env_timeout)
            except ValueError:
                pass

        # Image processing settings
        if env_dpi := os.getenv("CHANDRA_IMAGE_DPI"):
            try:
                self.image_dpi = int(env_dpi)
            except ValueError:
                pass
        if env_min_pdf := os.getenv("CHANDRA_MIN_PDF_IMAGE_DIM"):
            try:
                self.min_pdf_image_dim = int(env_min_pdf)
            except ValueError:
                pass
        if env_min_image := os.getenv("CHANDRA_MIN_IMAGE_DIM"):
            try:
                self.min_image_dim = int(env_min_image)
            except ValueError:
                pass

        # Output settings
        if env_output_dir := os.getenv("CHANDRA_OUTPUT_DIR"):
            self.default_output_dir = env_output_dir
        if env_image_format := os.getenv("CHANDRA_IMAGE_FORMAT"):
            self.image_format = env_image_format

    def update(
        self,
        server_url: Optional[str] = None,
        api_key: Optional[str] = None,
        max_tokens: Optional[int] = None,
        temperature: Optional[float] = None,
        top_p: Optional[float] = None,
        timeout: Optional[int] = None,
    ) -> None:
        """Update configuration at runtime."""
        if server_url is not None:
            self.server_url = server_url
        if api_key is not None:
            self.api_key = api_key
        if max_tokens is not None:
            self.max_tokens = max_tokens
        if temperature is not None:
            self.temperature = temperature
        if top_p is not None:
            self.top_p = top_p
        if timeout is not None:
            self.timeout = timeout

    async def verify_connection(self) -> tuple[bool, str]:
        """
        Verify connection to the Chandra server.

        Returns:
            Tuple of (success: bool, message: str)
        """
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                # Try to get the models endpoint
                response = await client.get(f"{self.server_url}/models")
                if response.status_code == 200:
                    return True, "Successfully connected to Chandra server"
                else:
                    return False, f"Server returned status code {response.status_code}"
        except httpx.ConnectError:
            return (
                False,
                f"Failed to connect to {self.server_url}. "
                "Ensure the Chandra vLLM server is running."
            )
        except httpx.TimeoutException:
            return False, f"Connection to {self.server_url} timed out"
        except Exception as e:
            return False, f"Connection error: {str(e)}"

    def get_config_dict(self) -> dict:
        """Get configuration as a dictionary."""
        return {
            "server_url": self.server_url,
            "api_key": "***" if self.api_key else None,  # Redact API key
            "max_tokens": self.max_tokens,
            "temperature": self.temperature,
            "top_p": self.top_p,
            "timeout": self.timeout,
            "image_dpi": self.image_dpi,
            "min_pdf_image_dim": self.min_pdf_image_dim,
            "min_image_dim": self.min_image_dim,
            "bbox_scale": self.bbox_scale,
            "default_output_dir": self.default_output_dir,
            "image_format": self.image_format,
            "include_headers_footers": self.include_headers_footers,
            "include_images": self.include_images,
        }
