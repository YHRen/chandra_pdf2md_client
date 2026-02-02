"""Utility functions for Chandra MCP Server."""

import os
import json
from pathlib import Path
from typing import Optional, Dict, Any
import filetype


def validate_file_path(file_path: str) -> None:
    """
    Validate that a file path exists and is readable.

    Args:
        file_path: Path to validate

    Raises:
        FileNotFoundError: If file doesn't exist
        PermissionError: If file isn't readable
    """
    path = Path(file_path)
    if not path.exists():
        raise FileNotFoundError(
            f"File not found: {file_path}. "
            "Please verify the path is correct."
        )
    if not path.is_file():
        raise ValueError(
            f"Path is not a file: {file_path}. "
            "Please provide a path to a PDF or image file."
        )
    if not os.access(path, os.R_OK):
        raise PermissionError(
            f"File is not readable: {file_path}. "
            "Please check file permissions."
        )


def ensure_output_dir(output_dir: str) -> Path:
    """
    Ensure output directory exists, creating it if necessary.

    Args:
        output_dir: Directory path

    Returns:
        Path object for the directory

    Raises:
        PermissionError: If directory can't be created
    """
    path = Path(output_dir)
    try:
        path.mkdir(parents=True, exist_ok=True)
        return path
    except PermissionError as e:
        raise PermissionError(
            f"Cannot create output directory {output_dir}: {e}. "
            "Please check permissions."
        )


def estimate_processing_time(num_pages: int) -> str:
    """
    Estimate processing time based on number of pages.

    Args:
        num_pages: Number of pages to process

    Returns:
        Human-readable time estimate
    """
    # Rough estimate: 10-15 seconds per page
    min_seconds = num_pages * 10
    max_seconds = num_pages * 15

    if max_seconds < 60:
        return f"{min_seconds}-{max_seconds} seconds"
    else:
        min_minutes = min_seconds // 60
        max_minutes = max_seconds // 60
        if max_minutes < 60:
            return f"{min_minutes}-{max_minutes} minutes"
        else:
            min_hours = min_minutes / 60
            max_hours = max_minutes / 60
            return f"{min_hours:.1f}-{max_hours:.1f} hours"


def format_error(
    error: Exception,
    error_type: Optional[str] = None,
    details: Optional[Dict[str, Any]] = None,
    suggestion: Optional[str] = None
) -> str:
    """
    Format an error message in a structured JSON format.

    Args:
        error: The exception that occurred
        error_type: Custom error type (defaults to exception class name)
        details: Additional error details
        suggestion: Suggestion for how to fix the error

    Returns:
        JSON-formatted error string
    """
    error_dict = {
        "error": error_type or error.__class__.__name__,
        "message": str(error),
        "details": details or {},
    }

    # Add suggestions based on error type
    if suggestion:
        error_dict["suggestion"] = suggestion
    elif isinstance(error, FileNotFoundError):
        error_dict["suggestion"] = (
            "Verify the file path and ensure the file exists and is accessible."
        )
    elif isinstance(error, ConnectionError):
        error_dict["suggestion"] = (
            "Ensure the Chandra vLLM server is running at the configured URL. "
            "Try: curl <server_url>/models"
        )
    elif isinstance(error, PermissionError):
        error_dict["suggestion"] = (
            "Check file and directory permissions."
        )
    elif isinstance(error, ValueError) and "page range" in str(error).lower():
        error_dict["suggestion"] = (
            "Use a valid page range within document bounds. "
            "Example: '1-3' or '1,3,5'"
        )

    return json.dumps(error_dict, indent=2)


def get_file_info(file_path: str) -> Dict[str, Any]:
    """
    Get information about a file.

    Args:
        file_path: Path to the file

    Returns:
        Dictionary with file information
    """
    path = Path(file_path)
    file_size = path.stat().st_size

    # Detect file type
    kind = filetype.guess(file_path)
    if kind:
        file_type = kind.extension
        mime_type = kind.mime
    else:
        file_type = path.suffix.lstrip('.')
        mime_type = "unknown"

    return {
        "file_path": str(path.absolute()),
        "file_name": path.name,
        "file_size_bytes": file_size,
        "file_type": file_type,
        "mime_type": mime_type,
    }
