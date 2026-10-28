<h2 align="center">
  <a href="https://www.onyx.app/"> <img width="60%" src="assets/logo/onyx_logo.svg" alt="Onyx logo" /></a>
</h2>

# Onyx Docs

This repo generates the docs and setup guide for [Onyx](https://github.com/onyx-dot-app/onyx)
found at [https://docs.onyx.app/](https://docs.onyx.app/).

It uses Mintlify, a low-code documentation generation tool.

More info on Mintlify found [here](https://mintlify.com/).

To make changes, check out `docs.json`.

### Set up Mintlify

Install the [Mintlify CLI](https://www.npmjs.com/package/mint) to preview the documentation changes locally.

To install, use the following command (requires node >= v18.0.0)

```
npm i -g mint
```

Run the following command at the root of your documentation (where docs.json is)

```
mint dev
```

### Publishing Changes

Changes are automatically deployed to production after merging to main.

### Troubleshooting

- Mint dev isn't running - Run `mint update` to pull the latest CLI and framework.
- Page loads as a 404 - Make sure you are running in a folder with `docs.json`
- Mintlify Docs - https://mintlify.com/docs/introduction

### Docs Formatter (scripts/format_docs.py)

A comprehensive Markdown/MDX formatter with intelligent formatting rules for documentation sites.

**Usage:**

```bash
# Check which files would be reformatted (exits with code 1 if changes needed)
python scripts/format_docs.py --check

# Apply formatting changes to files
python scripts/format_docs.py --write

# Set custom line width (default: 120)
python scripts/format_docs.py --write --width 100
```

**What it does:**

- **File scope:** Processes all `*.md`, `*.mdx`, `*.markdown` files recursively
- **Indentation:** Converts tabs to 2-space indentation; normalizes list indents to multiples of 2
- **Container normalization:** Properly formats nested structures like:
  - `<Steps>` with `<Step>` children
  - `<Accordion>` with `<AccordionItem>` children
  - `<Columns>` with `<Card>` children
  - `<CardGroup>` with `<Card>` children
  - Content inside containers gets indented one level deeper
- **Spacing control:** Ensures single blank lines around:
  - Headings and horizontal rules
  - Images (Markdown `![...]` and MDX `<Image>`)
  - Block-level components (`<Steps>`, `<Accordion>`, etc.)
  - Code fences (removes blanks after opening, adds after closing)
- **Advisory blocks:** Expands single-line tags to multi-line format:

  ```mdx
  <Warning>This is a warning</Warning>

  # Becomes:
  <Warning>
    This is a warning
  </Warning>
  ```

- **Text wrapping:** Reflows paragraphs to target width while preserving:
  - Code blocks and fenced code
  - Tables and complex formatting
  - Lines with backticks, URLs, or HTML/MDX tags
  - List item continuation indentation
- **Import cleanup:** Splits merged imports and fixes missing `import` keywords
- **YAML frontmatter:** Repairs malformed frontmatter and normalizes quoted values
- **Quality checks:**
  - Reports numbered lists (suggests using `<Steps>/<Step>` instead)
  - Warns about missing spaces after list markers (`1.item` → `1. item`)
  - Warns if `icon:` field missing from frontmatter (except in excluded directories)
- **Link validation:** Runs `broken-links` via the Mintlify CLI if available (install: `npm i -g mint`)

### TODOs and Enhancements

- Reintroduce the First Look page when bandwidth allows
- Add visuals for the Use Cases page
