"""Social data model.

Content::

    Post ──┬── PostMedia, Poll ── PollOption ── PollVote
           ├── PostReaction, Bookmark, PostMention, PostHashtag ── Hashtag
           ├── PostRevision (edit history, for accountability)
           ├── repost_of → Post        (pure repost: empty body; quote: with body)
           └── Comment (2-level threads) ── CommentReaction, CommentMention

Graph::

    SocialProfile (bio, counters, follow approval, mention policy)
    Follow (active | pending) · Block · Mute · Restrict

Design notes:

* Explicit relations everywhere — no generic foreign keys — so integrity and
  indexes stay first-class.
* Uniqueness that guards against duplicates under concurrency (one reaction
  per user, one follow, one vote …) is enforced by database constraints.
* Counters are denormalised and updated with atomic ``F()`` expressions.
* Audience-restricted posts carry ``scope_type``/``scope_id``; membership is
  resolved through Core's ``scopes.memberships`` hook, never by joining
  another module's tables.
"""

from __future__ import annotations

from django.conf import settings
from django.db import models
from django.db.models import F, Q
from django.utils.translation import gettext_lazy as _

from university.core.models import BaseModel, SoftDeleteModel
from university.core.uploads import uuid_upload_to
from university.social.constants import ContentStatus, FollowStatus, MentionPolicy, Visibility

USER = settings.AUTH_USER_MODEL


class SocialProfile(BaseModel):
    user = models.OneToOneField(USER, on_delete=models.CASCADE, related_name="social_profile")
    bio = models.CharField(max_length=300, blank=True)
    website = models.URLField(blank=True)
    #: "Protected" account: new followers need approval.
    requires_follow_approval = models.BooleanField(default=False)
    allow_mentions_from = models.CharField(max_length=16, choices=MentionPolicy.choices, default=MentionPolicy.EVERYONE)
    default_post_visibility = models.CharField(max_length=16, choices=Visibility.choices, default=Visibility.PUBLIC)
    followers_count = models.PositiveIntegerField(default=0)
    following_count = models.PositiveIntegerField(default=0)
    posts_count = models.PositiveIntegerField(default=0)

    class Meta:
        verbose_name = _("social profile")

    def __str__(self) -> str:
        return f"Social profile of {self.user_id}"


class Hashtag(BaseModel):
    name = models.CharField(max_length=64, unique=True)
    posts_count = models.PositiveIntegerField(default=0)

    class Meta:
        verbose_name = _("hashtag")

    def __str__(self) -> str:
        return f"#{self.name}"


class Post(BaseModel, SoftDeleteModel):
    author = models.ForeignKey(USER, on_delete=models.CASCADE, related_name="social_posts")
    body = models.TextField(blank=True)
    visibility = models.CharField(max_length=16, choices=Visibility.choices, default=Visibility.PUBLIC)
    scope_type = models.CharField(max_length=32, blank=True)
    scope_id = models.CharField(max_length=64, blank=True)
    repost_of = models.ForeignKey("self", null=True, blank=True, on_delete=models.SET_NULL, related_name="reposts")
    status = models.CharField(max_length=16, choices=ContentStatus.choices, default=ContentStatus.PUBLISHED)
    moderation_reason = models.CharField(max_length=255, blank=True)
    links = models.JSONField(default=list, blank=True)
    location = models.CharField(max_length=100, blank=True)
    comments_enabled = models.BooleanField(default=True)
    edited_at = models.DateTimeField(null=True, blank=True)
    reaction_count = models.PositiveIntegerField(default=0)
    comment_count = models.PositiveIntegerField(default=0)
    repost_count = models.PositiveIntegerField(default=0)
    hashtags = models.ManyToManyField(Hashtag, through="PostHashtag", related_name="posts")

    class Meta:
        verbose_name = _("post")
        indexes = [
            models.Index(fields=["author", "-created_at"], name="univ_soc_post_author"),
            models.Index(fields=["visibility", "status", "-created_at"], name="univ_soc_post_visibility"),
            models.Index(fields=["scope_type", "scope_id", "-created_at"], name="univ_soc_post_scope"),
            models.Index(fields=["repost_of"], name="univ_soc_post_repost_of"),
        ]
        constraints = [
            # One pure repost per user per original.
            models.UniqueConstraint(
                fields=["author", "repost_of"],
                condition=Q(repost_of__isnull=False) & Q(body="") & Q(deleted_at__isnull=True),
                name="univ_soc_post_one_repost",
            ),
            models.CheckConstraint(
                condition=(Q(scope_type="") & Q(scope_id="")) | (~Q(scope_type="") & ~Q(scope_id="")),
                name="univ_soc_post_scope_consistent",
            ),
        ]

    def __str__(self) -> str:
        return f"Post {self.pk}"

    @property
    def is_pure_repost(self) -> bool:
        return self.repost_of_id is not None and not self.body


