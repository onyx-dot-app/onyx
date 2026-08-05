// Composable slide component library for pptxgenjs (see components.md).
//
// Usage:
//   const C = require(".opencode/skills/pptx/scripts/components.js");
//   const theme = C.defaultTheme(); // or C.makeTheme({ primary: "...", ... })
//   const pres = C.createPresentation(theme, { title: "My Deck" });
//   C.titleSlide(pres, theme, { title: "...", subtitle: "..." });
//   await pres.writeFile({ fileName: "outputs/deck.pptx" });
//
// Visual system: "engineered monochrome" — light field with ink text, hairline
// rules instead of card fills, faint architectural grid on title/divider/closing
// slides, a notched (snip-corner) plate as the single emphasis element, and
// rectilinear geometry throughout. All colors derive from the theme object;
// custom palettes inherit the same architecture in their own colors.
//
// Every component enforces 0.5" margins, the typography scale, one dominant
// visual per slide, and shrink/truncate guards so long content cannot
// overflow. pptxgenjs is resolved from the sandbox's global npm root
// (NODE_PATH is not set in the sandbox).
"use strict";

const { execFileSync } = require("child_process");

// --- Layout constants (LAYOUT_16x9, inches) ---------------------------------
const PAGE = { W: 10, H: 5.625 };
const MARGIN = 0.5;
const CONTENT_W = PAGE.W - 2 * MARGIN; // 9.0
const CONTENT_BOTTOM = PAGE.H - MARGIN; // 5.125
const BODY_TOP = 1.45; // below the title band on content slides
const HAIRLINE_PT = 0.75;

// Fonts installed in the sandbox (must stay in sync with SKILL.md Typography).
const KNOWN_FONTS = new Set([
  "inter",
  "montserrat",
  "lato",
  "eb garamond",
  "fira code",
  "calibri",
  "cambria",
  "arial",
  "arial black",
  "times new roman",
]);

// --- pptxgenjs resolution (mirrors icon.js) ----------------------------------

function globalNpmRoot() {
  try {
    return execFileSync("npm", ["root", "-g"], {
      encoding: "utf8",
      stdio: ["ignore", "pipe", "ignore"],
    }).trim();
  } catch {
    return null;
  }
}

let _pptxgen = null;

function requirePptxgen() {
  if (_pptxgen) return _pptxgen;
  const paths = [...module.paths, "/usr/local/lib/node_modules"];
  const root = globalNpmRoot();
  if (root && !paths.includes(root)) paths.push(root);
  let resolved;
  try {
    resolved = require.resolve("pptxgenjs", { paths });
  } catch {
    throw new Error(
      "pptxgenjs not found. It is baked into the sandbox image as a global npm package; " +
        "do not try to npm-install it through the egress proxy."
    );
  }
  _pptxgen = require(resolved);
  return _pptxgen;
}

// --- Color math ----------------------------------------------------------------

function normColor(raw, label) {
  const m = /^#?([0-9a-fA-F]{6})$/.exec(String(raw));
  if (!m) throw new Error(`theme.${label}: expected a 6-digit hex color, got "${raw}"`);
  return m[1].toUpperCase();
}

function rgbOf(hex) {
  return [parseInt(hex.slice(0, 2), 16), parseInt(hex.slice(2, 4), 16), parseInt(hex.slice(4, 6), 16)];
}

function hexOf(rgb) {
  return rgb.map((c) => Math.round(Math.min(255, Math.max(0, c))).toString(16).padStart(2, "0")).join("").toUpperCase();
}

// Blend a toward b by t (0..1).
function mix(a, b, t) {
  const ra = rgbOf(a);
  const rb = rgbOf(b);
  return hexOf(ra.map((c, i) => c + (rb[i] - c) * t));
}

const WHITE = "FFFFFF";
const BLACK = "000000";

function relLuminance(hex) {
  const [r, g, b] = rgbOf(hex).map((c) => {
    const v = c / 255;
    return v <= 0.03928 ? v / 12.92 : Math.pow((v + 0.055) / 1.055, 2.4);
  });
  return 0.2126 * r + 0.7152 * g + 0.0722 * b;
}

function contrastRatio(a, b) {
  const la = relLuminance(a);
  const lb = relLuminance(b);
  return (Math.max(la, lb) + 0.05) / (Math.min(la, lb) + 0.05);
}

// First candidate with >=3.6:1 contrast on bg (lint warns below 3.5); falls
// back to whichever pole (white/black) contrasts more.
function pickOn(bg, candidates) {
  for (const c of candidates) {
    if (contrastRatio(c, bg) >= 3.6) return c;
  }
  return contrastRatio(WHITE, bg) >= contrastRatio(BLACK, bg) ? WHITE : BLACK;
}

function isDark(hex) {
  return relLuminance(hex) < 0.18;
}

// --- Text fitting guards --------------------------------------------------------

// Conservative average glyph width as a fraction of font size.
function charW(sizePt, bold) {
  return sizePt * (bold ? 0.62 : 0.55);
}

function estLines(text, usableWIn, sizePt, bold) {
  const usablePt = Math.max(usableWIn * 72 - 10, 20);
  const spaceW = charW(sizePt, bold) * 0.5;
  // Count each hard-broken line separately, then word-wrap within it: a "\n"
  // always starts a new rendered line and never collapses into a space.
  let total = 0;
  for (const hardLine of String(text).split("\n")) {
    let lines = 1;
    let cur = 0;
    for (const word of hardLine.split(/\s+/).filter(Boolean)) {
      const w = Math.min(word.length * charW(sizePt, bold), usablePt);
      if (cur > 0 && cur + spaceW + w > usablePt) {
        lines += 1;
        cur = w;
      } else {
        cur += (cur > 0 ? spaceW : 0) + w;
      }
    }
    total += lines;
  }
  return Math.max(total, 1);
}

function truncate(text, maxChars) {
  const s = String(text).trim();
  if (s.length <= maxChars) return s;
  return s.slice(0, Math.max(maxChars - 1, 1)).trimEnd() + "…";
}

// Shrink font size (never below minSize) until the text fits the box at ~1.2
// line spacing; if it still doesn't fit, truncate with an ellipsis.
function fitBlock(text, { wIn, hIn, size, minSize, bold = false, maxLines = null }) {
  let s = size;
  const lineBudget = () => {
    const byHeight = Math.floor((hIn * 72) / (s * 1.2));
    return maxLines ? Math.min(byHeight, maxLines) : byHeight;
  };
  let out = String(text).trim();
  while (s > minSize && estLines(out, wIn, s, bold) > lineBudget()) s -= 2;
  let guard = 40;
  while (estLines(out, wIn, s, bold) > Math.max(lineBudget(), 1) && out.length > 8 && guard-- > 0) {
    out = truncate(out, Math.floor(out.length * 0.85));
  }
  return { text: out, size: s };
}

function fitLine(text, opts) {
  return fitBlock(text, { ...opts, hIn: (opts.size * 1.3) / 72, maxLines: 1 });
}

// --- Theme ---------------------------------------------------------------------

