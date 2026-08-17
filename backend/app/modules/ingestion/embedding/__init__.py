"""Embedding module for generating vector embeddings of document chunks."""

from app.modules.ingestion.embedding.embedder import (
    embed_chunks,
    embed_document_chunks,
)

__all__ = [
    "embed_chunks",
    "embed_document_chunks",
]
