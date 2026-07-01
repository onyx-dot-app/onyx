/** Compact token count in the style of Claude Code / Codex: 15.5K, 148K, 1M. */
export function formatTokens(n: number): string {
  const oneDecimal = (x: number) => String(Math.round(x * 10) / 10);
  if (n < 1000) return String(n);
  // < 999_500 (not 1_000_000): values that would round to 1000K roll to "1M".
  if (n < 999_500) {
    const k = n / 1000;
    return `${k < 100 ? oneDecimal(k) : String(Math.round(k))}K`;
  }
  const m = n / 1_000_000;
  return `${m < 10 ? oneDecimal(m) : String(Math.round(m))}M`;
}