function makeTheme(opts) {
  if (!opts || !opts.primary) throw new Error("makeTheme requires at least { primary }");
  const primary = normColor(opts.primary, "primary");
  const secondary = normColor(opts.secondary || mix(primary, WHITE, 0.75), "secondary");
  const accent = normColor(opts.accent || primary, "accent");
  const background = normColor(opts.background || WHITE, "background");
  const text = normColor(opts.text || mix(BLACK, WHITE, 0.06), "text");
  const muted = normColor(opts.muted || mix(text, background, 0.38), "muted");
  const headerFont = opts.headerFont || "Inter";
  const bodyFont = opts.bodyFont || "Inter";
  const monoFont = opts.monoFont || "Fira Code";
  for (const [label, font] of [["headerFont", headerFont], ["bodyFont", bodyFont], ["monoFont", monoFont]]) {
    if (!KNOWN_FONTS.has(font.toLowerCase())) {
      throw new Error(
        `theme.${label}: "${font}" is not installed in the sandbox and would silently ` +
          `render as a fallback. Use one of: ${[...KNOWN_FONTS].join(", ")}`
      );
    }
  }
  // Dark field for the bookend slides: the primary itself when it is dark,
  // otherwise a near-black of the palette.
  const darkField = normColor(opts.darkField || (isDark(primary) ? primary : mix(primary, BLACK, 0.85)), "darkField");
  const hairline = normColor(opts.hairline || mix(background, text, 0.13), "hairline");
  return {
    primary,
    secondary,
    accent,
    background,
    text,
    muted,
    headerFont,
    bodyFont,
    monoFont,
    darkField,
    hairline,
    // Derived, contrast-safe roles:
    gridOnLight: normColor(opts.gridLight || mix(background, text, 0.08), "gridLight"),
    gridOnDark: normColor(opts.gridDark || mix(darkField, WHITE, 0.1), "gridDark"),
    onPrimary: pickOn(primary, [background]),
    onPrimaryMuted: pickOn(primary, [secondary, mix(secondary, WHITE, 0.4), mix(background, primary, 0.25)]),
    onDark: pickOn(darkField, [background]),
    onDarkMuted: pickOn(darkField, [secondary, mix(secondary, WHITE, 0.4), mix(background, darkField, 0.3)]),
    accentStrong: pickOn(background, [accent, primary, text]),
  };
}

// The default monochrome palette: engineered monochrome (white field,
// near-black ink). Just colors and fonts — no branding. Components derive
// everything from the theme object, so any makeTheme(...) palette inherits
// this same architecture in its own colors.
function defaultTheme() {
  return makeTheme({
    primary: "0A0A0A",
    secondary: "595F6B",
    accent: "0F0F0F",
    background: "FFFFFF",
    text: "0F0F0F",
    muted: "595F6B",
    hairline: "E4E7EB",
    gridLight: "E9ECEF",
    gridDark: "1F1F1F",
    darkField: "0A0A0A",
    headerFont: "Inter",
    bodyFont: "Inter",
    monoFont: "Fira Code",
  });
}

function createPresentation(theme, meta = {}) {
  const pptxgen = requirePptxgen();
  const pres = new pptxgen();
  pres.layout = "LAYOUT_16x9";
  if (meta.title) pres.title = meta.title;
  if (meta.author) pres.author = meta.author;
  return pres;
}

// --- Internal building blocks ----------------------------------------------------

function hr(slide, color, x, y, w, widthPt = HAIRLINE_PT) {
  slide.addShape("line", { x, y, w, h: 0, line: { color, width: widthPt } });
}

function vr(slide, color, x, y, h, widthPt = HAIRLINE_PT) {
  slide.addShape("line", { x, y, w: 0, h, line: { color, width: widthPt } });
}

// Faint, evenly-spaced architectural grid — a deliberate module field, not a
// few stray lines. Vertical lines span the full height, horizontals span the
// region [x0, x1]; both are anchored to the right/top edges so the grid reads
// as intentional. Very low contrast (gridOnLight / gridOnDark) and fully
// on-canvas. On light title slides pass the empty right region so it stays
// clear of text; on dark divider/closing slides pass the full width (faint
// full-bleed).
const GRID_STEP = 0.5; // inches; 20-col x ~11-row module on a 16:9 slide
function gridField(slide, color, { x0 = 0, x1 = PAGE.W } = {}) {
  for (let x = x1; x >= x0 - 1e-6; x -= GRID_STEP) {
    vr(slide, color, Number(x.toFixed(3)), 0, PAGE.H);
  }
  for (let y = 0; y <= PAGE.H + 1e-6; y += GRID_STEP) {
    hr(slide, color, x0, Number(y.toFixed(3)), x1 - x0);
  }
}

// The notched plate: cut-corner rectangle, the single emphasis element.
function plate(slide, theme, { x, y, w, h, text, fill, color, size = 10 }) {
  const fitted = fitLine(text, { wIn: w - 0.2, size, minSize: 8 });
  slide.addText(truncate(fitted.text, 60), {
    shape: "snip1Rect",
    x,
    y,
    w,
    h,
    fill: { color: fill },
    line: { type: "none" },
    fontSize: fitted.size,
    fontFace: theme.monoFont,
    color,
    align: "center",
    valign: "middle",
  });
}

function addTitle(slide, theme, title, { color, y = MARGIN, w = CONTENT_W, x = MARGIN, align = "left" } = {}) {
  const fitted = fitBlock(title, { wIn: w, hIn: 0.62, size: 27, minSize: 18, bold: true, maxLines: 2 });
  slide.addText(fitted.text, {
    x,
    y,
    w,
    h: 0.62,
    fontSize: fitted.size,
    fontFace: theme.headerFont,
    bold: true,
    color: color || theme.text,
    align,
    valign: "top",
    margin: 0,
    fit: "shrink",
  });
}

// Display text for title/divider/closing slides: large, anchored low-left.
function displayText(slide, theme, text, { x, y, w, h, size, minSize, color }) {
  const fitted = fitBlock(text, { wIn: w, hIn: h, size, minSize, bold: true, maxLines: 2 });
  slide.addText(fitted.text, {
    x,
    y,
    w,
    h,
    fontSize: fitted.size,
    fontFace: theme.headerFont,
    bold: true,
    color,
    align: "left",
    valign: "bottom",
    margin: 0,
    fit: "shrink",
  });
}

function addBodyBullets(slide, theme, items, { x, y, w, h, color, size = 14 }) {
  const kept = items.slice(0, 6).map((t) => truncate(t, 160));
  const runs = kept.map((text, i) => ({
    text,
    options: { bullet: { indent: 12 }, breakLine: i < kept.length - 1, paraSpaceAfter: 8 },
  }));
  slide.addText(runs, {
    x,
    y,
    w,
    h,
    fontSize: size,
    fontFace: theme.bodyFont,
    color: color || theme.text,
    align: "left",
    valign: "top",
    margin: 0,
    fit: "shrink",
  });
}

function placeVisual(slide, theme, visual, region) {
  if (!visual || visual.type === "none" || !visual.type) return;
  if (visual.type === "image" || visual.type === "chart") {
    const img = { x: region.x, y: region.y, sizing: { type: "contain", w: region.w, h: region.h } };
    if (visual.data) img.data = visual.data;
    else if (visual.path) img.path = visual.path;
    else throw new Error(`visual type "${visual.type}" requires a path or data`);
    img.w = region.w;
    img.h = region.h;
    slide.addImage(img);
    return;
  }
  throw new Error(`unknown visual type "${visual.type}" (use "image", "chart", or "none")`);
}

