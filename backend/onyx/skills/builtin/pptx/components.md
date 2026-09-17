# Slide Components

> **Path convention**: All commands run from the **session workspace**. Prefix skill scripts with `.opencode/skills/pptx/`. Generated files go in `outputs/`.

**Components are the DEFAULT way to build a deck from scratch.** Each component is a tested layout function: fixed 0.5" margins, the SKILL.md typography scale, contrast-safe color picking, and shrink/truncate guards so long content cannot overflow. Assembling slides from components is much faster than hand-placing shapes and produces decks that pass `lint.py` on the first try. Drop to raw pptxgenjs ([pptxgenjs.md](pptxgenjs.md)) **only** for a layout no component covers — and even then, keep the rest of the deck on components.

Components are for the **from-scratch path only**. When editing a chosen template, follow [editing.md](editing.md) instead.

## Design language: engineered monochrome

The default visual system is **engineered monochrome**: a white field with near-black ink, hierarchy carried by weight and size (not color). It is intentionally restrained — the design reads as precise and technical rather than decorated.

- **White field, ink text.** Content slides are white; text is near-black (not pure black), with a gray reserved for genuinely secondary lines. Body copy stays dark for comfortable contrast.
- **Rules, not cards.** Panels and columns are separated by thin hairline rules and whitespace — never tinted card fills.
- **Hairline grid.** Title, section, and closing slides carry a faint architectural grid in the empty region (kept clear of text).
- **The notched plate.** The one accent shape is a cut-corner rectangle (`snip1Rect`) filled in the primary ink with reversed text — used as the single dominant emphasis element on a slide (the title meta chip, one hero stat, the closing CTA). Never more than one per slide.
- **Rectilinear.** No circles. Timeline markers are small filled ink squares; icons sit bare (no colored backers).
- **Type.** Inter carries display and body; a monospace (Fira Code) is the "technical voice" for labels, section markers, step numbers, and attributions. Display headlines read best in **sentence case ending with a period** ("Give your team superpowers.").

**Themeability is preserved.** Every motif derives from the theme object — the hairline is a low blend of `background` toward `text`, the grid likewise per light/dark field, the plate is `theme.primary` with `theme.onPrimary` text, and dark slides use a theme-derived dark field. Passing a custom palette to `makeTheme` renders the *same* architecture in *those* colors, with no brand-specific values leaking in.

## Setup

Use the default monochrome palette (`defaultTheme()`) unless the user wants a specific palette:

```javascript
const C = require(".opencode/skills/pptx/scripts/components.js");

const theme = C.defaultTheme(); // engineered monochrome — colors + fonts, no branding
const pres = C.createPresentation(theme, { title: "Deck Title", author: "You" });

// ...one component call per slide...

await pres.writeFile({ fileName: "outputs/deck.pptx" });
```

For a topic-specific palette, `makeTheme` inherits the whole system in your colors:

```javascript
const theme = C.makeTheme({
  primary: "1E2761",   // dominant ink — plates, dark bookend field, markers
  secondary: "CADCFC", // supporting tone — muted reversed text on dark
  accent: "F96167",    // sharp accent — stat numerals, emphasis
  headerFont: "Montserrat",
  bodyFont: "Inter",
  monoFont: "Fira Code",
});
```

`makeTheme` needs only `primary`; everything else is derived and overridable. Keys: `primary`, `secondary`, `accent`, `background` (light field, default white), `text`, `muted`, `hairline`, `gridLight`, `gridDark`, `darkField` (bookend background — defaults to `primary` if dark, else a computed near-black), and `headerFont`/`bodyFont`/`monoFont` (rejected if not installed in the sandbox — see SKILL.md Typography). All colors are 6-digit hex, `#` optional. Contrast-safe roles (`onPrimary`, `onDark`, `accentStrong`, …) are computed for you — you never pick a text color per slide.

## Component catalog

Every component has the signature `component(pres, theme, opts)` and returns the created slide. Content beyond each limit is truncated with an ellipsis; oversized text shrinks within its box (down to a floor) before truncating.