class PostRevision(BaseModel):
    """Previous body of an edited post (kept for moderation accountability)."""

    post = models.ForeignKey(Post, on_delete=models.CASCADE, related_name="revisions")
    body = models.TextField(blank=True)

    class Meta:
        verbose_name = _("post revision")
        ordering = ("-created_at",)

    def __str__(self) -> str:
        return f"Revision of {self.post_id}"


class PostHashtag(models.Model):
    post = models.ForeignKey(Post, on_delete=models.CASCADE)
    hashtag = models.ForeignKey(Hashtag, on_delete=models.CASCADE)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["post", "hashtag"], name="univ_soc_post_hashtag_unique")]
        indexes = [models.Index(fields=["hashtag", "post"], name="univ_soc_hashtag_posts")]

    def __str__(self) -> str:
        return f"{self.post_id} #{self.hashtag_id}"


class PostMention(BaseModel):
    post = models.ForeignKey(Post, on_delete=models.CASCADE, related_name="mentions")
    user = models.ForeignKey(USER, on_delete=models.CASCADE, related_name="social_post_mentions")

    class Meta:
        constraints = [models.UniqueConstraint(fields=["post", "user"], name="univ_soc_post_mention_unique")]

    def __str__(self) -> str:
        return f"@{self.user_id} in {self.post_id}"


class PostMedia(BaseModel):
    """An uploaded image. Owned by its uploader until attached to a post."""

    owner = models.ForeignKey(USER, on_delete=models.CASCADE, related_name="social_media")
    post = models.ForeignKey(Post, null=True, blank=True, on_delete=models.CASCADE, related_name="media")
    file = models.FileField(upload_to=uuid_upload_to("social/media"), max_length=255)
    mime_type = models.CharField(max_length=64)
    size = models.PositiveIntegerField(default=0)
    width = models.PositiveIntegerField(null=True, blank=True)
    height = models.PositiveIntegerField(null=True, blank=True)
    alt_text = models.CharField(max_length=500, blank=True)
    position = models.PositiveSmallIntegerField(default=0)

    class Meta:
        verbose_name = _("post media")
        verbose_name_plural = _("post media")
        ordering = ("position", "created_at")
        indexes = [models.Index(fields=["owner", "post"], name="univ_soc_media_owner")]

    def __str__(self) -> str:
        return f"Media {self.pk}"


class Poll(BaseModel):
    post = models.OneToOneField(Post, on_delete=models.CASCADE, related_name="poll")
    allows_multiple = models.BooleanField(default=False)
    closes_at = models.DateTimeField(null=True, blank=True)
    total_votes = models.PositiveIntegerField(default=0)

    class Meta:
        verbose_name = _("poll")

    def __str__(self) -> str:
        return f"Poll on {self.post_id}"