// Normalize an image reference into pptxgenjs { path } or { data }. Accepts a
// file path string, a base64 data string ("image/png;base64,…"), or an object
// { path } / { data }. Returns null when nothing usable is given.
function imgSrc(ref) {
  if (!ref) return null;
  if (typeof ref === "object") return ref.data ? { data: ref.data } : ref.path ? { path: ref.path } : null;
  return ref.startsWith("image/") || ref.startsWith("data:") ? { data: ref } : { path: ref };
}

function columnRegions(n, { top, height, gap = 0.3 }) {
  const colW = (CONTENT_W - gap * (n - 1)) / n;
  return Array.from({ length: n }, (_, i) => ({
    x: MARGIN + i * (colW + gap),
    y: top,
    w: colW,
    h: height,
  }));
}

// Vertical hairlines on the interior boundaries of a column row.
function columnRules(slide, theme, cols, { y, h, color }) {
  for (let i = 1; i < cols.length; i++) {
    vr(slide, color || theme.hairline, cols[i].x - 0.15, y, h);
  }
}

// --- Components ---------------------------------------------------------------

// Opening slide: white field, faint grid right, massive ink headline anchored
// low-left, notched meta plate top-left. Display headlines read best in
// sentence case ending with a period ("Give your team superpowers.").
function titleSlide(pres, theme, { title, subtitle, meta } = {}) {
  const slide = pres.addSlide();
  slide.background = { color: theme.background };
  gridField(slide, theme.gridOnLight, { x0: 7.0, x1: PAGE.W });
  if (meta) {
    plate(slide, theme, {
      x: MARGIN,
      y: MARGIN,
      w: 2.9,
      h: 0.44,
      text: meta,
      fill: theme.primary,
      color: theme.onPrimary,
    });
  }
  displayText(slide, theme, title || "Untitled", {
    x: MARGIN,
    y: 2.1,
    w: 6.3,
    h: 2.25,
    size: 64,
    minSize: 36,
    color: theme.text,
  });
  if (subtitle) {
    slide.addText(truncate(subtitle, 120), {
      x: MARGIN,
      y: 4.5,
      w: 6.3,
      h: 0.5,
      fontSize: 16,
      fontFace: theme.bodyFont,
      color: theme.muted,
      valign: "top",
      margin: 0,
      fit: "shrink",
    });
  }
  return slide;
}

// Dark section break: near-black field, faint dark grid, huge display title
// low-left, monospace section label top-left.
function sectionDivider(pres, theme, { number, title, subtitle } = {}) {
  const slide = pres.addSlide();
  slide.background = { color: theme.darkField };
  gridField(slide, theme.gridOnDark, { x0: 0, x1: PAGE.W });
  if (number !== undefined && number !== null) {
    slide.addText(`SECTION ${String(number).padStart(2, "0")}`, {
      x: MARGIN,
      y: 0.55,
      w: 3.0,
      h: 0.3,
      fontSize: 11,
      fontFace: theme.monoFont,
      color: theme.onDarkMuted,
      valign: "middle",
      margin: 0,
      charSpacing: 2,
    });
  }
  displayText(slide, theme, title || "", {
    x: MARGIN,
    y: 2.3,
    w: 6.7,
    h: 1.9,
    size: 60,
    minSize: 34,
    color: theme.onDark,
  });
  if (subtitle) {
    slide.addText(truncate(subtitle, 140), {
      x: MARGIN,
      y: 4.4,
      w: 6.7,
      h: 0.55,
      fontSize: 14,
      fontFace: theme.bodyFont,
      color: theme.onDarkMuted,
      valign: "top",
      margin: 0,
      fit: "shrink",
    });
  }
  return slide;
}

// Numbered agenda rows separated by hairlines, like a technical index.
// Single column up to 5 items, two columns for 6-8.
function agendaSlide(pres, theme, { title = "Agenda", items = [] } = {}) {
  const slide = pres.addSlide();
  slide.background = { color: theme.background };
  addTitle(slide, theme, title);
  const kept = items.slice(0, 8).map((t) => truncate(t, 70));
  const twoCol = kept.length > 5;
  const perCol = twoCol ? Math.ceil(kept.length / 2) : kept.length;
  const rowH = Math.min(0.72, (CONTENT_BOTTOM - BODY_TOP - 0.05) / Math.max(perCol, 1));
  kept.forEach((item, i) => {
    const col = twoCol ? Math.floor(i / perCol) : 0;
    const row = twoCol ? i % perCol : i;
    const x = MARGIN + col * (CONTENT_W / 2 + 0.1);
    const y = BODY_TOP + 0.05 + row * rowH;
    const w = twoCol ? CONTENT_W / 2 - 0.4 : CONTENT_W;
    slide.addText(String(i + 1).padStart(2, "0"), {
      x,
      y,
      w: 0.55,
      h: rowH - 0.16,
      fontSize: 12,
      fontFace: theme.monoFont,
      color: theme.muted,
      valign: "middle",
      margin: 0,
    });
    slide.addText(item, {
      x: x + 0.7,
      y,
      w: w - 0.7,
      h: rowH - 0.16,
      fontSize: 15,
      fontFace: theme.bodyFont,
      color: theme.text,
      valign: "middle",
      margin: 0,
      fit: "shrink",
    });
    hr(slide, theme.hairline, x, y + rowH - 0.06, w);
  });
  return slide;
}

// Text column + one visual slot (image or chart PNG). With no visual, the
// columns separate with a single vertical hairline and whitespace.
// visualSide: "right" (default) or "left".
function twoColumn(pres, theme, { title, body = [], visual, visualSide = "right" } = {}) {
  const slide = pres.addSlide();
  slide.background = { color: theme.background };
  addTitle(slide, theme, title || "");
  const textW = 4.3;
  const visualW = CONTENT_W - textW - 0.4;
  const textX = visualSide === "left" ? MARGIN + visualW + 0.4 : MARGIN;
  const visualX = visualSide === "left" ? MARGIN : MARGIN + textW + 0.4;
  const h = CONTENT_BOTTOM - BODY_TOP;
  addBodyBullets(slide, theme, body, { x: textX, y: BODY_TOP + 0.1, w: textW, h: h - 0.1 });
  if (!visual || visual.type === "none" || !visual.type) {
    vr(slide, theme.hairline, visualSide === "left" ? textX - 0.2 : visualX - 0.2, BODY_TOP + 0.1, h - 0.3);
  } else {
    placeVisual(slide, theme, visual, { x: visualX, y: BODY_TOP, w: visualW, h });
  }
  return slide;
}

