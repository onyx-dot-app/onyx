import { firstStrongTextDir } from "@/lib/rehypeDirection";

// Initials are a Latin-script habit. Cursive RTL scripts join adjacent
// letters into word fragments and CJK has no initials at all, so those
// names show a single grapheme of the display name instead.
const CJK =
  /[\p{Script=Han}\p{Script=Hiragana}\p{Script=Katakana}\p{Script=Hangul}]/u;
const LETTER = /\p{L}/u;
const MARK = /\p{M}/u;
// Viramas glue the following consonant into the same cluster.
const VIRAMA =
  /[\u094D\u09CD\u0A4D\u0ACD\u0B4D\u0BCD\u0C4D\u0CCD\u0D4D\u0DCA\u1039\u1B44\uA9C0]/u;

// Grapheme-cluster segmentation keeps surrogate pairs, emoji, and
// mark-bearing scripts intact where slice() would corrupt them.
function graphemes(value: string, max: number): string[] {
  if (typeof Intl !== "undefined" && "Segmenter" in Intl) {
    const out: string[] = [];
    const segments = new Intl.Segmenter(undefined, {
      granularity: "grapheme",
    }).segment(value);
    for (const segment of segments) {
      out.push(segment.segment);
      if (out.length >= max) break;
    }
    return out;
  }
  // Legacy fallback: fold combining marks, and consonants that follow a
  // virama, into the previous cluster so decomposed accents and Indic
  // conjuncts survive without Intl.Segmenter.
  const out: string[] = [];
  let joinNext = false;
  for (const char of value) {
    if (out.length > 0 && (joinNext || MARK.test(char))) {
      out[out.length - 1] += char;
    } else if (out.length < max) {
      out.push(char);
    } else {
      break;
    }
    joinNext = VIRAMA.test(char);
  }
  return out;
}

function firstGrapheme(value: string): string {
  return graphemes(value, 1)[0] ?? "";
}

/** True when the glyph is one grapheme, so avatars can size it up. */
export function isSingleGrapheme(value: string): boolean {
  return graphemes(value, 2).length === 1;
}

// Avatar glyph for a name: `maxLetters` uppercased initials for Latin
// scripts, one grapheme for RTL and CJK names, null so callers fall back.
export function nameInitials(name: string, maxLetters: number): string | null {
  const trimmed = name.trim();
  if (!trimmed) return null;

  const lead = firstGrapheme(trimmed);
  if (firstStrongTextDir(trimmed) === "rtl" || CJK.test(lead)) {
    return LETTER.test(lead) ? lead : null;
  }

  // Every taken slot must be a letter, so callers can fall back to
  // their email or icon path instead of showing a partial glyph.
  const words = trimmed.split(/\s+/);
  const slots =
    words.length >= 2 || maxLetters === 1
      ? words.slice(0, maxLetters).map(firstGrapheme)
      : graphemes(trimmed, maxLetters);
  if (!slots.every((grapheme) => LETTER.test(grapheme))) return null;
  // One glyph per slot: uppercasing can expand (ß becomes SS), so each
  // slot keeps only the first grapheme of its uppercased form.
  return slots
    .map((grapheme) => firstGrapheme(grapheme.toUpperCase()))
    .join("");
}
