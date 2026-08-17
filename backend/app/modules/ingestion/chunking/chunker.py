"""Semantic chunking with structure-aware boundaries and metadata tagging."""

import re
from typing import Any

import structlog
from tiktoken import encoding_for_model

logger = structlog.get_logger(__name__)

# Token budget for text chunks (configurable)
DEFAULT_MAX_TOKENS = 500
# Maximum tokens for a table chunk before splitting (tables can exceed this)
MAX_TABLE_TOKENS = 2000

# Regex patterns for heading/section detection
SECTION_NUMBER_PATTERN = re.compile(r"^(\d+(?:\.\d+){0,3})\s+(.+)$")
SECTION_KEYWORD_PATTERN = re.compile(r"^(Section|Chapter|Annexure|Appendix)\s+(\d+(?:\.\d+){0,2})\b", re.IGNORECASE)
HEADING_LIKE_PATTERN = re.compile(r"^([A-Z][A-Za-z0-9\s,\-\(\)]{5,80}):?$")


class SectionTracker:
    """Tracks current heading/section context while walking through blocks."""

    def __init__(self) -> None:
        self.current_section_path: list[str] = []
        self.current_heading: str | None = None

    def update_from_block(self, block: dict[str, Any]) -> None:
        """Update section context based on a block."""
        block_type = block.get("type")
        content = block.get("content", "")

        # Table blocks have list content, skip section tracking for them
        if block_type == "table":
            return

        if isinstance(content, list):
            content = ""
        content = content.strip()

        if block_type == "heading":
            # Explicit heading from extractor
            self._process_heading(content)
        elif block_type == "text":
            # Try to detect numbered sections or section keywords in text
            self._detect_section_from_text(content)

    def _process_heading(self, heading_text: str) -> None:
        """Process an explicit heading block."""
        # Clean up heading text
        heading_text = heading_text.strip()
        if not heading_text:
            return

        # Try to extract section number
        section_match = SECTION_NUMBER_PATTERN.match(heading_text)
        if section_match:
            section_num = section_match.group(1)
            section_title = section_match.group(2).strip()
            self._update_section_stack(section_num, section_title)
            self.current_heading = heading_text
            return

        # Try section keyword pattern
        keyword_match = SECTION_KEYWORD_PATTERN.match(heading_text)
        if keyword_match:
            section_num = keyword_match.group(2)
            section_title = heading_text
            self._update_section_stack(section_num, section_title)
            self.current_heading = heading_text
            return

        # Generic heading - use as-is
        self.current_heading = heading_text
        # Add to section path if it looks like a structural heading
        if len(self.current_section_path) == 0 or len(heading_text) < 60:
            self.current_section_path.append(heading_text)

    def _detect_section_from_text(self, text: str) -> None:
        """Detect section boundaries from text content (for PDFs without explicit headings)."""
        lines = text.split("\n")
        for line in lines[:3]:  # Check first few lines only
            line = line.strip()
            if not line:
                continue

            section_match = SECTION_NUMBER_PATTERN.match(line)
            if section_match:
                section_num = section_match.group(1)
                section_title = section_match.group(2).strip()
                self._update_section_stack(section_num, section_title)
                self.current_heading = line
                break

            keyword_match = SECTION_KEYWORD_PATTERN.match(line)
            if keyword_match:
                section_num = keyword_match.group(2)
                section_title = line
                self._update_section_stack(section_num, section_title)
                self.current_heading = line
                break

    def _update_section_stack(self, section_num: str, section_title: str) -> None:
        """Update the section path stack based on section number depth."""
        # Parse section number depth (e.g., "2.1.3" -> depth 3)
        depth = section_num.count(".") + 1

        # Truncate stack to parent depth
        self.current_section_path = self.current_section_path[: depth - 1]

        # Add this section
        section_label = f"{section_num} {section_title}".strip()
        if len(self.current_section_path) >= depth:
            self.current_section_path[depth - 1] = section_label
        else:
            self.current_section_path.append(section_label)

    def get_section_path(self) -> str | None:
        """Get the current section path as a string."""
        if not self.current_section_path:
            return None
        return " > ".join(self.current_section_path)

    def get_current_heading(self) -> str | None:
        """Get the current heading."""
        return self.current_heading


def count_tokens(text: str, model: str = "gpt-4o-mini") -> int:
    """Count tokens in text using tiktoken."""
    try:
        enc = encoding_for_model(model)
        return len(enc.encode(text))
    except Exception:
        # Fallback: rough estimate (4 chars per token)
        return len(text) // 4


def table_to_text(table: list[list[str | None]]) -> str:
    """Convert a table (list of rows) to a text representation for token counting."""
    lines = []
    for row in table:
        cells = [str(c or "").strip() for c in row]
        lines.append(" | ".join(cells))
    return "\n".join(lines)


