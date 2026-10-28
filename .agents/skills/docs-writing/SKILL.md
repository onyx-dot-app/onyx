---
name: "docs-writing"
description: "Write, rewrite, audit, or review a page of the Onyx customer docs (this Mintlify repo). Use for new pages, release refreshes, screenshot updates, connector and provider guides, API guides, and docs quality reviews. Covers audience, source-of-truth checks against the onyx repo, ASD-STE100 prose rules, Mintlify page patterns, screenshot capture, and the checks to run before a PR."
---

# Onyx docs writing

Every page here is customer-facing. The reader is an Onyx user, admin,
or developer who wants to do one thing with the product. Write for that reader, not for the Onyx team.

## 1. Before you write

### Name the reader and the page type

Pick one dominant reader for the page: end user, admin, developer, or operator who deploys Onyx.
Pick one Diataxis type per page: tutorial, how-to, reference, or explanation. If two readers or two types compete,
split the page or link out.

### Ground every claim in source truth

Do not document from memory or from the old page. Check the onyx repo (`onyx-dot-app/onyx`), in this order:

| Claim | Where to verify |
| --- | --- |
| What a feature does, what it touches, edition gating | `.agents/feature-map/components/<component>.md` (find it via `PATHS.md` or `INDEX.md`; read `GLOSSARY.md` first, Onyx overloads Persona, Tool, Agent, turn) |
| UI labels, menu names, button text | `web/src/i18n/messages/en.json`, then the component under `web/src/` |
| Admin routes and tier per route | `web/src/lib/admin-routes.ts` |
| Connector credential fields and form labels | `web/src/lib/credentials/constants.ts`, `web/src/lib/connectors/connectors.tsx` |
| Permission-sync support per source | `backend/ee/onyx/external_permissions/sync_params.py` |
| Env vars, defaults | `backend/onyx/configs/app_configs.py` and the config module that reads the var |
| API request and response shapes | the Pydantic models on the route, not the prose of an old guide |
| Route permissions | `require_permission(...)` on the FastAPI route |
| Release and version facts | git tags and `release/vX.Y` branches |

If a running stack is available, confirm the flow in the UI (`http://localhost:3000`,
`admin_user@example.com` / `TestPassword123!`). Code beats the old page; the running UI beats code when they disagree.

Business, legal, and infrastructure claims (subprocessors, compliance, SLAs, Cloud defaults, pricing, release cadence)
are not verifiable from code. Leave them as they are and list them as open questions for the page owner. Do not guess.

Remove content you cannot verify. Do not keep it with a caveat.

### Terminology

Use the current product names. One word for one idea, the same word on every page.

| Use | Do not use |
| --- | --- |
| Agent | Assistant, Persona |
| Plugin / Action | Tool (except in API field names) |
| Connector | Integration, data source (as a product noun) |
| Admin Panel | admin dashboard, settings page |
| OpenSearch | Vespa |
| Community Edition, Business, Enterprise, Onyx Cloud | EE, paid tier (undefined) |
| Document Set, User Group, Indexing Status | ad-hoc variants |

Use the exact label the UI shows, in bold, for anything the reader clicks or types into: **Admin Panel → Connectors**,
**Save API Key**.

## 2. Prose rules

Follow ASD-STE100 Simplified Technical English:

- Short sentences. 20 words or fewer for an instruction, 25 for a description.
- Active voice, second person for instructions: "Click **Connect**", not "Connect should be clicked".
- One topic per paragraph. One idea per sentence.
- Approved words only; each word has one meaning. Do not vary wording for style.
- Present tense for stable behaviour. Dates for historical events.
- Put the outcome, the prerequisites, and the shortest correct path first. Advanced options,
  alternatives, and limits come after the happy path unless safety requires them earlier.

Avoid:

- marketing language, hype, adjectives and adverbs that carry no fact,
- metaphors, cliches, colloquialisms, clever headings,
- unsupported claims, performance numbers without a source,
- repeated information, summary or conclusion setup phrases,
- meta-commentary about the docs or about AI,
- em dashes (use a period, comma, colon, or parentheses),
- vague references ("this", "it", "the above") where a section can be read alone,
- internal implementation detail (module names, Celery queues, tables) unless an admin needs
  it to operate the product.

Write so that a section quoted alone still answers the reader's question. Name the feature and the page in the sentence,
not only in the heading.

## 3. Mintlify page patterns

### Frontmatter

```mdx
---
title: "Document Processing"
description: "Configure document processing settings and options"
icon: "file-lines"
---
```

Keep `description` generic to the capability, not to the one vendor the UI shows today.
Every page must be in `docs.json` or reachable by a `redirects` entry. Removed pages get a redirect, never a dead URL.

### Structure

