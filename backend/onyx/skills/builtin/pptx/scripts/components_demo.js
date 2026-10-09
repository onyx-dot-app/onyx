// Demo deck exercising every component in components.js — one slide per
// component, on the default monochrome palette. Doubles as a lint fixture: the
// output must pass `python scripts/lint.py` with zero ERRORs.
//
//   node .opencode/skills/pptx/scripts/components_demo.js [outputs/components-demo.pptx]
//
// Uses tiny embedded placeholder PNGs so it runs with no asset setup; real
// decks pass icon.js / chart.py / image-generation outputs as file paths.
// Content is generic placeholder text — the demo is illustrative, not branded.
"use strict";

const C = require("./components.js");

const PLACEHOLDER_IMAGE =
  "image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAKAAAAC0CAIAAACc6rD3AAABm0lEQVR42u3c0Y0EIQxEQWzx5fwDJgysVlUIZ5nHzs5tzcwh160qfwUDxoDZOuD2V0gecLcNdkRjwGgwXwasweGXLEe0BqPBaDAajAajwdhglyxcstBgNBgNRoPRYA1Gg7HBrLtkabANRoOxwfgcjCdZOKJxydJgNBgNZkGDHdE2GAPGJQsNxhGNAaPBGowjGgPGgPHaLL7wxxFtwHhlBz/pjyMaA0aD0WAc0QaMBuNZNF7ZQYPRYGywBx3YYDQYG4wHHXhtFke0AaPB+JiEb5PQYDQYDUaDNRgDxs8oYYNxycIGo8E2GA3GBqPB2GAMGJcs3wf7K3ijAw1Gg9FgNBgNxoD9fzAajCMaH5OwwfilO2ywBmOD8W0SHnSgwWgwBowHHRqMIxoDRoPRYBzRGLBn0XhtFkc0BowB42eU8MqOIxoDRoPRYBzRGDAajA12ycIrO/jCHw1Gg9FgHNEuWdhgvDaLDUaDscH4HOxJFhqMBqPBaDAajAajwTYYlyxcstBgNBgNRoM1GA3GgPGT/mgwjmgM2IDbr+xEexNSBYTYe7cAAAAAAElFTkSuQmCC";

const PLACEHOLDER_CHART =
  "image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAUAAAAC0CAIAAABqhmJGAAABwUlEQVR42u3dsRGAIAxA0egxAGvZ2TiljZ1rsUFcI8J7E3Dh/qWDLTMD+KfdCEDAgIABAYOAAQEDAgYEDAIGBAwIGAQMCBgQMCBgEDAgYEDAgIBhDs0ImEzvvdqRxhg2MCBgEDAgYEDAIGBAwICAAQGDgAEBAwIGBAwCBgQMCBgEDAgYEDAgYBAwIGBAwICAQcCAgAEBg4ABAQMCBgQMAgYEDAgYBAwIGBAwIGAQMFBZM4Jl3c9b7UjXebgXGxgEDAgYEDAgYBAwIGBAwCBgQMCAgAEBg4ABAQMCBgQMAgYEDAgYwptYhLejsIEBAQMCBgEDAgYEDAgYBAwIGBAwCBgQMCBgQMAgYEDAgIBBwICAAQEDAgYBAwIGBAwIGAQMCBgQMAgYiIV/J/SLH9jAgIBBwICAAQEDAgYBAwIGBAwCBgQMCBgQMAgYEDAgYEDAIGBAwICAQcCAgAEBAwIGAQMCBgQMCBgEDAgYEDAIGBAwIGBAwCBgQMCAgEHAgIABAQMCBgEDAgYEDAgYBAwIGBAwCBgQMCBgQMAgYEDAgIABAYOAAQEDAoalbJlpCmADAwIGBAwCBgQMCBgQMAgYKOADbNwTab9X4BcAAAAASUVORK5CYII=";

