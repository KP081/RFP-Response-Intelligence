"""Header and footer detection and stripping for extracted document content."""

from collections import defaultdict
from typing import Any

import structlog

logger = structlog.get_logger(__name__)

# Minimum fraction of pages a block must appear on to be considered header/footer
PAGE_FRACTION_THRESHOLD = 0.6
# Margin threshold (fraction of page height) for top/bottom margin zones
MARGIN_FRACTION = 0.12


def strip_headers_footers(
    blocks: list[dict[str, Any]],
    total_pages: int,
) -> list[dict[str, Any]]:
    """
    Detect and remove running headers/footers from extracted blocks.

    Args:
        blocks: List of content blocks with type, page, content, bbox.
        total_pages: Total number of pages in the document.

    Returns:
        Filtered list of blocks with headers/footers removed.
    """
    if not blocks or total_pages <= 1:
        return blocks

    # Group blocks by page
    blocks_by_page: dict[int, list[dict[str, Any]]] = defaultdict(list)
    for block in blocks:
        page = block.get("page", 1)
        blocks_by_page[page].append(block)

    # Find candidate header/footer blocks (in top/bottom margin zones)
    header_candidates: list[dict[str, Any]] = []
    footer_candidates: list[dict[str, Any]] = []

    for page_num in range(1, total_pages + 1):
        page_blocks = blocks_by_page.get(page_num, [])
        if not page_blocks:
            continue

        # Estimate page height from bboxes
        page_height = max((b["bbox"][3] for b in page_blocks if b.get("bbox")), default=792)

        top_margin = page_height * MARGIN_FRACTION
        bottom_margin = page_height * (1 - MARGIN_FRACTION)

        for block in page_blocks:
            bbox = block.get("bbox")
            if not bbox:
                continue

            block_top = bbox[1]
            block_bottom = bbox[3]

            # Check if block is in top margin zone (header candidate)
            if block_top <= top_margin:
                header_candidates.append({
                    "block": block,
                    "page": page_num,
                    "normalized_content": _normalize_content(block["content"]),
                    "rel_y": block_top / page_height,
                })

            # Check if block is in bottom margin zone (footer candidate)
            if block_bottom >= bottom_margin:
                footer_candidates.append({
                    "block": block,
                    "page": page_num,
                    "normalized_content": _normalize_content(block["content"]),
                    "rel_y": block_bottom / page_height,
                })

    # Find repeated headers
    header_signatures = _group_similar_blocks(header_candidates)
    footer_signatures = _group_similar_blocks(footer_candidates)

    # Determine which signatures appear on enough pages
    min_pages = max(2, int(total_pages * PAGE_FRACTION_THRESHOLD))

    header_pages_to_strip = set()
    for sig, occurrences in header_signatures.items():
        if len(occurrences) >= min_pages:
            for occ in occurrences:
                header_pages_to_strip.add((occ["page"], id(occ["block"])))

    footer_pages_to_strip = set()
    for sig, occurrences in footer_signatures.items():
        if len(occurrences) >= min_pages:
            for occ in occurrences:
                footer_pages_to_strip.add((occ["page"], id(occ["block"])))

    # Filter out header/footer blocks
    stripped_blocks = []
    stripped_count = 0

    for block in blocks:
        page = block.get("page", 1)
        block_id = id(block)

        if (page, block_id) in header_pages_to_strip or (page, block_id) in footer_pages_to_strip:
            stripped_count += 1
            logger.debug("stripped_header_footer", page=page, content_preview=block["content"][:50])
        else:
            stripped_blocks.append(block)

    logger.info(
        "header_footer_stripping_complete",
        total_blocks=len(blocks),
        stripped=stripped_count,
        remaining=len(stripped_blocks),
    )

    return stripped_blocks


def _normalize_content(content: Any) -> str:
    """Normalize content for comparison (lowercase, strip whitespace, remove page numbers)."""
    if not isinstance(content, str):
        # For tables, convert to string representation
        if isinstance(content, list):
            return " ".join(str(cell) for row in content for cell in row)
        return str(content)
    normalized = content.lower().strip()
    # Remove common page number patterns - only at start/end of text, not embedded
    import re
    # Remove "page X" at start or end
    normalized = re.sub(r'^\s*page\s+\d+\s*', '', normalized)
    normalized = re.sub(r'\s*page\s+\d+\s*$', '', normalized)
    # Remove "X / Y" or "X/Y" at start or end
    normalized = re.sub(r'^\s*\d+\s*/\s*\d+\s*', '', normalized)
    normalized = re.sub(r'\s*\d+\s*/\s*\d+\s*$', '', normalized)
    normalized = re.sub(r'\s+', ' ', normalized)
    return normalized.strip()


def _group_similar_blocks(candidates: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    """Group blocks by similar content and relative position."""
    groups: dict[str, list[dict[str, Any]]] = defaultdict(list)

    for candidate in candidates:
        norm_content = candidate["normalized_content"]
        rel_y = candidate["rel_y"]

        # Create a signature combining normalized content and relative position bucket
        pos_bucket = "top" if rel_y < 0.5 else "bottom"
        signature = f"{pos_bucket}:{norm_content}"

        # Use exact match on normalized content for header/footer detection
        # Fuzzy matching is too aggressive and catches real content that happens to have similar words
        if signature in groups:
            groups[signature].append(candidate)
        else:
            groups[signature].append(candidate)

    return groups