def split_table_by_rows(table: list[list[str | None]], max_tokens: int = MAX_TABLE_TOKENS) -> list[list[list[str | None]]]:
    """Split a large table into row groups, keeping header row in each group."""
    if not table or len(table) < 2:
        return [table]

    header = table[0]
    header_tokens = count_tokens(table_to_text([header]))

    # If header alone exceeds budget, don't split (return as-is)
    if header_tokens >= max_tokens:
        return [table]

    chunks = []
    current_chunk = [header]
    current_tokens = header_tokens

    for row in table[1:]:
        row_text = table_to_text([row])
        row_tokens = count_tokens(row_text)

        # If this row alone exceeds budget, keep it with header
        if row_tokens >= max_tokens:
            if len(current_chunk) > 1:
                chunks.append(current_chunk)
            chunks.append([header, row])
            current_chunk = [header]
            current_tokens = header_tokens
            continue

        # Check if adding this row would exceed budget
        if current_tokens + row_tokens > max_tokens:
            chunks.append(current_chunk)
            current_chunk = [header, row]
            current_tokens = header_tokens + row_tokens
        else:
            current_chunk.append(row)
            current_tokens += row_tokens

    if len(current_chunk) > 1:
        chunks.append(current_chunk)

    return chunks if chunks else [table]


def create_chunks_from_blocks(
    blocks: list[dict[str, Any]],
    max_tokens: int = DEFAULT_MAX_TOKENS,
) -> list[dict[str, Any]]:
    """
    Convert raw extraction blocks into semantic chunks.

    Rules:
    - Text blocks accumulate up to max_tokens
    - Heading boundaries always start a new chunk
    - Table blocks are always isolated (never merged with text)
    - Large tables are split by row groups with header repeated
    - Every chunk gets section_path from current heading context
    """
    if not blocks:
        return []

    tracker: SectionTracker = SectionTracker()
    chunks: list[dict[str, Any]] = []
    current_text_blocks: list[dict[str, Any]] = []
    current_text_tokens = 0
    chunk_index = 0

    def flush_text_chunk() -> None:
        nonlocal current_text_blocks, current_text_tokens, chunk_index
        if not current_text_blocks:
            return

        # Combine text content
        content_parts = [b["content"] for b in current_text_blocks]
        content = "\n\n".join(content_parts)

        # Determine page range
        pages = [b["page"] for b in current_text_blocks]
        page_start = min(pages)
        page_end = max(pages)

        # Get section path
        section_path = tracker.get_section_path()

        chunks.append({
            "chunk_index": chunk_index,
            "content": content,
            "chunk_type": "text",
            "page_start": page_start,
            "page_end": page_end,
            "section_path": section_path,
            "token_count": current_text_tokens,
        })
        chunk_index += 1

        current_text_blocks = []
        current_text_tokens = 0

    for block in blocks:
        block_type = block.get("type", "text")
        content = block.get("content", "")
        page = block.get("page", 1)

        # Update section tracker
        tracker.update_from_block(block)

        if block_type == "table":
            # Flush any pending text chunk
            flush_text_chunk()

            # Process table - may split into multiple chunks
            table_data = content if isinstance(content, list) else []
            table_chunks = split_table_by_rows(table_data, max_tokens=max_tokens)

            for table_chunk in table_chunks:
                table_text = table_to_text(table_chunk)
                table_tokens = count_tokens(table_text)

                chunks.append({
                    "chunk_index": chunk_index,
                    "content": table_text,
                    "chunk_type": "table",
                    "page_start": page,
                    "page_end": page,
                    "section_path": tracker.get_section_path(),
                    "token_count": table_tokens,
                })
                chunk_index += 1

        elif block_type == "heading":
            # Flush pending text chunk (heading starts new section)
            flush_text_chunk()

            # Heading becomes its own chunk if substantial, or just updates context
            heading_text = content.strip()
            if len(heading_text) > 5:  # Only create chunk for substantial headings
                heading_tokens = count_tokens(heading_text)
                chunks.append({
                    "chunk_index": chunk_index,
                    "content": heading_text,
                    "chunk_type": "heading",
                    "page_start": page,
                    "page_end": page,
                    "section_path": tracker.get_section_path(),
                    "token_count": heading_tokens,
                })
                chunk_index += 1

        else:  # text block
            block_tokens = count_tokens(content)

            # Check if this block would exceed budget
            if current_text_tokens + block_tokens > max_tokens and current_text_blocks:
                flush_text_chunk()

            current_text_blocks.append(block)
            current_text_tokens += block_tokens

    # Flush any remaining text
    flush_text_chunk()

    logger.info("chunking_complete", total_chunks=len(chunks), max_tokens=max_tokens)
    return chunks