"""Events published by the anonymous module.

Payloads NEVER include an author or user id — not even for internal
consumers — so no downstream store (analytics, notifications, search) can
accumulate an index of who wrote what.
"""

POST_CREATED = "anonymous.post.created"
POST_DELETED = "anonymous.post.deleted"
COMMENT_CREATED = "anonymous.comment.created"
COMMENT_DELETED = "anonymous.comment.deleted"
#: {"message_id", "recipient_id"}: the recipient is known (it's their inbox); the sender never is.
MESSAGE_RECEIVED = "anonymous.message.received"
#: {"message_id", "recipient_id"} when an answer is made public.
MESSAGE_ANSWERED = "anonymous.message.answered"
