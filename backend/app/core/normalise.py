"""
Plate normalisation — one function per data source.

Each parking system stores licence plates in a different format.
Never collapse these into one shared function — the SK041H bug
(see CLAUDE.md) was caused by a shared normaliser stripping "SK"
from plates that genuinely start with SK.
"""


def normalise_reads_plate(raw: str | None) -> str:
    """Genetec plate reads: plates are already clean — uppercase + trim only."""
    if not raw:
        return ""
    return str(raw).strip().upper()


def normalise_payments_plate(raw: str | None) -> str:
    """
    T2 Iris payments: plates are wrapped in Excel formula syntax: ="SK041H"
    Strip the leading =" and the trailing " — nothing else.
    """
    if not raw:
        return ""
    s = str(raw).strip().upper()
    if s.startswith('="') and s.endswith('"'):
        return s[2:-1]
    return s.lstrip('="').rstrip('"')


def normalise_citations_plate(raw: str | None) -> str:
    """
    T2 Flex citations: format is PROVINCE-PLATE-SUFFIX (e.g. BC-SK041H-NA).
    Always extract the middle segment(s).

    Edge cases:
      "LICENSE #"      — repeated header row from exporter, return ""
      "BC-  -NA"       — blank plate, return ""
      "BC-XE115F-BIKE" — non-NA suffix, still takes middle segment
      "BC-SK-041H-NA"  — 4 parts, joins middle segments → SK041H
    """
    if not raw:
        return ""

    s = str(raw).strip().upper()

    if not s or s == "LICENSE #":
        return ""

    parts = [p.strip() for p in s.split("-")]

    if len(parts) == 3:
        return parts[1]

    if len(parts) > 3:
        return "".join(parts[1:-1])

    if len(parts) == 1:
        return parts[0]

    return ""


def normalise_permits_plate(raw: str | None) -> str:
    """T2 Flex permit holders: same format as plate reads — uppercase + trim."""
    return normalise_reads_plate(raw)
