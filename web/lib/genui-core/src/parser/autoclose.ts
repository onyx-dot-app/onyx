/**
 * Auto-close unmatched brackets and strings for streaming partial input.
 *
 * When the LLM is mid-stream, the last line may be incomplete — e.g. an
 * unclosed `(`, `[`, `{`, or string. We append the matching closers so the
 * parser can produce a valid (partial) tree from what we have so far.
 */
export function autoClose(input: string): string {
  const closers: string[] = [];
  let inString: string | null = null;
  let escaped = false;

  for (let i = 0; i < input.length; i++) {
    const ch = input[i]!;

    if (escaped) {
      escaped = false;
      continue;
    }

    if (ch === "\\") {
      escaped = true;
      continue;
    }

    if (inString !== null) {
      if (ch === inString) {
        inString = null;
        closers.pop(); // remove the string closer
      }
      continue;
    }

    if (ch === '"' || ch === "'") {
      inString = ch;
      closers.push(ch);
      continue;
    }

    switch (ch) {
      case "(":
        closers.push(")");
        break;
      case "[":
        closers.push("]");
        break;
      case "{":
        closers.push("}");
        break;
      case ")":
      case "]":
      case "}":
        // Pop the matching opener if present
        if (closers.length > 0 && closers[closers.length - 1] === ch) {
          closers.pop();
        }
        break;
    }
  }

  // Append closers in reverse order
  return input + closers.reverse().join("");
}
