/**
 * Derive display initials from a user's name or email.
 *
 * - If a name is provided, uses the first letter of the first two words.
 * - Falls back to the email local part, splitting on `.`, `_`, or `-`.
 * - Returns at most 2 uppercase characters.
 */
export function getInitials(name: string | null, email: string): string {
  if (name) {
    const parts = name.trim().split(/\s+/);
    if (parts.length >= 2) {
      return ((parts[0]?.[0] ?? "") + (parts[1]?.[0] ?? "")).toUpperCase();
    }
    return name.slice(0, 2).toUpperCase();
  }
  const local = email.split("@")[0];
  if (!local) return "?";
  const parts = local.split(/[._-]/);
  if (parts.length >= 2) {
    return ((parts[0]?.[0] ?? "") + (parts[1]?.[0] ?? "")).toUpperCase();
  }
  return local.slice(0, 2).toUpperCase();
}
