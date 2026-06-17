> Status: active · Task: mobile-auth

# Mobile Authentication — Spec Index

Onyx mobile app (Expo / React Native) authentication. **Approach C — Mobile Auth Gateway (BFF)**: native Bearer auth reusing the existing revocable session token behind an `issue_session_credential` seam + a provider registry. **V1 = email/password + Google**, against **Onyx Cloud + self-hosted**, with **PKCE on the deep-link exchange**. SAML / OIDC / Apple Sign In and refresh-token rotation are designed-for and deferred behind the seams.

| # | Doc | What it covers |
|---|-----|----------------|
| 01 | [Research](01-research.md) | Requirement, clarifications, codebase scan (exact paths), web/industry findings, 3 approaches, chosen approach (C) |
| 02 | [High-Level Design](02-high-level-design.md) | Plain-language end-to-end flow, component interaction, key decisions |
| 03 | [Detailed Design](03-detailed-design.md) | New files, file tree, per-file contents, integration points, important notes (no DB changes in V1) |
| 04 | [Implementation Plan](04-implementation-plan.md) | CLAUDE.md-format plan + Plan-Challenge results (RFC 8252 / RFC 9700 / BFF verified) |
| 05 | [PR Roadmap](05-pr-roadmap.md) | 5 review-sized PRs with scope, files, tests, drift checkpoints |

**Key locked decisions:** native Bearer (not webview-cookie) · reuse existing token, rotation deferred · backend SSO-bridge + one-time PKCE-bound code over `onyx://` deep link (host-agnostic) · reuse the already-registered IdP callback (no new redirect URI for self-hosted) · App Store 4.8 (Sign in with Apple) is an accepted V1 risk.
