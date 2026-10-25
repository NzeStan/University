"""Event names published by moderation.

Payloads contain ids only. For anonymous content, ``target_user_id`` is never
included — consumers must not be able to link author and content.
"""

REPORT_CREATED = "moderation.report.created"
CASE_OPENED = "moderation.case.opened"
ACTION_TAKEN = "moderation.action.taken"
ACTION_REVERSED = "moderation.action.reversed"
APPEAL_FILED = "moderation.appeal.filed"
APPEAL_DECIDED = "moderation.appeal.decided"
