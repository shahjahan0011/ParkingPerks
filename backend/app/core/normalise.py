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
    T2 Iris payments (CSV export): plates are wrapped in Excel formula
    syntax: ="SK041H". Strip the leading =" and the trailing ", then apply
    the same typed-input cleanup as the live API path.
    """
    if not raw:
        return ""
    s = str(raw).strip().upper()
    if s.startswith('="') and s.endswith('"'):
        s = s[2:-1]
    else:
        s = s.lstrip('="').rstrip('"')
    return _strip_typed_input_noise(s)


def normalise_iris_plate(raw: str | None) -> str:
    """
    T2 Iris payments (live SOAP API): plates are typed by drivers at pay
    stations / phone apps, so the same physical plate the camera reads as
    "AB123C" may arrive as "ab 123c" or "AB-123C". Uppercase, trim, and
    remove internal spaces/hyphens so typed input matches camera reads.

    NOTE: this does NOT strip province codes -- that rule applies only to
    the citations format (see the SK041H bug).
    """
    if not raw:
        return ""
    return _strip_typed_input_noise(str(raw).strip().upper())


def _strip_typed_input_noise(s: str) -> str:
    """Remove characters drivers type but cameras never emit."""
    return s.replace(" ", "").replace("-", "").replace(".", "")


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
