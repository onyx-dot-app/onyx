export function formatCitations(content: string): string {
  let processed = content;

  processed = processed.replace(/\[([QD])(\d+)\]/g, (match, type, number) => {
    const citationNumber = parseInt(number, 10);
    return `[[${type}${citationNumber}]]()`;
  });

  processed = processed.replace(/\{\{(\d+)\}\}/g, (match, p1) => {
    const citationNumber = parseInt(p1, 10);
    return `[[${citationNumber}]]()`;
  });

  processed = processed.replace(/\]\](?!\()/g, "]]()");

  return processed;
}
