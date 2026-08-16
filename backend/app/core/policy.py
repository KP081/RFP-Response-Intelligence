"""Confidentiality policy hooks.

This module provides integration points for export/sharing policy enforcement.
Task 41 (security hardening) will implement real logic here.
"""

from app.db.models import Document


def can_export(document: Document) -> bool:
    """Check if a document can be exported/shared.

    This is a stub that always returns True. Task 41 will implement
    real confidentiality logic here (e.g., checking a confidential flag).

    Args:
        document: The document to check export permission for.

    Returns:
        True if export is allowed, False otherwise.
    """
    # TODO(task-41): Implement real confidentiality policy
    # Example: return not document.is_confidential
    return True