async function main() {
  const outPath = process.argv[2] || "outputs/components-demo.pptx";

  const theme = C.defaultTheme();
  const pres = C.createPresentation(theme, { title: "Components Demo", author: "Demo" });

  C.titleSlide(pres, theme, {
    title: "Assemble decks from tested parts.",
    subtitle: "Every slide on this deck is one components.js call.",
    meta: "PRODUCT · 2026",
  });

  C.agendaSlide(pres, theme, {
    items: ["Why a component library", "Layout primitives", "Data display", "Imagery and charts", "Wrapping up"],
  });

  C.sectionDivider(pres, theme, {
    number: 1,
    title: "Layout primitives.",
    subtitle: "Fixed margins, tested geometry, zero hand-placed coordinates.",
  });

  C.contentSlide(pres, theme, {
    title: "Plain content slide",
    body: [
      "Title plus a single-column body with generous whitespace",
      "Takes a bullet array or a paragraph string",
      "The straightforward text slide — no forced visual",
    ],
  });

  C.twoColumn(pres, theme, {
    title: "Two-column with a visual slot",
    body: [
      "Text column takes bullets or short paragraphs",
      "Visual slot accepts an image or a chart PNG",
      "Long content shrinks within bounds instead of overflowing",
      "Swap sides with visualSide: \"left\"",
    ],
    visual: { type: "image", data: PLACEHOLDER_IMAGE },
  });

  C.comparisonSlide(pres, theme, {
    title: "Side-by-side comparison",
    left: { heading: "Hand-placed", items: ["Coordinates by hand", "Drifts across slides", "Overflow is common", "Slow to build"] },
    right: { heading: "Components", items: ["One call per slide", "Consistent geometry", "Overflow guarded", "Fast to build"] },
  });

  C.quadrant(pres, theme, {
    title: "Effort vs. impact",
    xAxis: { low: "LOW EFFORT", high: "HIGH EFFORT" },
    yAxis: { low: "LOW IMPACT", high: "HIGH IMPACT" },
    cells: [{ label: "Quick wins" }, { label: "Big bets" }, { label: "Fill-ins" }, { label: "Money pits" }],
  });

  C.iconRow(pres, theme, {
    title: "Icon row",
    items: [
      { label: "Composable", desc: "Each component is one function call with fixed geometry" },
      { label: "Guarded", desc: "Autoshrink and ellipsis truncation keep text inside its box" },
      { label: "Themed", desc: "One theme object threads palette and fonts through every slide" },
    ],
  });

  C.processFlow(pres, theme, {
    title: "Process flow",
    steps: [
      { label: "Draft", desc: "Write the full text deck first" },
      { label: "Enhance", desc: "Add charts, icons, imagery" },
      { label: "Lint", desc: "Fix every mechanical defect" },
      { label: "Ship", desc: "Save the deck to outputs" },
    ],
  });

  C.timeline(pres, theme, {
    title: "Timeline",
    steps: [
      { label: "Pick theme", desc: "Palette and font pairing" },
      { label: "Assemble", desc: "One component call per slide" },
      { label: "Enhance", desc: "Charts, icons, imagery in passes" },
      { label: "Lint", desc: "lint.py until clean, then visual QA" },
    ],
  });

  C.statCallouts(pres, theme, {
    title: "Stat callouts",
    stats: [
      { value: "15 min", label: "Turn ceiling", desc: "Hand-placed geometry burns the whole turn" },
      { value: "0", label: "Lint errors", desc: "Components are pre-tested against lint.py", hero: true },
      { value: "23", label: "Components", desc: "Covering the layouts most decks need" },
    ],
  });

  C.kpiGrid(pres, theme, {
    title: "Metrics dashboard",
    kpis: [
      { value: "4.2k", label: "Decks built" },
      { value: "98%", label: "Lint pass rate" },
      { value: "23", label: "Components" },
      { value: "0.5\"", label: "Margins" },
      { value: "2x", label: "Faster" },
      { value: "11pt", label: "Min body" },
    ],
  });

  C.bigStatement(pres, theme, {
    statement: "One idea, one slide.",
    support: "When a claim deserves the whole slide, give it the whole slide.",
  });

  C.barCompare(pres, theme, {
    title: "Ranked comparison",
    items: [
      { label: "Components", value: 100, display: "100", highlight: true },
      { label: "Templates", value: 72, display: "72" },
      { label: "By hand", value: 38, display: "38" },
    ],
  });

  C.tableSlide(pres, theme, {
    title: "Data table",
    headers: ["Approach", "Slides/hr", "Overflow", "Lint"],
    numericCols: [1],
    rows: [
      ["Components", "24", "Guarded", "Clean"],
      ["Templates", "12", "Manual", "Varies"],
      ["By hand", "5", "Common", "Noisy"],
    ],
  });

  C.chartSlide(pres, theme, {
    title: "Chart with takeaway",
    chart: { data: PLACEHOLDER_CHART },
    takeaway: "Q4 broke the trend — the ink bar is the story, the rest is context.",
  });

  C.imageSlide(pres, theme, {
    title: "Half-bleed image",
    body: [
      "Image fills one half edge-to-edge",
      "Text stays in the safe zone with full margins",
      "bleed: \"full\" puts text on a solid dark bottom panel instead",
    ],
    image: { data: PLACEHOLDER_IMAGE },
    bleed: "half",
    side: "right",
  });

  C.logoWall(pres, theme, {
    title: "Trusted by",
    logos: [
      { data: PLACEHOLDER_IMAGE },
      { data: PLACEHOLDER_IMAGE },
      { data: PLACEHOLDER_IMAGE },
      { data: PLACEHOLDER_IMAGE },
      { data: PLACEHOLDER_IMAGE },
      { data: PLACEHOLDER_IMAGE },
    ],
  });

  C.teamSlide(pres, theme, {
    title: "The team",
    members: [
      { photo: PLACEHOLDER_IMAGE, name: "A. Rivera", role: "PRODUCT" },
      { photo: PLACEHOLDER_IMAGE, name: "J. Chen", role: "ENGINEERING" },
      { photo: PLACEHOLDER_IMAGE, name: "M. Okafor", role: "DESIGN" },
    ],
  });

  C.quoteSlide(pres, theme, {
    quote: "Agents assemble slides from tested layout functions instead of hand-writing coordinates.",
    attribution: "Placeholder attribution",
  });

  C.testimonialSlide(pres, theme, {
    quote: "We cut deck-building time in half and stopped fighting overflow bugs.",
    name: "R. Delgado",
    company: "VP Product, example.com",
    photo: PLACEHOLDER_IMAGE,
  });

  C.ctaSlide(pres, theme, {
    title: "Get started.",
    actions: ["Read components.md", "Run the demo deck", "Build your first deck"],
  });

  C.closingSlide(pres, theme, {
    title: "Thank you.",
    subtitle: "See components.md for the full catalog.",
    contact: "example.com",
  });

  await pres.writeFile({ fileName: outPath });
  process.stdout.write(`Wrote ${outPath}\n`);
}

main().catch((err) => {
  process.stderr.write(`Error: ${err.message}\n`);
  process.exit(1);
});
