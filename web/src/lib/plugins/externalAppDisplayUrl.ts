export function externalAppDisplayUrl(patterns: readonly string[]): string {
  const origins = patterns.flatMap((pattern) => {
    const match = /^\^?(https?):\/\/([^/$]+)(?:\/|\$|$)/.exec(pattern);
    if (!match) return [];
    const [, protocol, authority] = match;
    if (!protocol || !authority) return [];
    const host = authority.replace(/\\\./g, ".");
    if (!/^[a-zA-Z0-9-]+(?:\.[a-zA-Z0-9-]+)*(?::[0-9]+)?$/.test(host)) {
      return [];
    }
    try {
      return [new URL(`${protocol}://${host}`).origin];
    } catch {
      return [];
    }
  });
  return [...new Set(origins)].join(", ");
}
