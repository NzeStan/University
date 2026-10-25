"""Settings for the institution module (``UNIVERSITY["INSTITUTION"]``).

Nothing here assumes a particular country: institution types, academic unit
types, membership roles, qualification levels and verification methods are
all data, configured per deployment.
"""

from __future__ import annotations

from typing import Any

from university.core.conf import ModuleSettings

DEFAULTS: dict[str, Any] = {
    # Seeded into InstitutionType on migrate (editable afterwards in admin).
    "INSTITUTION_TYPES": [
        {"key": "university", "name": "University"},
        {"key": "polytechnic", "name": "Polytechnic"},
        {"key": "college_of_education", "name": "College of Education"},
        {"key": "monotechnic", "name": "Monotechnic"},
        {"key": "health_institution", "name": "College of Health / Nursing / Midwifery"},
        {"key": "vocational", "name": "Vocational / Technical Institution"},
        {"key": "other", "name": "Other higher institution"},
    ],
    "OWNERSHIP_TYPES": ["public", "private", "faith_based", "community", "other"],
    # Academic units form a tree whose levels differ between institutions.
    "ACADEMIC_UNIT_TYPES": ["college", "faculty", "school", "department", "institute", "centre", "unit"],
    "QUALIFICATION_LEVELS": [
        "certificate",
        "diploma",
        "national_diploma",
        "higher_national_diploma",
        "nce",
        "bachelor",
        "postgraduate_diploma",
        "master",
        "doctorate",
        "other",
    ],
    "STUDY_MODES": ["full_time", "part_time", "distance", "sandwich", "online"],
    "MEMBERSHIP_ROLES": [
        "student",
        "staff",
        "lecturer",
        "administrator",
        "alumni",
        "guest",
        "moderator",
        "organization",
    ],
    # Roles verified automatically on joining (no proof required).
    "AUTO_VERIFY_ROLES": ["guest"],
    "ALLOW_MULTIPLE_INSTITUTIONS": True,
    "MAX_ACTIVE_MEMBERSHIPS_PER_USER": 5,
    # Available verification providers, by key.
    "VERIFICATION_PROVIDERS": {
        "institution_email": "university.institution.verification.providers.InstitutionEmailProvider",
        "student_id": "university.institution.verification.providers.IdentifierReviewProvider",
        "document": "university.institution.verification.providers.DocumentReviewProvider",
        "manual": "university.institution.verification.providers.ManualReviewProvider",
    },
    # Methods offered when an institution does not list its own.
    "DEFAULT_VERIFICATION_METHODS": ["institution_email", "manual"],
    "DOCUMENT_MAX_BYTES": 5 * 1024 * 1024,
    "DOCUMENT_MIME_TYPES": ["application/pdf", "image/jpeg", "image/png"],
    # Days after a decision before uploaded verification documents are deleted.
    "VERIFICATION_DOCUMENT_RETENTION_DAYS": 90,
    "VERIFICATION_REQUEST_TTL_DAYS": 30,
}

institution_settings = ModuleSettings("INSTITUTION", DEFAULTS)
