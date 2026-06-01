// Mirrors web markdownUtils.processContent. Deviation: KaTeX/math escaping is
// omitted — mobile has no KaTeX, so math renders as plain text. Strips trailing
// INCOMPLETE citation markers so markdown-it never renders a half-arrived `[[N]](url`.

export function processContent(content: string): string {
  // [[N]](partial-url  — link opened, url not yet closed.
  content = content.replace(/\[\[\d+\]\]\([^)]*$/, "");
  // Lone trailing [[  / [[N  / [[N]  / [[N]]  (no paren yet) — incl. D/Q prefix.
  content = content.replace(/\[\[(?:[DQ]\s*)?\d*\]?\]?$/, "");

  // Unterminated trailing code fence -> tag plaintext so it renders as a code
  // block instead of leaking raw backticks until the closing fence arrives.
  const codeBlockRegex = /```(\w*)\n[\s\S]*?```|```[\s\S]*?$/g;
  const matches = content.match(codeBlockRegex);
  if (matches) {
    const lastMatch = matches[matches.length - 1];
    if (
      lastMatch &&
      !lastMatch.endsWith("```") &&
      !/```\w+/.test(lastMatch)
    ) {
      content = content.replace(
        lastMatch,
        lastMatch.replace("```", "```plaintext")
      );
    }
  }

  return content;
}
