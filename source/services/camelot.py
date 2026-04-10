import re

CAMELOT_RE = re.compile(r'^(\d{1,2})([AB])$')


def parse_camelot(key: str):
    """Parse '4A' into (4, 'A'). Returns None if invalid."""
    if not key:
        return None
    m = CAMELOT_RE.match(key.strip())
    if not m:
        return None
    num = int(m.group(1))
    if num < 1 or num > 12:
        return None
    return (num, m.group(2))


def is_compatible(key1: str, key2: str) -> bool:
    """Check if two Camelot keys are harmonically compatible."""
    p1 = parse_camelot(key1)
    p2 = parse_camelot(key2)
    if not p1 or not p2:
        return False
    n1, l1 = p1
    n2, l2 = p2
    if n1 == n2:
        return True  # Same number (identical or A/B flip)
    if l1 == l2:
        # Adjacent numbers, wrapping 12<->1
        diff = abs(n1 - n2)
        return diff == 1 or diff == 11
    return False


def compatibility_score(key1: str, key2: str) -> float:
    """Score the harmonic compatibility between two Camelot keys.

    Returns:
        1.0 = identical key
        0.8 = adjacent number, same letter
        0.7 = same number, A/B flip
        0.0 = incompatible
    """
    p1 = parse_camelot(key1)
    p2 = parse_camelot(key2)
    if not p1 or not p2:
        return 0.0
    n1, l1 = p1
    n2, l2 = p2
    if n1 == n2 and l1 == l2:
        return 1.0
    if n1 == n2 and l1 != l2:
        return 0.7
    if l1 == l2:
        diff = abs(n1 - n2)
        if diff == 1 or diff == 11:
            return 0.8
    return 0.0
