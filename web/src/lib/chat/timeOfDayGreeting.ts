/**
 * Time-of-day greeting helper used by the redesigned home-page hero.
 *
 * Splits the day into Morning / Afternoon / Evening at 5am / 12pm / 5pm
 * (local time). Pure function so it can be called both during SSR and
 * after hydration without producing a mismatch — callers should still
 * gate on a `useEffect`-set state if they care about the exact bucket
 * matching the user's local clock at render time.
 */
export function getTimeOfDayGreeting(now: Date = new Date()): string {
  const hour = now.getHours();
  if (hour < 5) return "Good Evening";
  if (hour < 12) return "Good Morning";
  if (hour < 17) return "Good Afternoon";
  return "Good Evening";
}

/**
 * Pick the operator's display first name from the user object's
 * personalization data. Falls back to the email's local-part split on
 * the first dot (covers `jane.doe@…` → "Jane") and finally to the
 * generic "there" so the greeting is never empty.
 */
export function operatorFirstName(user: {
  personalization?: { name?: string | null } | null;
  email?: string | null;
} | null | undefined): string {
  const personal = user?.personalization?.name?.trim();
  if (personal) return personal.split(" ")[0] ?? personal;

  const email = user?.email;
  if (email) {
    const local = email.split("@")[0] ?? "";
    const first = local.split(/[._-]/)[0] ?? "";
    if (first) return first.charAt(0).toUpperCase() + first.slice(1);
  }
  return "there";
}
