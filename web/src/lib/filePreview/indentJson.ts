// A string, a number or literal, or one punctuation character. The text has
// passed JSON.parse, so whitespace between tokens is all that the search skips.
const JSON_TOKEN = /"(?:[^"\\]+|\\.)*"|[^\s"{}[\],:]+|\S/g;

// Indentation grows with the square of the nesting depth, so a small, deeply
// nested file could become a huge text. Past this size the source shows.
const MAX_INDENTED_CHARACTERS = 20_000_000;

/**
 * Indents single-line JSON by two spaces a level. It copies each token from
 * the source and never rebuilds values, so numbers, key order and duplicate
 * keys stay as written. Text with line breaks, text that is not JSON, and
 * text that would indent past `MAX_INDENTED_CHARACTERS` come back unchanged.
 */
export function indentJson(text: string): string {
  if (/[\r\n]/.test(text.trim())) return text;
  try {
    JSON.parse(text);
  } catch {
    return text;
  }
  const parts: string[] = [];
  let size = 0;
  const append = (piece: string) => {
    parts.push(piece);
    size += piece.length;
  };
  let depth = 0;
  // An empty object or array stays on one line
  let afterOpen = false;
  for (const token of text.match(JSON_TOKEN) ?? []) {
    if (token === "}" || token === "]") {
      depth--;
      append(afterOpen ? token : "\n" + "  ".repeat(depth) + token);
      afterOpen = false;
    } else {
      if (afterOpen) append("\n" + "  ".repeat(depth));
      afterOpen = token === "{" || token === "[";
      if (afterOpen) depth++;
      append(
        token === ","
          ? ",\n" + "  ".repeat(depth)
          : token === ":"
            ? ": "
            : token
      );
    }
    if (size > MAX_INDENTED_CHARACTERS) return text;
  }
  return parts.join("");
}