// Row of 2-4 items — bare monochrome icon (icon.js PNG rendered in ink color)
// or a large numeral — with a bold label and short description, columns
// separated by hairlines.
function iconRow(pres, theme, { title, items = [] } = {}) {
  const slide = pres.addSlide();
  slide.background = { color: theme.background };
  addTitle(slide, theme, title || "");
  const kept = items.slice(0, 4);
  const top = BODY_TOP + 0.15;
  const cols = columnRegions(kept.length || 1, { top, height: CONTENT_BOTTOM - top });
  columnRules(slide, theme, cols, { y: top + 0.1, h: 3.2 });
  kept.forEach((item, i) => {
    const col = cols[i];
    if (item.iconPath) {
      const d = 0.6;
      slide.addImage({ path: item.iconPath, x: col.x + col.w / 2 - d / 2, y: top, w: d, h: d });
    } else {
      slide.addText(String(i + 1), {
        x: col.x,
        y: top,
        w: col.w,
        h: 0.6,
        fontSize: 26,
        fontFace: theme.headerFont,
        bold: true,
        color: theme.text,
        align: "center",
        valign: "middle",
        margin: 0,
      });
    }
    const labelFit = fitBlock(item.label || "", { wIn: col.w - 0.2, hIn: 0.55, size: 14, minSize: 11, bold: true, maxLines: 2 });
    slide.addText(labelFit.text, {
      x: col.x + 0.1,
      y: top + 0.85,
      w: col.w - 0.2,
      h: 0.55,
      fontSize: labelFit.size,
      fontFace: theme.headerFont,
      bold: true,
      color: theme.text,
      align: "center",
      valign: "top",
      margin: 0,
      fit: "shrink",
    });
    if (item.desc) {
      slide.addText(truncate(item.desc, 130), {
        x: col.x + 0.1,
        y: top + 1.5,
        w: col.w - 0.2,
        h: Math.max(col.h - 1.55, 0.5),
        fontSize: 12,
        fontFace: theme.bodyFont,
        color: theme.muted,
        align: "center",
        valign: "top",
        margin: 0,
        fit: "shrink",
      });
    }
  });
  return slide;
}

// Row of 2-4 large-number callouts in rule-separated columns: display numeral,
// monospace label, optional description. Mark at most one stat `hero: true` to
// set it on the notched plate as the slide's single emphasis element.
function statCallouts(pres, theme, { title, stats = [] } = {}) {
  const slide = pres.addSlide();
  slide.background = { color: theme.background };
  addTitle(slide, theme, title || "");
  const kept = stats.slice(0, 4);
  if (kept.filter((s) => s.hero).length > 1) {
    throw new Error("statCallouts allows at most one stat with hero: true (the slide's single emphasis element)");
  }
  const cols = columnRegions(kept.length || 1, { top: 1.85, height: 2.7 });
  columnRules(slide, theme, cols, { y: 1.95, h: 2.55 });
  kept.forEach((stat, i) => {
    const col = cols[i];
    const hero = Boolean(stat.hero);
    if (hero) {
      slide.addShape("snip1Rect", {
        x: col.x - 0.08,
        y: 1.8,
        w: col.w + 0.16,
        h: 2.85,
        fill: { color: theme.primary },
        line: { type: "none" },
      });
    }
    const valueFit = fitLine(stat.value || "", { wIn: col.w - 0.2, size: 66, minSize: 34, bold: true });
    slide.addText(valueFit.text, {
      x: col.x,
      y: 1.95,
      w: col.w,
      h: 1.15,
      fontSize: valueFit.size,
      fontFace: theme.headerFont,
      bold: true,
      color: hero ? theme.onPrimary : theme.accentStrong,
      align: "center",
      valign: "middle",
      margin: 0,
    });
    slide.addText(truncate((stat.label || "").toUpperCase(), 36), {
      x: col.x,
      y: 3.25,
      w: col.w,
      h: 0.4,
      fontSize: 11,
      fontFace: theme.monoFont,
      color: hero ? theme.onPrimaryMuted : theme.muted,
      align: "center",
      valign: "top",
      charSpacing: 1,
      margin: 0,
      fit: "shrink",
    });
    if (stat.desc) {
      slide.addText(truncate(stat.desc, 100), {
        x: col.x,
        y: 3.75,
        w: col.w,
        h: 0.8,
        fontSize: 11,
        fontFace: theme.bodyFont,
        color: hero ? theme.onPrimaryMuted : theme.muted,
        align: "center",
        valign: "top",
        margin: 0,
        fit: "shrink",
      });
    }
  });
  return slide;
}

// Horizontal process flow of 3-5 steps: 1pt ink spine, small filled ink
// squares as markers, monospace step numbers, bold step titles.
function timeline(pres, theme, { title, steps = [] } = {}) {
  const slide = pres.addSlide();
  slide.background = { color: theme.background };
  addTitle(slide, theme, title || "");
  const kept = steps.slice(0, 5);
  const cols = columnRegions(kept.length || 1, { top: 1.95, height: CONTENT_BOTTOM - 1.95, gap: 0.25 });
  const spineY = 2.05;
  const sq = 0.12;
  if (kept.length > 1) {
    const first = cols[0].x + cols[0].w / 2;
    const last = cols[cols.length - 1].x + cols[cols.length - 1].w / 2;
    hr(slide, theme.text, first, spineY, last - first, 1);
  }
  kept.forEach((step, i) => {
    const col = cols[i];
    const cx = col.x + col.w / 2;
    slide.addShape("rect", {
      x: cx - sq / 2,
      y: spineY - sq / 2,
      w: sq,
      h: sq,
      fill: { color: theme.text },
      line: { type: "none" },
    });
    slide.addText(String(i + 1).padStart(2, "0"), {
      x: col.x,
      y: spineY + 0.2,
      w: col.w,
      h: 0.3,
      fontSize: 10,
      fontFace: theme.monoFont,
      color: theme.muted,
      align: "center",
      valign: "top",
      margin: 0,
    });
    const labelFit = fitBlock(step.label || "", { wIn: col.w - 0.1, hIn: 0.5, size: 14, minSize: 11, bold: true, maxLines: 2 });
    slide.addText(labelFit.text, {
      x: col.x,
      y: spineY + 0.6,
      w: col.w,
      h: 0.5,
      fontSize: labelFit.size,
      fontFace: theme.headerFont,
      bold: true,
      color: theme.text,
      align: "center",
      valign: "top",
      margin: 0,
      fit: "shrink",
    });
    if (step.desc) {
      slide.addText(truncate(step.desc, 110), {
        x: col.x,
        y: spineY + 1.2,
        w: col.w,
        h: Math.max(CONTENT_BOTTOM - (spineY + 1.25), 0.5),
        fontSize: 11,
        fontFace: theme.bodyFont,
        color: theme.muted,
        align: "center",
        valign: "top",
        margin: 0,
        fit: "shrink",
      });
    }
  });
  return slide;
}

