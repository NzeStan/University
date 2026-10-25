"""Append-only, tamper-evident audit logging for security-sensitive actions.

Public API::

    from university.audit.services import record
    from university.audit.actions import AuditAction

    record(AuditAction.LOGIN_SUCCEEDED, actor=user, target=session)
"""
