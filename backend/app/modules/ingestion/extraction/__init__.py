"""Extraction module for text and table extraction from documents."""

from app.modules.ingestion.extraction.docx_extractor import extract_docx_content
from app.modules.ingestion.extraction.header_footer_stripper import strip_headers_footers
from app.modules.ingestion.extraction.pdf_extractor import extract_pdf_content

__all__ = [
    "extract_pdf_content",
    "extract_docx_content",
    "strip_headers_footers",
]