| Component | Signature (opts) | Notes |
|---|---|---|
| `titleSlide` | `{ title, subtitle?, meta? }` | White field, faint grid right, large ink headline low-left. `meta` renders on a notched plate (author/date). |
| `agendaSlide` | `{ title?, items }` | Numbered index rows separated by hairlines. ≤5 items one column, 6-8 two columns. |
| `sectionDivider` | `{ number?, title, subtitle? }` | Dark field, huge white display title, monospace `SECTION 0N` label. |
| `twoColumn` | `{ title, body, visual?, visualSide? }` | `body` = string array (bullets). `visual` = `{ type: "image"\|"chart", path }`; omit it and the columns split with a single hairline rule. `visualSide`: `"right"` (default) or `"left"`. |
| `iconRow` | `{ title, items }` | 2-4 items of `{ iconPath?, label, desc? }`, columns separated by hairlines. `iconPath` = **bare** PNG from `icon.js` (render it in an ink color); omit for a large numeral. |
| `statCallouts` | `{ title, stats }` | 2-4 of `{ value, label, desc?, hero? }` — display numeral, monospace label. Mark **one** stat `hero: true` to set it on the notched plate. Use for headline numbers instead of fabricating a chart. |
| `timeline` | `{ title, steps }` | 3-5 of `{ label, desc? }` — filled ink squares on a 1pt ink spine, monospace step numbers. |
| `imageSlide` | `{ title, body?, image, bleed?, side? }` | `image` = `{ path }`. `bleed: "half"` (default; image fills one half, text in safe zone, `side: "right"\|"left"`) or `"full"` (image fills slide, text on a solid dark bottom panel). |
| `chartSlide` | `{ title, chart, takeaway? }` | `chart` = `{ path }` / `{ data }`, a PNG from [charts.md](charts.md) / `chart.py`. Chart region is 6.1 × 3.7" — render the PNG at that size. `takeaway` = one-line so-what, hairline-separated beside the chart. |
| `quoteSlide` | `{ quote, attribution? }` | Pull-quote framed by full-width hairline rules above and below; monospace attribution. |
| `closingSlide` | `{ title?, subtitle?, contact? }` | Dark bookend; `title` defaults to "Thank you.". `contact` renders on an inverted notched plate. |
| `contentSlide` | `{ title, body }` | Use for a straightforward text slide with no visual. `body` = bullet array or a paragraph string; single column, generous whitespace. |
| `comparisonSlide` | `{ title, left, right }` | Use to contrast two options/states in words. Each of `left`/`right` = `{ heading, items[] }`; a vertical hairline splits them. (Text-vs-visual is `twoColumn`.) |
| `quadrant` | `{ title, xAxis, yAxis, cells }` | Use for a 2×2 positioning / effort-impact map. `xAxis`/`yAxis` = `{ low, high }` (mono labels); `cells` = up to 4 `{ label }` (TL, TR, BL, BR). |
| `processFlow` | `{ title, steps }` | Use for a non-dated flow/pipeline. 3-5 `{ label, desc? }` joined by ink arrows. (Dated → `timeline`.) |
| `bigStatement` | `{ statement, support? }` | Use when one claim/number deserves the whole slide. Oversized display text + optional supporting line. |
| `tableSlide` | `{ title, headers, rows, numericCols? }` | Use for tabular data. Bold header, hairline row separators (no zebra). Caps ~8 rows × 5 cols; `numericCols` = indices rendered mono/right-aligned. |
| `kpiGrid` | `{ title, kpis }` | Use for a multi-metric dashboard. Up to 8 `{ value, label }` in a 2×N grid with hairline separators. (Single headline row → `statCallouts`.) |
| `barCompare` | `{ title, items }` | Use for a ranked comparison without a chart PNG. Up to 6 `{ label, value, display?, highlight? }` as native horizontal ink bars; `highlight: true` emphasizes one. |
| `teamSlide` | `{ title, members }` | Use for people/team slides. Up to 4 `{ photo?, name, role? }`; `photo` = path or data (falls back to an outlined slot), hairline separators. |
| `logoWall` | `{ title?, logos }` | Use for a "trusted by" social-proof grid. Up to 12 logo slots (`{ path }` or `{ data }`), evenly spaced; graceful with fewer than the grid holds. |
| `testimonialSlide` | `{ quote, name?, company?, photo? }` | Use for one endorsement with a face/brand. Quote + attributor block (`photo` slot + name/company). (Pure text → `quoteSlide`.) |
| `ctaSlide` | `{ title, actions }` | Use to drive next steps (not the thank-you bookend — that's `closingSlide`). Heading + 1-3 `actions` as notched "button" plates. |

## Example: chart + stats + icons deck slice

```javascript
const theme = C.defaultTheme();

C.titleSlide(pres, theme, { title: "Q4 in review.", subtitle: "Revenue, retention, roadmap.", meta: "ACME · Q4 2026" });

C.statCallouts(pres, theme, {
  title: "Where we landed",
  stats: [
    { value: "$7.1M", label: "Q4 revenue", desc: "Up 14% quarter over quarter", hero: true },
    { value: "98%", label: "Retention" },
    { value: "3.2x", label: "Pipeline coverage" },
  ],
});

// chart.py PNG sized to the chartSlide region (see charts.md)
C.chartSlide(pres, theme, {
  title: "Quarterly revenue",
  chart: { path: "outputs/chart-revenue.png" },
  takeaway: "Q4 broke the flat trend — enterprise deals drove the jump.",
});

// icons pre-rendered with icon.js in ink, placed bare (no circle backer):
//   node .opencode/skills/pptx/scripts/icon.js trending-up --color 0F0F0F -o outputs/icons/up.png
C.iconRow(pres, theme, {
  title: "What worked",
  items: [
    { iconPath: "outputs/icons/up.png", label: "Expansion", desc: "Existing accounts grew 22%" },
    { iconPath: "outputs/icons/shield.png", label: "Churn control", desc: "Saves program cut churn in half" },
  ],
});
```

## Rules

- **One dominant visual per slide.** Each component already places exactly one (chart, image, icon row, stat row, one hero plate…). Don't add a second visual, don't set two `hero` stats, and don't stack components on one slide.
- **Vary layouts across the deck** — don't render five `twoColumn` slides in a row; mix in `iconRow`, `statCallouts`, `timeline`, `quoteSlide`.
- **Render assets first, pass paths in**: icons via `icon.js` (render in an ink color for the bare-icon treatment), charts via `chart.py` ([charts.md](charts.md)), and user-supplied or workspace images. Components never fetch or generate assets.
- **Never fabricate chart data** — with no underlying series, use `statCallouts` (see [charts.md](charts.md) grounding rule).
- Content limits are guards, not targets — a slide with 3 crisp bullets beats one with 6 truncated ones.
- QA still applies: run `lint.py`, then the visual pass (SKILL.md "QA"). Components make lint findings rare, not impossible — especially when you mix in raw pptxgenjs shapes.

## Demo / smoke test

`scripts/components_demo.js` renders a deck (on `defaultTheme()`) with one slide per component and must stay lint-clean:

```bash
node .opencode/skills/pptx/scripts/components_demo.js outputs/components-demo.pptx
python .opencode/skills/pptx/scripts/lint.py outputs/components-demo.pptx
```