// Half-bleed (image fills one half edge-to-edge, text-safe zone on the other)
// or full-bleed (image fills the slide, text on a solid dark bottom panel).
// image: { path } or { data }. bleed: "half" (default) or "full".
// side (half-bleed only): "right" (default) or "left".
function imageSlide(pres, theme, { title, body, image, bleed = "half", side = "right" } = {}) {
  const slide = pres.addSlide();
  if (bleed !== "half" && bleed !== "full") throw new Error(`imageSlide bleed must be "half" or "full" (got "${bleed}")`);
  if (side !== "left" && side !== "right") throw new Error(`imageSlide side must be "left" or "right" (got "${side}")`);
  const imgRef = imgSrc(image);
  if (!imgRef) throw new Error("imageSlide requires image { path } or { data }");
  if (bleed === "full") {
    slide.addImage({ ...imgRef, x: 0, y: 0, w: PAGE.W, h: PAGE.H, sizing: { type: "cover", w: PAGE.W, h: PAGE.H } });
    slide.addShape("rect", {
      x: 0,
      y: 3.55,
      w: PAGE.W,
      h: PAGE.H - 3.55,
      fill: { color: theme.darkField },
      line: { type: "none" },
    });
    const fitted = fitBlock(title || "", { wIn: CONTENT_W, hIn: 0.6, size: 26, minSize: 18, bold: true, maxLines: 1 });
    slide.addText(fitted.text, {
      x: MARGIN,
      y: 3.75,
      w: CONTENT_W,
      h: 0.6,
      fontSize: fitted.size,
      fontFace: theme.headerFont,
      bold: true,
      color: theme.onDark,
      valign: "top",
      margin: 0,
      fit: "shrink",
    });
    if (body) {
      slide.addText(truncate(Array.isArray(body) ? body.join(" ") : body, 160), {
        x: MARGIN,
        y: 4.45,
        w: CONTENT_W,
        h: 0.65,
        fontSize: 13,
        fontFace: theme.bodyFont,
        color: theme.onDarkMuted,
        valign: "top",
        margin: 0,
        fit: "shrink",
      });
    }
    return slide;
  }
  const imgW = 4.8;
  const imgX = side === "left" ? 0 : PAGE.W - imgW;
  const textX = side === "left" ? imgW + 0.5 : MARGIN;
  const textW = PAGE.W - imgW - 1.0;
  slide.background = { color: theme.background };
  slide.addImage({ ...imgRef, x: imgX, y: 0, w: imgW, h: PAGE.H, sizing: { type: "cover", w: imgW, h: PAGE.H } });
  addTitle(slide, theme, title || "", { x: textX, w: textW, y: 0.7 });
  if (body) {
    const items = Array.isArray(body) ? body : [body];
    addBodyBullets(slide, theme, items, { x: textX, y: 1.7, w: textW, h: CONTENT_BOTTOM - 1.7 });
  }
  return slide;
}

// Chart PNG (from charts.md / chart.py) as the dominant visual, with a
// hairline-separated takeaway block beside it.
function chartSlide(pres, theme, { title, chart, takeaway } = {}) {
  const slide = pres.addSlide();
  slide.background = { color: theme.background };
  if (!chart || (!chart.path && !chart.data)) throw new Error("chartSlide requires chart { path } or { data }");
  addTitle(slide, theme, title || "");
  const chartRegion = { x: MARGIN, y: BODY_TOP, w: 6.1, h: CONTENT_BOTTOM - BODY_TOP };
  placeVisual(slide, theme, { type: "chart", path: chart.path, data: chart.data }, chartRegion);
  if (takeaway) {
    const tx = MARGIN + 6.1 + 0.4;
    const tw = CONTENT_W - 6.1 - 0.4;
    vr(slide, theme.hairline, tx - 0.2, BODY_TOP + 0.15, CONTENT_BOTTOM - BODY_TOP - 0.45);
    slide.addText("KEY TAKEAWAY", {
      x: tx,
      y: BODY_TOP + 0.25,
      w: tw,
      h: 0.3,
      fontSize: 10,
      fontFace: theme.monoFont,
      color: theme.muted,
      charSpacing: 1,
      valign: "top",
      margin: 0,
    });
    slide.addText(truncate(takeaway, 180), {
      x: tx,
      y: BODY_TOP + 0.7,
      w: tw,
      h: 2.5,
      fontSize: 18,
      fontFace: theme.bodyFont,
      bold: true,
      color: theme.text,
      valign: "top",
      margin: 0,
      fit: "shrink",
    });
  }
  return slide;
}

// Large pull-quote framed by full-width hairline rules that hug the quote
// tightly, with the attribution just under the lower rule. The whole group
// (rule → quote → rule → attribution) is vertically centered in the content
// area — no large floating whitespace inside it.
function quoteSlide(pres, theme, { quote, attribution } = {}) {
  const slide = pres.addSlide();
  slide.background = { color: theme.background };

  const gapRule = 0.22; // rule ↔ quote breathing room
  const gapAttr = 0.16; // lower rule ↔ attribution
  const attrH = attribution ? 0.3 : 0;

  const fitted = fitBlock(quote || "", { wIn: CONTENT_W, hIn: 2.4, size: 28, minSize: 18, bold: false });
  const lines = estLines(fitted.text, CONTENT_W, fitted.size, false);
  const quoteH = Math.min(Math.max((lines * fitted.size * 1.28) / 72, 0.5), 2.6);

  const areaTop = BODY_TOP;
  const areaH = CONTENT_BOTTOM - areaTop;
  const groupH = gapRule + quoteH + gapRule + gapAttr + attrH;
  const top = areaTop + Math.max((areaH - groupH) / 2, 0);

  const quoteY = top + gapRule;
  const bottomRuleY = quoteY + quoteH + gapRule;

  hr(slide, theme.hairline, MARGIN, top, CONTENT_W);
  slide.addText(fitted.text, {
    x: MARGIN,
    y: quoteY,
    w: CONTENT_W,
    h: quoteH,
    fontSize: fitted.size,
    fontFace: theme.bodyFont,
    color: theme.text,
    valign: "middle",
    margin: 0,
    fit: "shrink",
  });
  hr(slide, theme.hairline, MARGIN, bottomRuleY, CONTENT_W);
  if (attribution) {
    slide.addText("— " + truncate(attribution, 70), {
      x: MARGIN,
      y: bottomRuleY + gapAttr,
      w: CONTENT_W,
      h: attrH,
      fontSize: 11,
      fontFace: theme.monoFont,
      color: theme.muted,
      valign: "top",
      margin: 0,
    });
  }
  return slide;
}

// Dark bookend: near-black field, white display text, faint dark grid, and an
// inverted notched plate carrying the call-to-action / contact line.
function closingSlide(pres, theme, { title = "Thank you.", subtitle, contact } = {}) {
  const slide = pres.addSlide();
  slide.background = { color: theme.darkField };
  gridField(slide, theme.gridOnDark, { x0: 0, x1: PAGE.W });
  displayText(slide, theme, title, {
    x: MARGIN,
    y: 1.95,
    w: 6.7,
    h: 1.7,
    size: 54,
    minSize: 32,
    color: theme.onDark,
  });
  if (subtitle) {
    slide.addText(truncate(subtitle, 120), {
      x: MARGIN,
      y: 3.8,
      w: 6.7,
      h: 0.55,
      fontSize: 16,
      fontFace: theme.bodyFont,
      color: theme.onDarkMuted,
      valign: "top",
      margin: 0,
      fit: "shrink",
    });
  }
  if (contact) {
    plate(slide, theme, {
      x: MARGIN,
      y: 4.5,
      w: 3.1,
      h: 0.44,
      text: contact,
      fill: theme.background,
      color: theme.text,
    });
  }
  return slide;
}

