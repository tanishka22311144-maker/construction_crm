"""Identity and phone number normalization service for WhatsApp sender identification.

PROJECT_SPEC.md §2 requires:
whatsapp_sender_hash = sha256 of the WhatsApp number; this IS the identity.

Meta Cloud API sends messages[0].from as an international number without '+'
(e.g., '918698510857'). This module ensures identical canonicalization whether
numbers are ingested from webhooks or seeded administratively.
"""
import hashlib
import re


def canonicalize_whatsapp_number(raw: str) -> str:
    """Normalize a raw phone number or WhatsApp ID to canonical E.164 digits-only format.

    - Strips leading '+', spaces, hyphens, and any non-digit characters.
    - If a 10-digit Indian mobile number is provided (starts with 6, 7, 8, 9),
      prepends country code '91' to match Meta's standard payload representation.
    """
    if not raw:
        return ""

    digits = re.sub(r"\D", "", str(raw).strip())
    if not digits:
        return ""

    # Common case: 10-digit Indian national mobile number
    if len(digits) == 10 and digits[0] in "6789":
        digits = f"91{digits}"

    return digits


def hash_whatsapp_number(raw: str) -> str:
    """Compute the SHA-256 identity hash for a WhatsApp phone number.

    Always normalizes the number first to guarantee identical hashing across
    webhook ingestion and user seeding.
    """
    canonical = canonicalize_whatsapp_number(raw)
    if not canonical:
        return ""
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()