class PollOption(BaseModel):
    poll = models.ForeignKey(Poll, on_delete=models.CASCADE, related_name="options")
    text = models.CharField(max_length=100)
    position = models.PositiveSmallIntegerField(default=0)
    vote_count = models.PositiveIntegerField(default=0)

    class Meta:
        verbose_name = _("poll option")
        ordering = ("position",)
        constraints = [models.UniqueConstraint(fields=["poll", "position"], name="univ_soc_poll_option_position")]

    def __str__(self) -> str:
        return self.text


class PollVote(BaseModel):
    poll = models.ForeignKey(Poll, on_delete=models.CASCADE, related_name="votes")
    option = models.ForeignKey(PollOption, on_delete=models.CASCADE, related_name="votes")
    user = models.ForeignKey(USER, on_delete=models.CASCADE, related_name="social_poll_votes")
    #: Copied from the poll so single-choice uniqueness can be a DB constraint.
    single_choice = models.BooleanField(default=True)

    class Meta:
        verbose_name = _("poll vote")
        constraints = [
            models.UniqueConstraint(fields=["option", "user"], name="univ_soc_poll_vote_option_unique"),
            models.UniqueConstraint(
                fields=["poll", "user"], condition=Q(single_choice=True), name="univ_soc_poll_vote_single"
            ),
        ]

    def __str__(self) -> str:
        return f"Vote by {self.user_id}"


class PostReaction(BaseModel):
    post = models.ForeignKey(Post, on_delete=models.CASCADE, related_name="reactions")
    user = models.ForeignKey(USER, on_delete=models.CASCADE, related_name="social_post_reactions")
    kind = models.CharField(max_length=16)

    class Meta:
        verbose_name = _("post reaction")
        constraints = [models.UniqueConstraint(fields=["post", "user"], name="univ_soc_post_reaction_unique")]
        indexes = [models.Index(fields=["user", "-created_at"], name="univ_soc_post_reaction_user")]

    def __str__(self) -> str:
        return f"{self.kind} by {self.user_id}"


class Bookmark(BaseModel):
    post = models.ForeignKey(Post, on_delete=models.CASCADE, related_name="bookmarks")
    user = models.ForeignKey(USER, on_delete=models.CASCADE, related_name="social_bookmarks")

    class Meta:
        verbose_name = _("bookmark")
        constraints = [models.UniqueConstraint(fields=["post", "user"], name="univ_soc_bookmark_unique")]
        indexes = [models.Index(fields=["user", "-created_at"], name="univ_soc_bookmark_user")]

    def __str__(self) -> str:
        return f"Bookmark {self.pk}"


class Comment(BaseModel, SoftDeleteModel):
    post = models.ForeignKey(Post, on_delete=models.CASCADE, related_name="comments")
    author = models.ForeignKey(USER, on_delete=models.CASCADE, related_name="social_comments")
    #: Replies are flattened to two levels: parent is always a top-level comment.
    parent = models.ForeignKey("self", null=True, blank=True, on_delete=models.CASCADE, related_name="replies")
    body = models.TextField()
    status = models.CharField(max_length=16, choices=ContentStatus.choices, default=ContentStatus.PUBLISHED)
    moderation_reason = models.CharField(max_length=255, blank=True)
    edited_at = models.DateTimeField(null=True, blank=True)
    reaction_count = models.PositiveIntegerField(default=0)
    reply_count = models.PositiveIntegerField(default=0)

    class Meta:
        verbose_name = _("comment")
        indexes = [
            models.Index(fields=["post", "parent", "created_at"], name="univ_soc_comment_thread"),
            models.Index(fields=["author", "-created_at"], name="univ_soc_comment_author"),
        ]

    def __str__(self) -> str:
        return f"Comment {self.pk}"


