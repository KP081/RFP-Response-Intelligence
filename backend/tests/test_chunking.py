"""Integration tests for semantic chunking (Task 13)."""

import os
from pathlib import Path

import pytest
import structlog

from app.modules.ingestion.chunking import (
    SectionTracker,
    count_tokens,
    create_chunks_from_blocks,
)
from app.modules.ingestion.extraction import extract_pdf_content

logger = structlog.get_logger(__name__)

# Path to the test fixture
FIXTURE_PATH = Path(__file__).parent.parent.parent / "plan" / "fixtures" / "RFP" / "tele-manas-rfp-sample.pdf"


def _check_fixture() -> None:
    """Check if fixture exists, fail in CI if missing, skip otherwise."""
    if not FIXTURE_PATH.exists():
        if os.environ.get("CI"):
            pytest.fail(f"Required fixture missing in CI: {FIXTURE_PATH}")
        pytest.skip(f"Fixture not found at {FIXTURE_PATH} (skipping outside CI)")


@pytest.mark.integration
def test_chunking_section_tracker():
    """Test that SectionTracker correctly builds section paths."""
    tracker = SectionTracker()

    # Simulate heading blocks
    tracker.update_from_block({"type": "heading", "content": "1. Introduction"})
    assert tracker.get_section_path() == "1. Introduction"

    tracker.update_from_block({"type": "heading", "content": "1.1 Background"})
    assert tracker.get_section_path() == "1. Introduction > 1.1 Background"

    tracker.update_from_block({"type": "heading", "content": "1.1.1 Project History"})
    assert tracker.get_section_path() == "1. Introduction > 1.1 Background > 1.1.1 Project History"

    # Going back to higher level
    tracker.update_from_block({"type": "heading", "content": "1.2 Scope"})
    assert tracker.get_section_path() == "1. Introduction > 1.2 Scope"

    # New top-level section (accumulates - doesn't reset)
    tracker.update_from_block({"type": "heading", "content": "2. Requirements"})
    assert tracker.get_section_path() == "1. Introduction > 1.2 Scope > 2. Requirements"


@pytest.mark.integration
def test_chunking_section_tracker_with_keywords():
    """Test SectionTracker with section keyword patterns."""
    tracker = SectionTracker()

    tracker.update_from_block({"type": "heading", "content": "Section 3.1 Technical Requirements"})
    assert "3.1" in tracker.get_section_path()
    assert "Technical Requirements" in tracker.get_section_path()

    tracker.update_from_block({"type": "heading", "content": "Annexure 4 Financial Details"})
    assert "4" in tracker.get_section_path()


@pytest.mark.integration
def test_chunking_section_tracker_from_text():
    """Test SectionTracker detecting sections from text blocks."""
    tracker = SectionTracker()

    # Text block starting with section number
    tracker.update_from_block({
        "type": "text",
        "content": "2.1 Solution Components\n\nThis section describes the solution..."
    })
    assert tracker.get_section_path() is not None
    assert "2.1" in tracker.get_section_path()


@pytest.mark.integration
def test_chunking_basic_text_grouping():
    """Test that text blocks are grouped up to token budget."""
    blocks = [
        {"type": "text", "page": 1, "content": "This is a short paragraph."},
        {"type": "text", "page": 1, "content": "This is another short paragraph."},
        {"type": "text", "page": 1, "content": " ".join(["word"] * 200)},  # ~200 tokens
    ]

    chunks = create_chunks_from_blocks(blocks, max_tokens=500)

    # Should have 1 chunk (all fit within 500 tokens)
    assert len(chunks) == 1
    assert chunks[0]["chunk_type"] == "text"
    assert chunks[0]["token_count"] <= 500


@pytest.mark.integration
def test_chunking_splits_on_token_budget():
    """Test that chunks split when token budget exceeded."""
    blocks = [
        {"type": "text", "page": 1, "content": " ".join(["word"] * 300)},
        {"type": "text", "page": 1, "content": " ".join(["word"] * 300)},
    ]

    chunks = create_chunks_from_blocks(blocks, max_tokens=500)

    # Should have 2 chunks (each ~300 tokens, budget 500)
    assert len(chunks) == 2
    for chunk in chunks:
        assert chunk["token_count"] <= 500


@pytest.mark.integration
def test_chunking_isolates_tables():
    """Test that table blocks are always isolated into their own chunks."""
    blocks = [
        {"type": "text", "page": 1, "content": "Introduction text before table."},
        {"type": "table", "page": 1, "content": [["Header 1", "Header 2"], ["Row 1", "Data 1"], ["Row 2", "Data 2"]]},
        {"type": "text", "page": 1, "content": "Text after table."},
    ]

    chunks = create_chunks_from_blocks(blocks, max_tokens=500)

    # Should have 3 chunks: text, table, text
    assert len(chunks) == 3
    assert chunks[0]["chunk_type"] == "text"
    assert chunks[1]["chunk_type"] == "table"
    assert chunks[2]["chunk_type"] == "text"

    # Table chunk should have table content
    assert "Header 1" in chunks[1]["content"]
    assert "Header 2" in chunks[1]["content"]


@pytest.mark.integration
def test_chunking_table_carries_section_path():
    """Test that table chunks get the current section path."""
    blocks = [
        {"type": "heading", "page": 1, "content": "2.1 Solution Components"},
        {"type": "table", "page": 1, "content": [["Role", "Count"], ["Developer", "5"], ["QA", "2"]]},
    ]

    chunks = create_chunks_from_blocks(blocks)

    assert len(chunks) == 2
    assert chunks[1]["chunk_type"] == "table"
    assert chunks[1]["section_path"] is not None
    assert "2.1" in chunks[1]["section_path"]


