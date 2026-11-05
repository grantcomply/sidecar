def truncate(text: str, max_len: int) -> str:
    """Truncate text to max_len, adding ellipsis if needed."""
    return text if len(text) <= max_len else text[:max_len - 1] + "\u2026"


_LABEL_SEPARATORS = (" / ", " - ")


def truncate_start(text: str, max_len: int) -> str:
    """Truncate from the START, keeping the end (the leaf name tells rows apart).

    Cuts at a folder separator where possible:
    ``"My Sets / LiveSets / 02. CrumbsAndCream"`` → ``"… / LiveSets / 02. CrumbsAndCream"``.
    """
    if len(text) <= max_len:
        return text
    tail = text[-(max_len - 1):]
    cuts = [i for sep in _LABEL_SEPARATORS if (i := tail.find(sep)) >= 0]
    return "\u2026" + (tail[min(cuts):] if cuts else tail)
