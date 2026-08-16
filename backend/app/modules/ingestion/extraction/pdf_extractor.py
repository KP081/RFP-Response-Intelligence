"""PDF content extraction using pdfplumber for layout-aware text and table extraction."""

import io
from typing import Any

import pdfplumber
import structlog

from app.modules.ingestion.extraction.header_footer_stripper import strip_headers_footers

logger = structlog.get_logger(__name__)


def extract_pdf_content(file_data: bytes) -> list[dict[str, Any]]:
    """
    Extract text blocks and tables from a PDF file.

    Args:
        file_data: Raw PDF file bytes.

    Returns:
        List of content blocks, each with type, page, content, and bbox.
        Block types: "text", "table", "heading".
    """
    blocks: list[dict[str, Any]] = []

    with pdfplumber.open(io.BytesIO(file_data)) as pdf:
        for page_num, page in enumerate(pdf.pages, start=1):
            page_width = page.width
            page_height = page.height

            # Extract tables first (they have priority)
            tables = page.extract_tables(table_settings={
                "vertical_strategy": "lines",
                "horizontal_strategy": "lines",
                "intersection_tolerance": 5,
                "snap_tolerance": 3,
                "join_tolerance": 3,
                "edge_min_length": 3,
                "min_words_vertical": 1,
                "min_words_horizontal": 1,
            })

            table_bboxes: list[tuple[float, float, float, float]] = []
            for table in tables:
                if not table or len(table) < 2:
                    continue

                # Find table bbox by searching for table area
                table_bbox = _find_table_bbox(page, table)
                if table_bbox:
                    table_bboxes.append(table_bbox)
                    blocks.append({
                        "type": "table",
                        "page": page_num,
                        "content": table,
                        "bbox": list(table_bbox),
                    })

            # Extract text blocks (words with positions)
            words = page.extract_words(
                keep_blank_chars=False,
                x_tolerance=3,
                y_tolerance=3,
            )

            # Group words into lines by y-position
            text_lines = _group_words_into_lines(words, y_tolerance=3)

            # Filter out words that are inside table bboxes
            filtered_lines = _filter_lines_outside_tables(text_lines, table_bboxes)

            # Group lines into text blocks by vertical proximity
            text_blocks = _group_lines_into_blocks(filtered_lines, y_gap_threshold=10)

            for block in text_blocks:
                if not block["lines"]:
                    continue

                content = "\n".join(line["text"] for line in block["lines"])
                content = content.strip()
                if not content:
                    continue

                # Determine if this looks like a heading
                block_type = _classify_block(block, page_height)

                bbox = (
                    min(line["x0"] for line in block["lines"]),
                    min(line["top"] for line in block["lines"]),
                    max(line["x1"] for line in block["lines"]),
                    max(line["bottom"] for line in block["lines"]),
                )

                blocks.append({
                    "type": block_type,
                    "page": page_num,
                    "content": content,
                    "bbox": list(bbox),
                })

    # Strip headers/footers
    blocks = strip_headers_footers(blocks, total_pages=len(pdf.pages) if 'pdf' in locals() else 0)

    # Sort by page then by vertical position
    blocks.sort(key=lambda b: (b["page"], b["bbox"][1] if b["bbox"] else 0))

    logger.info("pdf_extraction_complete", total_blocks=len(blocks))
    return blocks


def _find_table_bbox(page: pdfplumber.page.Page, table: list[list[str | None]]) -> tuple[float, float, float, float] | None:
    """Find the bounding box of a detected table on the page."""
    # Use pdfplumber's find_tables to get bbox
    found_tables = page.find_tables(table_settings={
        "vertical_strategy": "lines",
        "horizontal_strategy": "lines",
    })
    for ft in found_tables:
        # Check if this table matches our extracted table content
        ft_content = ft.extract()
        if _tables_match(ft_content, table):
            return (ft.bbox[0], ft.bbox[1], ft.bbox[2], ft.bbox[3])
    return None


def _tables_match(t1: list[list[str | None]], t2: list[list[str | None]]) -> bool:
    """Check if two tables have similar content."""
    if len(t1) != len(t2):
        return False
    for r1, r2 in zip(t1, t2):
        if len(r1) != len(r2):
            return False
        for c1, c2 in zip(r1, r2):
            if (c1 or "").strip() != (c2 or "").strip():
                return False
    return True


def _group_words_into_lines(words: list[dict[str, Any]], y_tolerance: float = 3) -> list[dict[str, Any]]:
    """Group words into lines based on y-position."""
    if not words:
        return []

    lines: list[dict[str, Any]] = []
    current_line: list[dict[str, Any]] = [words[0]]

    for word in words[1:]:
        last_word = current_line[-1]
        if abs(word["top"] - last_word["top"]) <= y_tolerance:
            current_line.append(word)
        else:
            # Finalize current line
            lines.append(_finalize_line(current_line))
            current_line = [word]

    if current_line:
        lines.append(_finalize_line(current_line))

    return lines


def _finalize_line(words: list[dict[str, Any]]) -> dict[str, Any]:
    """Create a line dict from a list of words."""
    words.sort(key=lambda w: w["x0"])
    text = " ".join(w["text"] for w in words)
    return {
        "text": text,
        "x0": min(w["x0"] for w in words),
        "x1": max(w["x1"] for w in words),
        "top": min(w["top"] for w in words),
        "bottom": max(w["bottom"] for w in words),
    }


def _filter_lines_outside_tables(lines: list[dict[str, Any]], table_bboxes: list[tuple[float, float, float, float]]) -> list[dict[str, Any]]:
    """Filter out lines that are inside table bounding boxes."""
    if not table_bboxes:
        return lines

    filtered = []
    for line in lines:
        line_center_y = (line["top"] + line["bottom"]) / 2
        line_center_x = (line["x0"] + line["x1"]) / 2

        inside_table = False
        for bbox in table_bboxes:
            if (bbox[0] <= line_center_x <= bbox[2] and
                bbox[1] <= line_center_y <= bbox[3]):
                inside_table = True
                break

        if not inside_table:
            filtered.append(line)

    return filtered


def _group_lines_into_blocks(lines: list[dict[str, Any]], y_gap_threshold: float = 10) -> list[dict[str, Any]]:
    """Group lines into text blocks based on vertical proximity."""
    if not lines:
        return []

    blocks: list[dict[str, Any]] = []
    current_block: dict[str, Any] = {"lines": [lines[0]]}

    for line in lines[1:]:
        last_line = current_block["lines"][-1]
        gap = line["top"] - last_line["bottom"]

        if gap <= y_gap_threshold:
            current_block["lines"].append(line)
        else:
            blocks.append(current_block)
            current_block = {"lines": [line]}

    blocks.append(current_block)
    return blocks


def _classify_block(block: dict[str, Any], page_height: float) -> str:
    """Classify a text block as 'heading' or 'text' based on heuristics."""
    if not block["lines"]:
        return "text"

    first_line = block["lines"][0]
    text = first_line["text"].strip()

    # Heuristics for heading detection
    # Short line, possibly all caps or title case, at top of page or after large gap
    if len(text) < 100 and (
        text.isupper() or
        text.istitle() or
        text.endswith(":") or
        first_line["top"] < page_height * 0.15  # Near top of page
    ):
        return "heading"

    return "text"