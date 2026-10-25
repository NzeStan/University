"""Event names published by the social module.

Payloads contain identifiers only. Consumers (notifications, analytics,
search, trending) subscribe to these; social never imports them.
"""

POST_CREATED = "social.post.created"
POST_UPDATED = "social.post.updated"
POST_DELETED = "social.post.deleted"
POST_REPOSTED = "social.post.reposted"
POST_REACTED = "social.post.reacted"
POST_HIDDEN = "social.post.hidden"
POST_RESTORED = "social.post.restored"
COMMENT_CREATED = "social.comment.created"
COMMENT_DELETED = "social.comment.deleted"
COMMENT_REACTED = "social.comment.reacted"
COMMENT_HIDDEN = "social.comment.hidden"
MENTION_CREATED = "social.mention.created"
FOLLOW_CREATED = "social.follow.created"
FOLLOW_REQUESTED = "social.follow.requested"
FOLLOW_APPROVED = "social.follow.approved"
FOLLOW_REMOVED = "social.follow.removed"
BLOCK_CREATED = "social.block.created"
POLL_VOTED = "social.poll.voted"
