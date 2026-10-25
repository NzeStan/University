"""Social services — every mutation of social data goes through here.

Each service rate-limits the actor, authorises against visibility, blocks and
permissions, validates, runs anti-spam checks, writes atomically, maintains
counters with atomic ``F()`` updates, audits moderation and publishes events.
"""

from university.social.services.comments import create_comment, delete_comment, edit_comment
from university.social.services.graph import (
    approve_follow_request,
    block_user,
    decline_follow_request,
    follow_user,
    mute_user,
    remove_follower,
    restrict_user,
    unblock_user,
    unfollow_user,
    unmute_user,
    unrestrict_user,
)
from university.social.services.media import delete_media, upload_media
from university.social.services.moderation import hide_comment, hide_post, restore_comment, restore_post
from university.social.services.polls import vote_in_poll
from university.social.services.posts import create_post, delete_post, edit_post, repost, undo_repost
from university.social.services.profiles import get_social_profile, update_social_profile
from university.social.services.reactions import (
    bookmark_post,
    react_to_comment,
    react_to_post,
    remove_bookmark,
    remove_comment_reaction,
    remove_post_reaction,
)

__all__ = [
    "approve_follow_request",
    "block_user",
    "bookmark_post",
    "create_comment",
    "create_post",
    "decline_follow_request",
    "delete_comment",
    "delete_media",
    "delete_post",
    "edit_comment",
    "edit_post",
    "follow_user",
    "get_social_profile",
    "hide_comment",
    "hide_post",
    "mute_user",
    "react_to_comment",
    "react_to_post",
    "remove_bookmark",
    "remove_comment_reaction",
    "remove_follower",
    "remove_post_reaction",
    "repost",
    "restore_comment",
    "restore_post",
    "restrict_user",
    "unblock_user",
    "undo_repost",
    "unfollow_user",
    "unmute_user",
    "unrestrict_user",
    "update_social_profile",
    "upload_media",
    "vote_in_poll",
]
