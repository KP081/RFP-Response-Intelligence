"""Versioned prompt templates for LLM tasks.

Each prompt is a named, versioned function that returns the system instructions
and user task template. Prompts are referenced by name+version in llm_calls
for traceability against the evaluation harness.
"""

from app.llm.gateway import build_messages


def get_prompt(name: str, version: str = "v1") -> dict[str, str]:
    """Get a prompt template by name and version.

    Args:
        name: Prompt name (e.g., "requirement_extraction").
        version: Prompt version (e.g., "v1", "v2").

    Returns:
        Dict with 'system_instructions' and 'user_task_template' keys.

    Raises:
        ValueError: If prompt not found.
    """
    prompts = {
        "requirement_extraction": {
            "v1": _requirement_extraction_v1,
        },
        "smoke_test": {
            "v1": _smoke_test_v1,
        },
    }

    if name not in prompts:
        raise ValueError(f"Unknown prompt: {name}")
    if version not in prompts[name]:
        raise ValueError(f"Unknown version {version} for prompt {name}")

    return prompts[name][version]()


def _requirement_extraction_v1() -> dict[str, str]:
    """Requirement extraction prompt v1."""
    return {
        "system_instructions": (
            "You are an expert RFP analyst. Your task is to extract "
            "all requirements, obligations, and constraints from the "
            "provided document content. Return structured output only."
        ),
        "user_task_template": (
            "Extract all requirements from the document. Each requirement "
            "should include: a unique ID, the requirement text, category "
            "(functional, non-functional, compliance, commercial), "
            "priority (must, should, could), and any referenced section numbers."
        ),
    }


def _smoke_test_v1() -> dict[str, str]:
    """Simple smoke test prompt for gateway verification."""
    return {
        "system_instructions": "You are a helpful assistant. Return a JSON object with a single field 'status' set to 'ok'.",
        "user_task_template": "Return the status object.",
    }


def render_prompt(
    name: str,
    version: str,
    document_content: str,
    **kwargs: str,
) -> list[dict[str, str]]:
    """Render a prompt template with document content and additional variables.

    This is the MANDATORY way to build messages for any prompt that includes
    ingested document content. It uses build_messages() to enforce prompt-injection
    safety by isolating untrusted document content from system instructions.

    Args:
        name: Prompt name.
        version: Prompt version.
        document_content: The untrusted document content to analyze.
        **kwargs: Additional variables for the user_task_template.

    Returns:
        List of message dicts ready for the LLM API.
    """
    prompt = get_prompt(name, version)
    user_task = prompt["user_task_template"].format(**kwargs)
    return build_messages(
        system_instructions=prompt["system_instructions"],
        untrusted_document_content=document_content,
        user_task=user_task,
    )


def get_prompt_version(name: str, version: str) -> str:
    """Get a string identifier for the prompt version for logging."""
    return f"{name}@{version}"