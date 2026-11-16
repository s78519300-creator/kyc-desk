"""Indian name handling: normalisation and the "same person" test from the KYC policy.

The policy (section 2.3) accepts these differences between two spellings of one name:
case, dots and spacing; initials for any part except the surname; the listed
abbreviations (Mohd/Md = Mohammed, Kr = Kumar, Pd = Prasad, ...); a missing middle
name; and a different order of the parts. A different first name or surname, or a
missing first name or surname, is a different person.
"""

from __future__ import annotations

import re
from typing import List

ABBREVIATIONS = {
    "MOHD": "MOHAMMED", "MD": "MOHAMMED", "MOHAMMAD": "MOHAMMED", "MUHAMMAD": "MOHAMMED",
    "KR": "KUMAR", "PD": "PRASAD", "PRASADH": "PRASAD", "SK": "SHAIKH", "SHEIKH": "SHAIKH",
    "LAKSHMI": "LAXMI", "LAKSMI": "LAXMI", "CH": "CHANDRA", "CHANDER": "CHANDRA",
}


def tokens(name: str) -> List[str]:
    parts = re.split(r"[\s.]+", name.upper().strip())
    return [ABBREVIATIONS.get(p, p) for p in parts if p]


def _matches(a: str, b: str) -> bool:
    if a == b:
        return True
    return (len(a) == 1 and b.startswith(a)) or (len(b) == 1 and a.startswith(b))


def same_person(name_a: str, name_b: str) -> bool:
    """True when two spellings fall within the accepted variations of policy 2.3."""
    ta, tb = tokens(name_a), tokens(name_b)
    if not ta or not tb:
        return False
    short, long = (ta, tb) if len(ta) <= len(tb) else (tb, ta)
    if len(long) - len(short) > 1:
        return False
    used = [False] * len(long)
    full_matches = 0
    for t in short:
        # prefer an exact match, then an initial
        idx = next((i for i, u in enumerate(long) if not used[i] and u == t), None)
        if idx is None:
            idx = next((i for i, u in enumerate(long) if not used[i] and _matches(t, u)), None)
        if idx is None:
            return False
        used[idx] = True
        if len(t) > 1 and len(long[idx]) > 1:
            full_matches += 1
    # only a middle name may be missing: the unmatched part cannot be the first or last one
    unmatched = [i for i, u in enumerate(used) if not u]
    if unmatched and unmatched[0] in (0, len(long) - 1):
        return False
    return full_matches >= 1


def similarity(name_a: str, name_b: str) -> float:
    """A screening score in [0, 1]: token overlap that also credits initials."""
    ta, tb = tokens(name_a), tokens(name_b)
    if not ta or not tb:
        return 0.0
    hits = 0.0
    used = [False] * len(tb)
    for t in ta:
        for i, u in enumerate(tb):
            if not used[i] and t == u:
                used[i] = True
                hits += 1
                break
        else:
            for i, u in enumerate(tb):
                if not used[i] and _matches(t, u):
                    used[i] = True
                    hits += 0.5
                    break
    return round(2 * hits / (len(ta) + len(tb)), 3)