class CommentReaction(BaseModel):
    comment = models.ForeignKey(Comment, on_delete=models.CASCADE, related_name="reactions")
    user = models.ForeignKey(USER, on_delete=models.CASCADE, related_name="social_comment_reactions")
    kind = models.CharField(max_length=16)

    class Meta:
        verbose_name = _("comment reaction")
        constraints = [models.UniqueConstraint(fields=["comment", "user"], name="univ_soc_comment_reaction_unique")]

    def __str__(self) -> str:
        return f"{self.kind} by {self.user_id}"


class CommentMention(BaseModel):
    comment = models.ForeignKey(Comment, on_delete=models.CASCADE, related_name="mentions")
    user = models.ForeignKey(USER, on_delete=models.CASCADE, related_name="social_comment_mentions")

    class Meta:
        constraints = [models.UniqueConstraint(fields=["comment", "user"], name="univ_soc_comment_mention_unique")]

    def __str__(self) -> str:
        return f"@{self.user_id} in comment {self.comment_id}"


# ------------------------------------------------------------------ graph
class Follow(BaseModel):
    follower = models.ForeignKey(USER, on_delete=models.CASCADE, related_name="social_following")
    followee = models.ForeignKey(USER, on_delete=models.CASCADE, related_name="social_followers")
    status = models.CharField(max_length=16, choices=FollowStatus.choices, default=FollowStatus.ACTIVE)

    class Meta:
        verbose_name = _("follow")
        constraints = [
            models.UniqueConstraint(fields=["follower", "followee"], name="univ_soc_follow_unique"),
            models.CheckConstraint(condition=~Q(follower=F("followee")), name="univ_soc_follow_not_self"),
        ]
        indexes = [
            models.Index(fields=["followee", "status", "-created_at"], name="univ_soc_follow_followee"),
            models.Index(fields=["follower", "status", "-created_at"], name="univ_soc_follow_follower"),
        ]

    def __str__(self) -> str:
        return f"{self.follower_id} → {self.followee_id} ({self.status})"


class Block(BaseModel):
    blocker = models.ForeignKey(USER, on_delete=models.CASCADE, related_name="social_blocking")
    blocked = models.ForeignKey(USER, on_delete=models.CASCADE, related_name="social_blocked_by")

    class Meta:
        verbose_name = _("block")
        constraints = [
            models.UniqueConstraint(fields=["blocker", "blocked"], name="univ_soc_block_unique"),
            models.CheckConstraint(condition=~Q(blocker=F("blocked")), name="univ_soc_block_not_self"),
        ]
        indexes = [models.Index(fields=["blocked", "blocker"], name="univ_soc_block_reverse")]

    def __str__(self) -> str:
        return f"{self.blocker_id} blocks {self.blocked_id}"


class Mute(BaseModel):
    muter = models.ForeignKey(USER, on_delete=models.CASCADE, related_name="social_muting")
    muted = models.ForeignKey(USER, on_delete=models.CASCADE, related_name="social_muted_by")

    class Meta:
        verbose_name = _("mute")
        constraints = [
            models.UniqueConstraint(fields=["muter", "muted"], name="univ_soc_mute_unique"),
            models.CheckConstraint(condition=~Q(muter=F("muted")), name="univ_soc_mute_not_self"),
        ]

    def __str__(self) -> str:
        return f"{self.muter_id} mutes {self.muted_id}"


class Restrict(BaseModel):
    """The restricted user's comments on the restrictor's posts are visible
    only to the two of them, without the restricted user being told."""

    restrictor = models.ForeignKey(USER, on_delete=models.CASCADE, related_name="social_restricting")
    restricted = models.ForeignKey(USER, on_delete=models.CASCADE, related_name="social_restricted_by")

    class Meta:
        verbose_name = _("restriction")
        constraints = [
            models.UniqueConstraint(fields=["restrictor", "restricted"], name="univ_soc_restrict_unique"),
            models.CheckConstraint(condition=~Q(restrictor=F("restricted")), name="univ_soc_restrict_not_self"),
        ]

    def __str__(self) -> str:
        return f"{self.restrictor_id} restricts {self.restricted_id}"
