# Invisible Firefox fetcher (proposal)

> Status: Draft proposal
> Created: 2026-05-27
> Tracking discussion: TBD

## Goal

Optional Firefox-based stealth fetcher path in `backend/onyx/utils/playwright_fetch.py`, parallel to the current Chromium-based `start_playwright()` and `fetch_rendered_html()`. Selected via env, no change to defaults.

## Motivation

The current playwright_fetch module handles bot-detection-aware navigation, but the underlying browser is vanilla Chromium. A growing share of customer doc sites and SaaS targets (ZenDesk article centers, Cloudflare-protected portals) return empty content or 403 even with the existing tuning. Related signals:

- Closed-stale #3616 "Web Connector: Inadequate Mimics in requests.get and Ineffective Playwright Mimic" (reporter ended up switching connectors but the underlying generic Web Connector pain remains)
- The lazy `OnyxWebCrawler` Cloudflare-fallback path documented in the module docstring is exactly the case where stealth helps

A Firefox build with fingerprint patches at the C++ source code level avoids the JS-shim detection surface that the standard playwright path uses.

## Proposed change

A small branch in `playwright_fetch.start_playwright()` so that, when `ONYX_WEB_FETCHER=invisible_firefox` is set, the function launches `firefox` with `executablePath` pointing at the patched binary plus the prefs map. No change to the public API surface (`BrowserContext` returned is identical from the caller's perspective).

`invisible_playwright` (https://github.com/feder-cr/invisible_playwright) is the Python wrapper. The patched Firefox 150 binary lives at https://github.com/feder-cr/invisible_firefox (MPL-2.0, same license as Firefox upstream).

## Out of scope

No change to the default Chromium path. No change to `WebConnector` or `OnyxWebCrawler` call sites. No change to dedicated connectors (ZenDesk, Confluence, etc).

## Maintenance

Issues against the backend route to feder-cr/invisible_playwright. Only ask of this repo would be the env-gated branch in `playwright_fetch.py` plus a config docstring update.
