"""University Anonymous — anonymous posts and comments with accountability.

Anonymous means *unlinkable to the public, accountable to the platform*:

* nobody — other users, moderators, events, exports — learns who wrote what;
* authorship is never stored in plaintext: ownership is checked with a
  per-item keyed hash, and the identity is kept only encrypted;
* revealing an author requires a sensitive permission, a written
  justification, approval by a second person, and is audited at every step;
* abuse controls are mandatory (moderation module, rate limits, spam
  screening, account-age and verification gates, sanctions).

Install alongside the moderation module::

    pip install university-anonymous university-moderation
"""

__version__ = "0.1.0"
