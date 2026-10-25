# university-podcast

Podcasts for the [University platform](https://github.com/NzeStan/University): shows,
seasons, episodes, hosts, guests, audio and video, transcripts, clips, RSS and listening analytics.
This is an optional *level two* module that depends only on `university-core`. Media goes through
Core's media library, normally provided by `university-media`.

- **Shows** can be hosted by a person or by a scope (such as a campus radio station or a
  community), and can be limited to members. Owners, hosts and producers have ranked roles.
- **Episodes** are published only once their media has finished processing. Episodes can be
  scheduled, and subscribers are notified.
- **Guests** can be linked to accounts, which appear publicly only after the guest confirms.
- **Transcripts:** WebVTT or SRT upload (sanitised), VTT export, and optional automatic
  transcription behind a provider protocol.
- **Clips** are cut asynchronously.
- **RSS feeds** use the iTunes and Podcasting 2.0 tags, with stable enclosure links that redirect
  to fresh signed URLs.
- **Listening analytics** are daily aggregates only, de-duplicated without storing listeners.
- **Moderation:** shows and episodes can be reported, and reports go to the host scope's
  moderators.

```bash
pip install university-podcast university-media
```

See [the module documentation](../../docs/modules/podcast.md).