// Two side-by-side panels (before/after, pros/cons) split by a vertical
// hairline; each panel is a heading + bullet list. Use when contrasting two
// options or states in words (not text-vs-visual — that's twoColumn).
function comparisonSlide(pres, theme, { title, left, right } = {}) {
  const slide = pres.addSlide();
  slide.background = { color: theme.background };
  addTitle(slide, theme, title || "");
  const top = BODY_TOP + 0.1;
  const panelH = CONTENT_BOTTOM - top;
  const panelW = (CONTENT_W - 0.6) / 2;
  const rightX = MARGIN + panelW + 0.6;
  vr(slide, theme.hairline, MARGIN + panelW + 0.3, top, panelH);
  for (const [panel, x] of [[left, MARGIN], [right, rightX]]) {
    if (!panel) continue;
    const headFit = fitBlock(panel.heading || "", { wIn: panelW, hIn: 0.4, size: 16, minSize: 13, bold: true, maxLines: 1 });
    slide.addText(headFit.text, {
      x,
      y: top,
      w: panelW,
      h: 0.4,
      fontSize: headFit.size,
      fontFace: theme.headerFont,
      bold: true,
      color: theme.text,
      valign: "top",
      margin: 0,
      fit: "shrink",
    });
    addBodyBullets(slide, theme, panel.items || [], { x, y: top + 0.6, w: panelW, h: panelH - 0.6 });
  }
  return slide;
}

// 2x2 matrix with hairline axes and mono axis labels, one label per cell. Use
// for positioning / effort-impact style maps.
function quadrant(pres, theme, { title, xAxis = {}, yAxis = {}, cells = [] } = {}) {
  const slide = pres.addSlide();
  slide.background = { color: theme.background };
  addTitle(slide, theme, title || "");
  const x0 = MARGIN + 0.9;
  const x1 = PAGE.W - MARGIN;
  const y0 = BODY_TOP + 0.45;
  const y1 = CONTENT_BOTTOM - 0.35;
  const cx = (x0 + x1) / 2;
  const cy = (y0 + y1) / 2;
  vr(slide, theme.text, cx, y0, y1 - y0, 1);
  hr(slide, theme.text, x0, cy, x1 - x0, 1);
  // Axis labels (mono, gray), kept inside margins. fitLine shrinks/truncates
  // to a single line so long labels can't wrap out of the box.
  const mono = (text, x, y, w, align) => {
    const f = fitLine(truncate(text, 26), { wIn: w, size: 10, minSize: 8 });
    slide.addText(f.text, {
      x,
      y,
      w,
      h: 0.28,
      fontSize: f.size,
      fontFace: theme.monoFont,
      color: theme.muted,
      align,
      valign: "middle",
      margin: 0,
    });
  };
  if (yAxis.high) mono(yAxis.high, cx - 1.4, BODY_TOP + 0.12, 2.8, "center");
  if (yAxis.low) mono(yAxis.low, cx - 1.4, y1 + 0.05, 2.8, "center");
  if (xAxis.low) mono(xAxis.low, MARGIN, cy - 0.14, 1.25, "left");
  if (xAxis.high) mono(xAxis.high, x1 - 1.4, cy - 0.36, 1.4, "right");
  const centers = [
    [x0 + (cx - x0) / 2, y0 + (cy - y0) / 2],
    [cx + (x1 - cx) / 2, y0 + (cy - y0) / 2],
    [x0 + (cx - x0) / 2, cy + (y1 - cy) / 2],
    [cx + (x1 - cx) / 2, cy + (y1 - cy) / 2],
  ];
  cells.slice(0, 4).forEach((cell, i) => {
    if (!cell || !cell.label) return;
    const [ccx, ccy] = centers[i];
    const cellW = 3.2;
    const fit = fitBlock(cell.label, { wIn: cellW, hIn: 0.7, size: 14, minSize: 11, bold: true, maxLines: 2 });
    slide.addText(fit.text, {
      x: ccx - cellW / 2,
      y: ccy - 0.35,
      w: cellW,
      h: 0.7,
      fontSize: fit.size,
      fontFace: theme.headerFont,
      bold: true,
      color: theme.text,
      align: "center",
      valign: "middle",
      margin: 0,
      fit: "shrink",
    });
  });
  return slide;
}

// Horizontal sequence of 3-5 steps connected by thin ink arrows. Use for a
// non-dated flow / pipeline (timeline is for dated, chronological steps).
function processFlow(pres, theme, { title, steps = [] } = {}) {
  const slide = pres.addSlide();
  slide.background = { color: theme.background };
  addTitle(slide, theme, title || "");
  const kept = steps.slice(0, 5);
  const gap = 0.4;
  const cols = columnRegions(kept.length || 1, { top: BODY_TOP + 0.5, height: CONTENT_BOTTOM - BODY_TOP - 0.5, gap });
  const midY = BODY_TOP + 0.75;
  for (let i = 0; i < cols.length - 1; i++) {
    const ax = cols[i].x + cols[i].w + 0.06;
    const bx = cols[i + 1].x - 0.06;
    slide.addShape("line", {
      x: ax,
      y: midY,
      w: bx - ax,
      h: 0,
      line: { color: theme.text, width: 1.5, endArrowType: "triangle" },
    });
  }
  kept.forEach((step, i) => {
    const col = cols[i];
    const labelFit = fitBlock(step.label || "", { wIn: col.w - 0.1, hIn: 0.55, size: 15, minSize: 12, bold: true, maxLines: 2 });
    slide.addText(labelFit.text, {
      x: col.x,
      y: BODY_TOP + 0.45,
      w: col.w,
      h: 0.6,
      fontSize: labelFit.size,
      fontFace: theme.headerFont,
      bold: true,
      color: theme.text,
      align: "center",
      valign: "middle",
      margin: 0,
      fit: "shrink",
    });
    if (step.desc) {
      slide.addText(truncate(step.desc, 110), {
        x: col.x,
        y: BODY_TOP + 1.2,
        w: col.w,
        h: CONTENT_BOTTOM - (BODY_TOP + 1.25),
        fontSize: 11,
        fontFace: theme.bodyFont,
        color: theme.muted,
        align: "center",
        valign: "top",
        margin: 0,
        fit: "shrink",
      });
    }
  });
  return slide;
}

// A single oversized claim or number filling the slide, optional supporting
// line. Use when one idea deserves the whole slide.
function bigStatement(pres, theme, { statement, support } = {}) {
  const slide = pres.addSlide();
  slide.background = { color: theme.background };
  const h = support ? 2.9 : 3.4;
  const fit = fitBlock(statement || "", { wIn: CONTENT_W, hIn: h, size: 60, minSize: 30, bold: true, maxLines: 3 });
  slide.addText(fit.text, {
    x: MARGIN,
    y: 1.0,
    w: CONTENT_W,
    h,
    fontSize: fit.size,
    fontFace: theme.headerFont,
    bold: true,
    color: theme.text,
    align: "left",
    valign: "middle",
    margin: 0,
    fit: "shrink",
  });
  if (support) {
    slide.addText(truncate(support, 140), {
      x: MARGIN,
      y: 4.15,
      w: CONTENT_W,
      h: 0.6,
      fontSize: 16,
      fontFace: theme.bodyFont,
      color: theme.muted,
      valign: "top",
      margin: 0,
      fit: "shrink",
    });
  }
  return slide;
}

