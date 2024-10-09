export function extractCodeText(
  node: any,
  content: string,
  children: React.ReactNode
): string {
  let codeText: string | null = null;
  if (
    node?.position?.start?.offset != null &&
    node?.position?.end?.offset != null
  ) {
    codeText = content.slice(
      node.position.start.offset,
      node.position.end.offset
    );
    codeText = codeText.trim();

    // Find the last occurrence of closing backticks
    const lastBackticksIndex = codeText.lastIndexOf("```");
    if (lastBackticksIndex !== -1) {
      codeText = codeText.slice(0, lastBackticksIndex + 3);
    }

    // Remove the language declaration and trailing backticks
    const codeLines = codeText.split("\n");
    if (codeLines.length > 1 && codeLines[0].trim().startsWith("```")) {
      codeLines.shift(); // Remove the first line with the language declaration
      if (codeLines[codeLines.length - 1]?.trim() === "```") {
        codeLines.pop(); // Remove the last line with the trailing backticks
      }

      const minIndent = codeLines
        .filter((line) => line.trim().length > 0)
        .reduce((min, line) => {
          const match = line.match(/^\s*/);
          return Math.min(min, match ? match[0].length : 0);
        }, Infinity);

      const formattedCodeLines = codeLines.map((line) => line.slice(minIndent));
      codeText = formattedCodeLines.join("\n");
    }
  } else {
    // Fallback if position offsets are not available
    codeText = children?.toString() || null;
  }

  return codeText || "";
}
