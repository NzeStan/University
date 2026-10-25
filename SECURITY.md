# Security Policy

University handles identity, private communications and personal data for students and staff.
We treat security reports as our highest priority.

## Supported versions

| Package | Version | Supported |
| --- | --- | --- |
| All `university-*` packages | 0.1.x | ✅ |

Until 1.0, only the latest minor release of each package receives security fixes. After 1.0,
the latest two minor releases will be supported.

## Reporting a vulnerability

**Please do not open public issues for security problems.**

- Preferred: GitHub's private vulnerability reporting ([Report a vulnerability](https://github.com/NzeStan/University/security/advisories/new)).
- Or email **nnamaniifeanyi10@gmail.com** with `[SECURITY]` in the subject.

Please include:

- the affected package(s) and version(s);
- a description of the issue and its impact;
- steps to reproduce or a proof of concept;
- any suggested fix.

## Our process

| Step | Target |
| --- | --- |
| Acknowledge your report | within 2 business days |
| Initial assessment and severity | within 5 business days |
| Fix for critical/high severity | as fast as possible, normally within 14 days |
| Coordinated public disclosure | after a fix is released, normally within 90 days of the report |

We will keep you informed, credit you in the release notes (unless you prefer otherwise) and
request a CVE where appropriate.

## Responsible disclosure guidelines

- Test only against accounts and data you own, or local deployments.
- Do not access, modify or retain other people's data. Stop and report as soon as you see any.
- Do not degrade service availability (no denial-of-service testing against shared systems).
- Do not use social engineering, physical attacks or spam.
- Give us reasonable time to fix the issue before any public disclosure.

We will not pursue legal action against researchers who act in good faith under these guidelines.

## Scope highlights

We are particularly interested in:

- authentication or session bypass, token forgery, and gaps in refresh-token reuse detection;
- authorisation flaws: IDOR/BOLA, scope escapes, privilege escalation;
- account, email, phone or membership enumeration;
- leaks of protected identities (for example anonymous authorship, once that module ships);
- injection, SSRF, unsafe deserialisation, upload validation bypasses;
- tampering with the audit log that verification does not detect.

## Hardening guidance for deployers

See [docs/security](docs/security/index.md) and [docs/deployment](docs/deployment/index.md), and
always run `python manage.py check --deploy` before releasing.