@pytest.mark.integration
def test_chunking_heading_boundary_starts_new_chunk():
    """Test that heading boundaries always start a new chunk even under budget."""
    blocks = [
        {"type": "text", "page": 1, "content": "Text in section 1."},
        {"type": "heading", "page": 1, "content": "2. New Section"},
        {"type": "text", "page": 1, "content": "Text in section 2."},
    ]

    chunks = create_chunks_from_blocks(blocks, max_tokens=500)

    # Should have 3 chunks: text, heading, text (heading forces boundary)
    assert len(chunks) >= 3
    # Find the heading chunk
    heading_chunks = [c for c in chunks if c["chunk_type"] == "heading"]
    assert len(heading_chunks) >= 1
    assert "New Section" in heading_chunks[0]["content"]


@pytest.mark.integration
def test_chunking_large_table_split():
    """Test that large tables are split by row groups with header repeated."""
    # Create a large table (header + 50 rows with more content)
    header = ["Column 1", "Column 2", "Column 3", "Column 4", "Column 5"]
    rows = [[f"Row {i} Col 1", f"Row {i} Col 2", f"Row {i} Col 3", f"Row {i} Col 4", f"Row {i} Col 5"] for i in range(50)]
    table = [header] + rows

    blocks = [
        {"type": "table", "page": 1, "content": table},
    ]

    chunks = create_chunks_from_blocks(blocks, max_tokens=300)

    # Should have multiple table chunks
    table_chunks = [c for c in chunks if c["chunk_type"] == "table"]
    assert len(table_chunks) >= 2

    # Each chunk should have the header
    for chunk in table_chunks:
        assert "Column 1" in chunk["content"]
        assert "Column 2" in chunk["content"]
        assert "Column 3" in chunk["content"]


@pytest.mark.integration
def test_pdf_extraction_then_chunking_tele_manas_fixture():
    """Integration test: full chain upload → extract → chunk against Tele-MANAS fixture."""
    _check_fixture()

    with open(FIXTURE_PATH, "rb") as f:
        file_data = f.read()

    # Step 1: Extract
    blocks = extract_pdf_content(file_data)
    assert len(blocks) > 0

    # Step 2: Chunk
    chunks = create_chunks_from_blocks(blocks)

    # Basic validation
    assert len(chunks) > 10, f"Expected many chunks, got {len(chunks)}"

    # Check chunk types distribution
    type_counts: dict[str, int] = {}
    for c in chunks:
        type_counts[c["chunk_type"]] = type_counts.get(c["chunk_type"], 0) + 1

    assert "text" in type_counts
    assert "table" in type_counts, "Should have table chunks"

    # Check token budget adherence (except tables which can exceed)
    for chunk in chunks:
        if chunk["chunk_type"] != "table":
            assert chunk["token_count"] <= 600, f"Text chunk exceeds budget: {chunk['token_count']} tokens"

    # Verify Eligibility Criteria table is isolated
    eligibility_chunks = []
    for chunk in chunks:
        if chunk["chunk_type"] == "table":
            content_lower = chunk["content"].lower()
            if "eligibility" in content_lower or "criteria" in content_lower:
                eligibility_chunks.append(chunk)

    assert len(eligibility_chunks) >= 1, "Eligibility Criteria table should be isolated as table chunk(s)"

    # Verify Rate Card table is isolated
    rate_card_chunks = []
    for chunk in chunks:
        if chunk["chunk_type"] == "table":
            content_lower = chunk["content"].lower()
            if "project manager" in content_lower and "architect" in content_lower:
                rate_card_chunks.append(chunk)

    assert len(rate_card_chunks) >= 1, "Rate Card table should be isolated as table chunk(s)"

    # Verify Section 2 (Scope of Work) chunks have section_path
    section_2_chunks = []
    for chunk in chunks:
        if chunk["section_path"] and ("2.1" in chunk["section_path"] or "2.2" in chunk["section_path"] or "Scope" in chunk["section_path"]):
            section_2_chunks.append(chunk)

    assert len(section_2_chunks) >= 1, "Section 2 chunks should have section_path populated"

    logger.info(
        "chunking_integration_test_passed",
        total_chunks=len(chunks),
        type_counts=type_counts,
        eligibility_table_chunks=len(eligibility_chunks),
        rate_card_chunks=len(rate_card_chunks),
        section_2_chunks=len(section_2_chunks),
    )


@pytest.mark.integration
def test_chunking_token_counting():
    """Test token counting accuracy."""
    text = "This is a test sentence with exactly ten words here."
    count = count_tokens(text)
    # Rough check - should be around 10-15 tokens
    assert 5 < count < 30


@pytest.mark.integration
def test_chunking_empty_blocks():
    """Test handling of empty blocks."""
    blocks = [
        {"type": "text", "page": 1, "content": ""},
        {"type": "text", "page": 1, "content": "Real content"},
    ]

    chunks = create_chunks_from_blocks(blocks)
    assert len(chunks) == 1
    assert "Real content" in chunks[0]["content"]


@pytest.mark.integration
def test_chunking_page_range():
    """Test that page_start and page_end are correctly set."""
    blocks = [
        {"type": "text", "page": 1, "content": "Page 1 content"},
        {"type": "text", "page": 2, "content": "Page 2 content"},
        {"type": "text", "page": 2, "content": "More page 2 content"},
    ]

    chunks = create_chunks_from_blocks(blocks, max_tokens=1000)

    # All in one chunk since under budget
    assert len(chunks) == 1
    assert chunks[0]["page_start"] == 1
    assert chunks[0]["page_end"] == 2