"""DOCX content extraction using python-docx for structure-preserving extraction."""

import io
from typing import Any

import structlog
from docx import Document
from docx.table import Table
from docx.text.paragraph import Paragraph

from app.modules.ingestion.extraction.header_footer_stripper import strip_headers_footers

logger = structlog.get_logger(__name__)


def extract_docx_content(file_data: bytes) -> list[dict[str, Any]]:
    """
    Extract text blocks and tables from a DOCX file.

    Args:
        file_data: Raw DOCX file bytes.

    Returns:
        List of content blocks, each with type, page, content, and bbox.
        Block types: "text", "table", "heading".
        Note: DOCX doesn't have fixed pages, so page is approximated by section breaks.
    """
    blocks: list[dict[str, Any]] = []

    doc = Document(io.BytesIO(file_data))

    # Track approximate page number based on section breaks
    current_page = 1

    for element in doc.element.body:
        tag = element.tag.split("}")[-1]  # Remove namespace

        if tag == "p":  # Paragraph
            para = Paragraph(element, doc)
            text = para.text.strip()

            if not text:
                continue

            # Check if it's a heading
            is_heading = _is_heading(para)
            block_type = "heading" if is_heading else "text"

            # Approximate bbox (not available in DOCX, use placeholder)
            bbox = [0.0, 0.0, 612.0, 792.0]  # Standard letter size placeholder

            blocks.append({
                "type": block_type,
                "page": current_page,
                "content": text,
                "bbox": bbox,
            })

        elif tag == "tbl":  # Table
            table = Table(element, doc)
            table_data = _extract_table(table)

            if table_data and len(table_data) >= 2:
                bbox = [0.0, 0.0, 612.0, 792.0]
                blocks.append({
                    "type": "table",
                    "page": current_page,
                    "content": table_data,
                    "bbox": bbox,
                })

        elif tag == "sectPr":  # Section properties - indicates page break
            current_page += 1

    # Strip headers/footers (DOCX headers/footers are separate, but we check for repeated content)
    blocks = strip_headers_footers(blocks, total_pages=current_page)

    # Sort by page then by order
    blocks.sort(key=lambda b: (b["page"], id(b)))

    logger.info("docx_extraction_complete", total_blocks=len(blocks))
    return blocks


def _is_heading(para: Paragraph) -> bool:
    """Check if a paragraph is a heading based on style."""
    style_name = para.style.name.lower() if para.style else ""
    return style_name.startswith("heading") or style_name.startswith("title")


def _extract_table(table: Table) -> list[list[str]]:
    """Extract table data as list of rows, each row is list of cell texts."""
    rows_data: list[list[str]] = []

    for row in table.rows:
        row_data: list[str] = []
        for cell in row.cells:
            cell_text = cell.text.strip()
            row_data.append(cell_text)
        rows_data.append(row_data)

    return rows_data