- Use `<Steps>` / `<Step title="...">` for procedures. Numbered Markdown lists fail the
  `format-docs` pre-commit hook.
- Use shared snippets from `snippets/` instead of repeating a block:
  `navigate-to-ai-models.mdx`, `standard-ai-model-configs.mdx`, `enterprise-edition-info.mdx`,
  `business-edition-info.mdx`, `contact-us.mdx`.
- Tier gating: import the matching `*-edition-info.mdx` snippet at the top of a Business or
  Enterprise page. Say "Onyx Cloud includes every Business and Enterprise feature" only through the snippet,
  not in new prose.
- Callouts (`<Note>`, `<Tip>`, `<Warning>`, `<Info>`) only when they change what the reader
  does. A `<Warning>` states the condition and the consequence.
- Tables for parameters, env vars, and option lists. Bullets for unordered facts.
- Links use descriptive anchor text and site-relative paths (`/admins/connectors/overview`).

### Page shapes that work here

- **Connector page:** what gets indexed, prerequisites in the source system, credential
  steps (vendor console), Onyx steps (**Admin Panel → Connectors → New [Source] Account**, **Document Access**),
  permission sync if supported, limits and troubleshooting.
- **Model provider / gateway page:** short "Guide" intro, `<NavigateToAiModels />`, the
  Connect card steps with exact field names, `<StandardAiModelConfigs />`, final **Connect**.
- **Admin feature page:** overview of the capability (generic), where it lives in the Admin
  Panel, the steps, what changes for users, tier note.
- **API guide:** the shortest working request with real field names, then the contract table,
  then edge cases. Endpoint reference pages are generated from the OpenAPI spec;
  do not hand edit them (see `developers/api_reference`).

## 4. Images and video

- Format: WebP for images (`ffmpeg -i in.png -c:v libwebp -quality 90 out.webp`), MP4 for
  motion. No PNG, GIF, or JPG in `assets/` unless a vendor logo requires it.
- Markup: `<img className="rounded-image" src="/assets/<area>/<page>/<name>.webp" alt="..." />`.
  Video:
  `<video className="rounded-image" src="/assets/.../name.mp4" autoPlay muted loop playsInline aria-label="..." />`.
- Keep the existing path and filename when you replace a screenshot so the MDX does not
  change. Delete the asset file when you delete the image.
- Capture Onyx UI shots on a local stack: light theme, 1440x900 viewport at 2x device scale,
  admin user, seeded data that looks real (a connector, an agent, a chat), no personal data.
  Admin forms scroll in an inner container, so grow the viewport instead of `fullPage`.
  Hide the Next.js dev overlay (`nextjs-portal`) before every shot.
- Business and Enterprise pages need a license on the stack. Upload it through
  **Admin Panel → Billing**; never commit it.
- Vendor-console screenshots (Google Cloud, Atlassian, Slack) stay unless the vendor flow
  changed.
- Add media only when text cannot show the flow. Every image has alt text that says what it
  shows.

## 5. Checks before you open a PR

Run from the repo root:

```bash
python3 scripts/format_docs.py --write   # formats MDX and runs mintlify broken-links
python3 scripts/format_docs.py --check   # what the pre-commit hook runs
pre-commit run --files <changed files>
```

Also confirm:

- every `src="/assets/..."` on the changed pages resolves to a file,
- `docs.json` lists new pages and has a redirect for each removed page,
- the page renders in `mint dev` with no MDX error,
- no secrets, license files, or local URLs in the diff.

`prettier` rewrites `docs.json` on commit, so a commit that touches it fails once: re-add and commit again.

## 6. Review rubric

Score 0 to 2 per row. Publish at 16/20 or higher with no zero.

| Dimension | 2 means |
| --- | --- |
| Audience fit | Primary reader and goal are explicit |
| Task success | Steps are complete, in order, and success is recognizable |
| Content type | One Diataxis type per page or section |
| Accuracy | Every claim traced to code, the feature map, or the running UI |
| Structure | Headings, Steps, tables, and links form a clear map |
| Examples | Complete, realistic, copyable, no secrets |
| Terminology | Current product names, used the same way everywhere |
| Retrievability | Each section stands alone |
| Maintenance | Evergreen wording; volatile facts (versions, dates) are explicit |
| Style | STE: short, active, reader-centred, no filler |

## 7. Full-site audits

For a release refresh of many pages, use the tooling in `audit/`:

- `python3 audit/build_manifest.py` writes `audit/manifest.json`: every page, its nav group,
  feature-map components, and image references.
- `audit/CHECKLIST.md` is the per-page review unit for a fan-out of agents (one page group per
  agent; copy first, image verdicts reported, screenshots recaptured in a second pass).

## 8. What to report

When you finish a page or a review, state: the reader and page type, the structural changes,
the files or UI routes you used to verify each claim, and every claim you could not verify.
