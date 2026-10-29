"""University Media — secure uploads, object storage, asynchronous processing and signed URLs.

An optional *level two* module that depends only on University Core::

    pip install university-media

    INSTALLED_APPS = [..., *CORE_APPS, "university.media"]

It provides Core's media library (:mod:`university.core.media`), so other
modules (podcasts, posts, listings …) store and stream audio, video, images
and documents through media ids without importing this module.
"""

__version__ = "0.1.1"
