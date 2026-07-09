---
name: image-generation
description: Generate or edit raster images (photos, illustrations, textures, sprites, mockups, logos, infographics) using the workspace's configured image-generation provider via `onyx-cli image`. Use when the task should produce a brand-new bitmap image, transform an existing image, or derive variants from references — not when the output is better as code-native SVG/vector or built directly in HTML/CSS/canvas. If no image provider is configured, tell the user to set one up at /admin/configuration/image-generation.
---

# Image Generation Skill

Generate or edit images for the current project (website assets, game assets,
UI and product mockups, wireframes, logos, photorealistic images, infographics)
using `onyx-cli image`. Generation runs server-side with whatever provider the
admin configured at `/admin/configuration/image-generation` (OpenAI, Gemini, or
Azure) — **no API key is needed here.**

## When a provider isn't configured

If `onyx-cli image …` exits with "no image generation provider is configured",
stop and tell the user: *image generation is unavailable until an admin
configures a provider at `/admin/configuration/image-generation`.* Do not try to
work around it with another tool.

## When to use
- Generate a new image (concept art, product shot, hero, texture, sprite).
- Generate a new image guided by reference images (style, composition, mood).
- Edit an existing image (background replacement, object removal, lighting/weather change, compositing, inpainting).
- Produce many assets or variants for one task.

## When not to use
- Extending or matching an existing SVG/vector icon set, logo system, or illustration library already in the repo — edit those directly.
- Simple shapes, diagrams, wireframes, or icons better produced as SVG / HTML/CSS / canvas.
- A small project-local asset edit when the source already exists in an editable native format.
- Any task where the user clearly wants deterministic code-native output, not a generated bitmap.

## Decision tree

1. **Intent** — new image or edit of an existing image?
   - Modify an existing image while preserving parts of it → `image edit`.
   - Images supplied only as references for style/composition/mood, or no images → `image generate`.
2. **Execution** — one asset or many?
   - One asset → a single command.
   - Many *distinct* assets → one command per asset (do **not** use `-n` for distinct assets; `-n` produces variants of one prompt).

Assume the user wants a new image unless they clearly ask to change an existing one.

## Usage

### Generate (text-to-image)

```bash
onyx-cli image generate \
  -p "A minimal hero of a ceramic coffee mug, clean product photography, soft studio lighting, wide composition with negative space, no text, no watermark" \
  --shape landscape \
  -o assets/hero.png
```

### Edit / composite existing image(s)

`-i/--input-image` may be repeated to composite multiple inputs; the first is the
primary edit source.

```bash
onyx-cli image edit \
  -i assets/product.png \
  -p "Replace only the background with a warm sunset gradient; keep the product and its edges unchanged" \
  -o assets/product-sunset.png
```

Reference images are sent inline, and the sandbox egress proxy rejects any
request body over ~32 MiB with a "request body is larger than the limit"
(`body_too_large`) error. base64 inflates size by ~33%, so keep each `-i` image
roughly under ~20 MB on disk (downscale large source images first). This only
affects `edit`; plain `generate` has a tiny request body.

### Variants of one prompt

```bash
onyx-cli image generate -p "Abstract colorful album cover art" -n 3 -o art.png
```

`-n > 1` requires a model that supports multiple images per request (e.g.
`gpt-image-*`). Some models (e.g. `dall-e-3`) only support `-n 1` and will error
otherwise; if `-n > 1` fails, retry with `-n 1`.

The command prints the saved file path(s), one per line (multiples get a `_N`
suffix). **Open the output with `view_image` to inspect it and iterate** with a
single targeted prompt change.

## Flags

| Flag | Short | Applies to | Default | Description |
|------|-------|-----------|---------|-------------|
| `--prompt` | `-p` | both | — | Text prompt / instruction (required). |
| `--output` | `-o` | both | `output.png` | Output path; multiples get `_N` suffixes. |
| `--shape` | — | both | `square` | `square`, `portrait`, or `landscape`. |
| `--quality` | `-q` | both | provider default | Render quality (e.g. `low`/`medium`/`high`/`auto`). |
| `--num` | `-n` | both | `1` | Variants of a single prompt. |
| `--input-image` | `-i` | edit | — | Input image path; repeat to composite. |

## Workflow
1. Decide intent (`generate` vs `edit`) and execution (single vs repeated commands).
2. Collect inputs up front: prompt(s), exact in-image text (verbatim), constraints/avoid list, and any input images with their roles.
3. Shape the prompt by specificity: if it's already detailed, normalize it; if generic, add tasteful detail only when it materially improves the result.
4. Run `onyx-cli image …`, saving project-bound assets into the workspace. Don't overwrite an existing asset unless asked — use a sibling version (e.g. `hero-v2.png`).
5. `view_image` the output; inspect subject, style, composition, and text accuracy; iterate with one targeted change.
6. Report the saved path(s) and the final prompt(s).

## Prompt schema

Use these labeled lines as scaffolding; include only the ones that help.

```text
Use case: <photorealistic | product-mockup | ui-mockup | infographic | logo | illustration | concept-art | edit:object | edit:background | edit:style | compositing>
Asset type: <where the asset will be used>
Primary request: <main prompt>
Subject: <main subject>
Style/medium: <photo / illustration / 3D / etc.>
Composition/framing: <wide / close / top-down; placement>
Lighting/mood: <lighting + mood>
Color palette: <palette notes>
Text (verbatim): "<exact text>"
Constraints: <must keep / must avoid>
```

## Prompting best practices
- Structure as scene/backdrop → subject → details → constraints.
- State the intended use (ad, UI mock, infographic) to set polish level.
- Use camera/composition language for photorealism.
- Quote exact in-image text verbatim and specify typography + placement; for tricky words, spell them out and require verbatim rendering.
- For edits, repeat the invariants every iteration (`change only X; keep Y unchanged`).
- For multi-image inputs, reference each image and describe how to use it.
- Iterate with single-change follow-ups.
- If the prompt is generic, add only detail that materially helps; if it is already detailed, normalize rather than expand.
