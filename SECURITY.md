# Security Policy

We take the security of Onyx and our users seriously. Thank you for helping
keep Onyx and its community safe by practicing responsible disclosure.

## Supported Versions

Security fixes are applied to the `main` branch and the latest tagged release.
We strongly recommend running the most recent release of Onyx. Older releases
are not guaranteed to receive backported security patches.

## Reporting a Vulnerability

**Please do not report security vulnerabilities through public GitHub issues,
pull requests, or discussions.** Public reports give attackers a head start
and put other users at risk before a fix is available.

Instead, please use **GitHub Private Vulnerability Reporting** to file a
report at
<https://github.com/onyx-dot-app/onyx/security/advisories/new>. This
creates a private advisory visible only to the maintainers and ensures
your report is tracked rather than landing in an individual inbox.

Please include as much of the following as you can — it helps us triage
faster:

- A description of the issue and the impact you believe it has.
- The Onyx version, deployment type (self-hosted, Onyx Cloud, Docker, Helm,
  etc.), and any relevant configuration.
- Step-by-step reproduction instructions or a proof-of-concept.
- Any logs, screenshots, or sample payloads that demonstrate the issue.
- Your name and a way to credit you in the advisory, if desired.

## Response Expectations

After you report a vulnerability:

- We will work with you to validate the issue and agree on a disclosure
  timeline. Typical investigations take **up to 90 days**, though many issues
  are resolved sooner.
- We will keep you informed of progress and let you know when a fix is
  released.
- Once a fix is available, we will coordinate public disclosure (release
  notes, GitHub Security Advisory, and CVE if applicable) and are happy to
  credit reporters who would like recognition.

## Scope

In scope:

- The Onyx application code in this repository (backend, web, desktop, CLI,
  connectors, deployment manifests).
- Official Onyx-published Docker images and Helm charts.

Out of scope:

- Third-party services and integrations (please report those to the
  respective vendors).
- Findings that require access to a user's account or device, social
  engineering, or physical attacks.
- Denial-of-service issues caused solely by sending high volumes of traffic.
- Automated scanner output without a demonstrated, exploitable impact.

## Safe Harbor

We will not pursue or support legal action against researchers who:

- Make a good-faith effort to follow this policy.
- Avoid privacy violations, data destruction, or service degradation.
- Give us a reasonable opportunity to remediate before any public
  disclosure.

Thank you for helping keep Onyx and our community secure.
