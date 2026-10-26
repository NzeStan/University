"""University Podcast — shows, seasons, episodes, hosts, guests, transcripts, clips and RSS.

An optional *level two* module that depends only on University Core::

    pip install university-podcast university-media

    INSTALLED_APPS = [..., *CORE_APPS, "university.media", "university.podcast"]

Audio and video live in Core's media library (provided by university-media),
referenced by id: processing is asynchronous and this module never imports
the media module.
"""

__version__ = "0.1.1"
