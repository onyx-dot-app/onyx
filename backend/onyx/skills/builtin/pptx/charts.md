# Charts

> **Path convention**: All commands run from the **session workspace**. Prefix skill scripts with `.opencode/skills/pptx/`. Generated files go in `outputs/`.

Render charts as **PNG images via matplotlib** using the `chart.py` styling helper, then place them like any other image. This works identically for the from-scratch path (pptxgenjs `addImage`) and the template-editing path, and gives full styling control so charts match the deck instead of looking like a pasted Jupyter screenshot.

Only use native PowerPoint charts (pptxgenjs `addChart` or python-pptx) when the user **explicitly asks for an editable chart** — their styling control is much weaker.

---

## Grounding Rule (read first)

**Only chart real data.** Real data comes from the user's message, attachments, files in the workspace, or company-search results. **Never fabricate numbers to fill a chart** — a made-up chart is worse than no chart. If you have a claim but no underlying series (e.g. "revenue tripled"), use a **stat callout** (big number + label, see SKILL.md "Data display") instead of inventing data points.

## When to Chart vs. Stat Callout

| The data is… | Use |
|---|---|
| A single number (+ maybe a delta) | Stat callout, not a one-bar chart |
| 2-4 headline numbers | Row of stat callouts |
| A series to compare or a trend over time | Chart |
| More than ~7 categories that all matter | Table (or fold the tail into "Other") |

## Chart-Type Selection

| Job | Type |
|---|---|
| Compare magnitudes across categories | Bar (horizontal for long category names) |
| Trend over time | Line (area only for a single series) |
| Part-to-whole | Donut (≤ 4 slices) or stacked bar |
| One series is the story, rest are context | Highlight it in the accent color, gray the rest |

**Avoid:** pie/donut charts with more than 4 slices, 3D effects of any kind, dual y-axes (use two charts instead), and a legend when direct labels fit. Give every series a fixed color from the deck palette — don't let colors shift between charts of the same deck.

## Using chart.py

```python
import sys
sys.path.insert(0, ".opencode/skills/pptx/scripts")
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from chart import deck_style, save_for_slide

DECK_PALETTE = ["1E2761", "CADCFC", "F96167"]  # your deck's colors, dominant first

with deck_style(palette=DECK_PALETTE, font="Montserrat"):
    fig, ax = plt.subplots(layout="constrained")
    ax.bar(["Q1", "Q2", "Q3", "Q4"], [4500, 5500, 6200, 7100])
    ax.set_title("Quarterly Sales")
    save_for_slide(fig, "outputs/chart-sales.png", width_in=6, height_in=3.5)
```

- `palette`: the deck's palette (same hex values as the rest of the deck; bare hex like `"1E2761"` is fine). When editing a template, pull colors from the template's theme.
- `font`: the deck's **body** font (must be an installed font — see SKILL.md Typography). When editing a template whose fonts are embedded-only, pick the closest installed font for charts.
- `background`: omit for a transparent PNG (slide background shows through — usually what you want); pass the slide background hex if you need an opaque chart.
- Direct-label bars/points where it helps (`ax.bar_label(...)`) instead of forcing readers to the axis.

## Sizing and Placement

Decide the chart's region on the slide **in inches first**, then pass exactly those inches to `save_for_slide` — it renders at 2x resolution (200 DPI) so the PNG stays crisp. Place the PNG at the same size:

```javascript
// pptxgenjs (from scratch)
slide.addImage({ path: "outputs/chart-sales.png", x: 0.5, y: 1.2, w: 6, h: 3.5 });
```

For the template-editing path, insert the PNG as slide media (replace an existing picture's media file, or add an image the same way any picture is referenced in the slide XML) at the placeholder's size — see [editing.md](editing.md).

Typical sizes on a 10" x 5.625" slide: half-slide chart ~4.5 x 3.2", two-thirds ~6 x 3.5". Don't shrink a chart below ~3" wide — use a stat callout instead.
