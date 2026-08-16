"""Pydantic schemas for structured LLM output."""

from typing import Optional

from pydantic import BaseModel, Field


class RequirementExtractionResult(BaseModel):
    """Schema for requirement extraction structured output."""

    requirements: list["RequirementItem"] = Field(default_factory=list)


class RequirementItem(BaseModel):
    """Individual requirement item."""

    id: str = Field(..., description="Unique identifier for the requirement")
    text: str = Field(..., description="The requirement text")
    category: str = Field(
        ..., description="Category: functional, non-functional, compliance, commercial"
    )
    priority: str = Field(..., description="Priority: must, should, could")
    section_ref: Optional[str] = Field(None, description="Referenced section number")


class SmokeTestResult(BaseModel):
    """Schema for smoke test structured output."""

    status: str = Field(..., description="Status indicator")