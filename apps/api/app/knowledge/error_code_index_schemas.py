"""Contracts for read-only chunk error-code index evidence."""

from pydantic import BaseModel


class ErrorCodeIndexEntryResponse(BaseModel):
    error_code: str
    indexed_chunk_count: int
    published_chunk_count: int


class ErrorCodeIndexListResponse(BaseModel):
    items: list[ErrorCodeIndexEntryResponse]
    has_more: bool = False