// Real data table: bold header row, hairline row separators (no zebra fills),
// mono for numeric columns. Caps ~8 rows x 5 cols with truncation. Use for
// tabular data that must stay legible as a grid.
function tableSlide(pres, theme, { title, headers = [], rows = [], numericCols = [] } = {}) {
  const slide = pres.addSlide();
  slide.background = { color: theme.background };
  addTitle(slide, theme, title || "");
  const maxCols = Math.min(headers.length || 1, 5);
  const cols = headers.slice(0, maxCols);
  const numeric = new Set(numericCols);
  const bodyRows = rows.slice(0, 8).map((r) => r.slice(0, maxCols));
  const top = BODY_TOP + 0.1;
  const tableH = CONTENT_BOTTOM - top;
  const rowH = Math.min(0.5, tableH / (bodyRows.length + 1));
  const colW = CONTENT_W / maxCols;
  const cellText = (text, ci, y, bold) => {
    const isNum = numeric.has(ci);
    slide.addText(truncate(String(text ?? ""), 26), {
      x: MARGIN + ci * colW + 0.05,
      y,
      w: colW - 0.1,
      h: rowH - 0.08,
      fontSize: 12,
      fontFace: isNum ? theme.monoFont : theme.bodyFont,
      bold: Boolean(bold),
      color: theme.text,
      align: isNum ? "right" : "left",
      valign: "middle",
      margin: 0,
      fit: "shrink",
    });
  };
  cols.forEach((h, ci) => cellText(h, ci, top, true));
  hr(slide, theme.text, MARGIN, top + rowH, CONTENT_W, 1);
  bodyRows.forEach((row, ri) => {
    const y = top + rowH * (ri + 1) + 0.04;
    cols.forEach((_, ci) => cellText(row[ci], ci, y, false));
    if (ri < bodyRows.length - 1) hr(slide, theme.hairline, MARGIN, y + rowH - 0.04, CONTENT_W);
  });
  return slide;
}

// 2xN dashboard grid of metrics (numeral + mono label), hairline separators.
// Use for a metrics dashboard (statCallouts is a single headline row).
function kpiGrid(pres, theme, { title, kpis = [] } = {}) {
  const slide = pres.addSlide();
  slide.background = { color: theme.background };
  addTitle(slide, theme, title || "");
  const kept = kpis.slice(0, 8);
  const perRow = kept.length <= 3 ? kept.length : Math.ceil(kept.length / 2);
  const rows = kept.length <= 3 ? 1 : 2;
  const top = BODY_TOP + 0.2;
  const gridH = CONTENT_BOTTOM - top;
  const rowH = gridH / rows;
  const colW = CONTENT_W / perRow;
  for (let c = 1; c < perRow; c++) vr(slide, theme.hairline, MARGIN + c * colW, top + 0.1, gridH - 0.2);
  if (rows > 1) hr(slide, theme.hairline, MARGIN, top + rowH, CONTENT_W);
  kept.forEach((kpi, i) => {
    const r = Math.floor(i / perRow);
    const c = i % perRow;
    const x = MARGIN + c * colW;
    const y = top + r * rowH;
    const valFit = fitLine(kpi.value || "", { wIn: colW - 0.3, size: 40, minSize: 22, bold: true });
    slide.addText(valFit.text, {
      x: x + 0.15,
      y: y + rowH * 0.14,
      w: colW - 0.3,
      h: rowH * 0.5,
      fontSize: valFit.size,
      fontFace: theme.headerFont,
      bold: true,
      color: theme.accentStrong,
      align: "left",
      valign: "top",
      margin: 0,
    });
    slide.addText(truncate((kpi.label || "").toUpperCase(), 34), {
      x: x + 0.15,
      y: y + rowH * 0.72,
      w: colW - 0.3,
      h: rowH * 0.24,
      fontSize: 10,
      fontFace: theme.monoFont,
      color: theme.muted,
      align: "left",
      valign: "top",
      charSpacing: 1,
      margin: 0,
      fit: "shrink",
    });
  });
  return slide;
}

// Horizontal ranked bars drawn with native shapes (label + ink bar + value),
// one bar in a stronger role. Use for a simple ranked comparison without a
// chart PNG.
function barCompare(pres, theme, { title, items = [] } = {}) {
  const slide = pres.addSlide();
  slide.background = { color: theme.background };
  addTitle(slide, theme, title || "");
  const kept = items.slice(0, 6);
  const top = BODY_TOP + 0.25;
  const areaH = CONTENT_BOTTOM - top;
  const rowH = Math.min(0.7, areaH / Math.max(kept.length, 1));
  const barH = Math.min(0.3, rowH * 0.45);
  const labelW = 2.4;
  const valueW = 1.0;
  const barX = MARGIN + labelW + 0.2;
  const barMaxW = PAGE.W - MARGIN - valueW - 0.15 - barX;
  const maxVal = Math.max(...kept.map((it) => Number(it.value) || 0), 1);
  kept.forEach((item, i) => {
    const y = top + i * rowH;
    const barY = y + (rowH - barH) / 2;
    slide.addText(truncate(item.label || "", 28), {
      x: MARGIN,
      y,
      w: labelW,
      h: rowH,
      fontSize: 13,
      fontFace: theme.bodyFont,
      color: theme.text,
      align: "left",
      valign: "middle",
      margin: 0,
      fit: "shrink",
    });
    const w = Math.max((Number(item.value) || 0) / maxVal * barMaxW, 0.05);
    slide.addShape("rect", {
      x: barX,
      y: barY,
      w,
      h: barH,
      fill: { color: item.highlight ? theme.accentStrong : theme.muted },
      line: { type: "none" },
    });
    slide.addText(truncate(String(item.display ?? item.value ?? ""), 10), {
      x: barX + barMaxW + 0.15,
      y,
      w: valueW,
      h: rowH,
      fontSize: 12,
      fontFace: theme.monoFont,
      bold: Boolean(item.highlight),
      color: theme.text,
      align: "right",
      valign: "middle",
      margin: 0,
      fit: "shrink",
    });
  });
  return slide;
}

