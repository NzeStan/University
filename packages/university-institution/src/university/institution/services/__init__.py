"""Institution services: every mutation is authorised, audited and evented here."""

from university.institution.services.institutions import (
    add_domain,
    create_institution,
    remove_domain,
    sync_institution_types,
    update_institution,
)
from university.institution.services.memberships import (
    complete_verification,
    leave_membership,
    request_membership,
    review_membership,
    revoke_membership,
    set_primary_membership,
    start_verification,
    suspend_membership,
    update_membership_details,
)
from university.institution.services.structure import (
    create_academic_unit,
    create_campus,
    create_level,
    create_programme,
    create_semester,
    create_session,
    set_current_session,
    update_structure,
)

__all__ = [
    "add_domain",
    "complete_verification",
    "create_academic_unit",
    "create_campus",
    "create_institution",
    "create_level",
    "create_programme",
    "create_semester",
    "create_session",
    "leave_membership",
    "remove_domain",
    "request_membership",
    "review_membership",
    "revoke_membership",
    "set_current_session",
    "set_primary_membership",
    "start_verification",
    "suspend_membership",
    "sync_institution_types",
    "update_institution",
    "update_membership_details",
    "update_structure",
]
