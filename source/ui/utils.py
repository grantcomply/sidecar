def truncate(text: str, max_len: int) -> str:
    """Truncate text to max_len, adding ellipsis if needed."""
    return text if len(text) <= max_len else text[:max_len - 1] + "\u2026"