// Profile grid: image slot (path) + name (bold) + role (mono/gray), 3-4
// across, hairline separators. Use for team / people slides.
function teamSlide(pres, theme, { title, members = [] } = {}) {
  const slide = pres.addSlide();
  slide.background = { color: theme.background };
  addTitle(slide, theme, title || "");
  const kept = members.slice(0, 4);
  const top = BODY_TOP + 0.2;
  const cols = columnRegions(kept.length || 1, { top, height: CONTENT_BOTTOM - top });
  columnRules(slide, theme, cols, { y: top + 0.1, h: CONTENT_BOTTOM - top - 0.2 });
  const d = 1.3;
  kept.forEach((m, i) => {
    const col = cols[i];
    const ix = col.x + col.w / 2 - d / 2;
    const src = imgSrc(m.photo);
    if (src) {
      slide.addImage({ ...src, x: ix, y: top, w: d, h: d, sizing: { type: "cover", w: d, h: d } });
    } else {
      slide.addShape("rect", { x: ix, y: top, w: d, h: d, fill: { type: "none" }, line: { color: theme.hairline, width: 1 } });
    }
    const nameFit = fitBlock(m.name || "", { wIn: col.w - 0.2, hIn: 0.4, size: 15, minSize: 12, bold: true, maxLines: 1 });
    slide.addText(nameFit.text, {
      x: col.x + 0.1,
      y: top + d + 0.2,
      w: col.w - 0.2,
      h: 0.4,
      fontSize: nameFit.size,
      fontFace: theme.headerFont,
      bold: true,
      color: theme.text,
      align: "center",
      valign: "top",
      margin: 0,
      fit: "shrink",
    });
    if (m.role) {
      slide.addText(truncate(m.role, 40), {
        x: col.x + 0.1,
        y: top + d + 0.65,
        w: col.w - 0.2,
        h: 0.5,
        fontSize: 11,
        fontFace: theme.monoFont,
        color: theme.muted,
        align: "center",
        valign: "top",
        margin: 0,
        fit: "shrink",
      });
    }
  });
  return slide;
}

// "Trusted by" grid of logo image slots (paths), evenly spaced, optional
// heading; graceful when fewer logos than cells. Use for social-proof walls.
function logoWall(pres, theme, { title = "Trusted by", logos = [] } = {}) {
  const slide = pres.addSlide();
  slide.background = { color: theme.background };
  addTitle(slide, theme, title || "");
  const kept = logos.slice(0, 12);
  const perRow = kept.length <= 4 ? Math.max(kept.length, 1) : 4;
  const rows = Math.ceil(kept.length / perRow);
  const top = BODY_TOP + 0.35;
  const areaH = CONTENT_BOTTOM - top;
  const rowH = areaH / Math.max(rows, 1);
  const colW = CONTENT_W / perRow;
  const cellW = colW * 0.7;
  const cellH = Math.min(rowH * 0.6, 0.9);
  kept.forEach((logo, i) => {
    const r = Math.floor(i / perRow);
    const c = i % perRow;
    const x = MARGIN + c * colW + (colW - cellW) / 2;
    const y = top + r * rowH + (rowH - cellH) / 2;
    const src = imgSrc(logo);
    if (src) slide.addImage({ ...src, x, y, w: cellW, h: cellH, sizing: { type: "contain", w: cellW, h: cellH } });
  });
  return slide;
}

// Testimonial: quote + an attributor block (photo/logo slot + name/company).
// Use for a single endorsement with a face/brand (quoteSlide is pure text).
function testimonialSlide(pres, theme, { quote, name, company, photo } = {}) {
  const slide = pres.addSlide();
  slide.background = { color: theme.background };
  const fit = fitBlock(quote || "", { wIn: CONTENT_W, hIn: 2.5, size: 26, minSize: 17, bold: false });
  slide.addText(fit.text, {
    x: MARGIN,
    y: 1.1,
    w: CONTENT_W,
    h: 2.6,
    fontSize: fit.size,
    fontFace: theme.bodyFont,
    color: theme.text,
    valign: "top",
    margin: 0,
    fit: "shrink",
  });
  const rowY = 4.15;
  const d = 0.7;
  hr(slide, theme.hairline, MARGIN, rowY - 0.15, CONTENT_W);
  let textX = MARGIN;
  const psrc = imgSrc(photo);
  if (psrc) {
    slide.addImage({ ...psrc, x: MARGIN, y: rowY, w: d, h: d, sizing: { type: "cover", w: d, h: d } });
    textX = MARGIN + d + 0.25;
  }
  if (name) {
    slide.addText(truncate(name, 40), {
      x: textX,
      y: rowY,
      w: CONTENT_W - (textX - MARGIN),
      h: 0.38,
      fontSize: 15,
      fontFace: theme.headerFont,
      bold: true,
      color: theme.text,
      valign: "middle",
      margin: 0,
      fit: "shrink",
    });
  }
  if (company) {
    slide.addText(truncate(company, 50), {
      x: textX,
      y: rowY + 0.38,
      w: CONTENT_W - (textX - MARGIN),
      h: 0.32,
      fontSize: 11,
      fontFace: theme.monoFont,
      color: theme.muted,
      valign: "middle",
      margin: 0,
      fit: "shrink",
    });
  }
  return slide;
}

// Plain content slide: title + single-column body (bullets or paragraphs),
// generous whitespace. Use for a straightforward text slide with no visual.
function contentSlide(pres, theme, { title, body = [] } = {}) {
  const slide = pres.addSlide();
  slide.background = { color: theme.background };
  addTitle(slide, theme, title || "");
  const w = 8.0;
  const top = BODY_TOP + 0.15;
  if (Array.isArray(body)) {
    addBodyBullets(slide, theme, body, { x: MARGIN, y: top, w, h: CONTENT_BOTTOM - top, size: 15 });
  } else {
    slide.addText(truncate(String(body), 700), {
      x: MARGIN,
      y: top,
      w,
      h: CONTENT_BOTTOM - top,
      fontSize: 15,
      fontFace: theme.bodyFont,
      color: theme.text,
      align: "left",
      valign: "top",
      paraSpaceAfter: 8,
      margin: 0,
      fit: "shrink",
    });
  }
  return slide;
}

// Action-focused closer: heading + 1-3 next-step items rendered as notched
// "button" plates. Use to drive next steps (closingSlide is the thank-you
// bookend). The plate set is this slide's single dominant element.
function ctaSlide(pres, theme, { title, actions = [] } = {}) {
  const slide = pres.addSlide();
  slide.background = { color: theme.background };
  const fit = fitBlock(title || "", { wIn: CONTENT_W, hIn: 1.4, size: 40, minSize: 26, bold: true, maxLines: 2 });
  slide.addText(fit.text, {
    x: MARGIN,
    y: 0.9,
    w: CONTENT_W,
    h: 1.4,
    fontSize: fit.size,
    fontFace: theme.headerFont,
    bold: true,
    color: theme.text,
    align: "left",
    valign: "bottom",
    margin: 0,
    fit: "shrink",
  });
  const kept = actions.slice(0, 3);
  const plateW = 3.4;
  const plateH = 0.6;
  const gap = 0.25;
  let y = 2.6;
  kept.forEach((action) => {
    plate(slide, theme, {
      x: MARGIN,
      y,
      w: plateW,
      h: plateH,
      text: action,
      fill: theme.primary,
      color: theme.onPrimary,
      size: 13,
    });
    y += plateH + gap;
  });
  return slide;
}

module.exports = {
  PAGE,
  MARGIN,
  makeTheme,
  defaultTheme,
  createPresentation,
  titleSlide,
  sectionDivider,
  agendaSlide,
  twoColumn,
  iconRow,
  statCallouts,
  timeline,
  imageSlide,
  chartSlide,
  quoteSlide,
  closingSlide,
  comparisonSlide,
  quadrant,
  processFlow,
  bigStatement,
  tableSlide,
  kpiGrid,
  barCompare,
  teamSlide,
  logoWall,
  testimonialSlide,
  contentSlide,
  ctaSlide,
};
