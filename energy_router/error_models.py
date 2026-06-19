"""Pydantic models for structured API error responses.

All exceptions raised by the FastAPI application are caught by a custom
exception handler and serialised into one of these shapes so clients
receive a consistent JSON envelope regardless of the error source.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class ErrorResponse(BaseModel):
    """Standard error response for 4xx and 5xx API errors.

    Returned by the global exception handler for ``HTTPException``,
    ``RequestValidationError``, and unhandled exceptions.
    """

    status: int = Field(
        ...,
        description="HTTP status code of the error",
        examples=[400, 401, 403, 404, 429, 500, 503],
    )
    detail: str = Field(
        ...,
        description="Human-readable error message explaining what went wrong",
        examples=[
            "Unauthorized. Provide a valid API key via the X-API-Key header.",
            "Rate limit exceeded. Try again later.",
            "Router not initialized",
        ],
    )
    error_code: str = Field(
        ...,
        description="Machine-readable error code for programmatic handling",
        examples=[
            "unauthorized",
            "rate_limited",
            "router_not_initialized",
            "validation_error",
            "internal_error",
        ],
    )


class FieldError(BaseModel):
    """A single field-level validation error."""

    field: str = Field(
        ...,
        description="Name of the input field that failed validation",
        examples=["defer_until"],
    )
    message: str = Field(
        ...,
        description="Human-readable description of the validation failure",
        examples=["Input should be 'low', 'medium' or 'high'"],
    )


class ValidationErrorResponse(BaseModel):
    """Error response returned when request validation fails.

    Extends ``ErrorResponse`` with a list of per-field validation
    messages so clients can pinpoint the exact inputs that need
    correction.
    """

    status: int = Field(
        ...,
        description="HTTP status code (always 422 for validation errors)",
        examples=[422],
    )
    detail: str = Field(
        ...,
        description="Summary of the validation failure",
        examples=["Request validation failed"],
    )
    error_code: str = Field(
        ...,
        description="Always 'validation_error' for validation failures",
        examples=["validation_error"],
    )
    errors: list[FieldError] = Field(
        ...,
        description="Per-field validation error details",
    )
