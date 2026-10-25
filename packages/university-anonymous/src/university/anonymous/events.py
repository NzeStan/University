"""Events published by the anonymous module.

Payloads NEVER include an author or user id — not even for internal
consumers — so no downstream store (analytics, notifications, search) can
accumulate an index of who wrote what.
"""

POST_CREATED = "anonymous.post.created"
POST_DELETED = "anonymous.post.deleted"
COMMENT_CREATED = "anonymous.comment.created"
COMMENT_DELETED = "anonymous.comment.deleted"
