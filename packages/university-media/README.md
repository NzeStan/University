# university-media

Secure media for the [University platform](https://github.com/NzeStan/University):
uploads, private object storage, asynchronous processing, signed streaming links and clips. This
is an optional *level two* module that depends only on `university-core`. It provides Core's media
library, so podcasts and other modules use media without importing it.

- **Uploads are validated by content signature** against per-kind allow-lists (audio, video,
  image, document), with size limits, quotas, dimension and duration limits, SHA-256 hashes and
  random storage names. Executables and active content are always rejected.
- **Object storage:** S3, MinIO or any Django storage. Large files can go straight to storage via
  presigned uploads and are verified before use.
- **Asynchronous processing** on the task backend. The built-in processor needs no tools;
  `FFmpegProcessor` makes MP3 renditions, 720p MP4s and poster frames, cuts clips, and runs
  sandboxed (no shell, timeouts, file-only protocols).
- **Signed, expiring links** with HTTP Range support for seeking, or the storage's own presigned
  or CDN URLs.
- **Clean-up:** orphaned and failed uploads are deleted, and purge removes a person's files.

```bash
pip install university-media
```

See [the module documentation](../../docs/modules/media.md).
