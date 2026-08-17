"""Ingestion module for document processing pipeline."""

from app.modules.ingestion.router import router as ingestion_router

__all__ = ["ingestion_router"]