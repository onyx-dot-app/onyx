/**
 * Formats a date string for display in the chat search menu.
 * Examples: "just now", "5 mins ago", "3 hours ago", "yesterday", "3 days ago", "October 23"
 */
export function formatDisplayTime(isoDate: string): string {
  const date = new Date(isoDate);
  const now = new Date();
  const diffMs = now.getTime() - date.getTime();

  if (diffMs < 0) {
    return "just now";
  }

  const diffMins = Math.floor(diffMs / (1000 * 60));
  const diffHours = Math.floor(diffMs / (1000 * 60 * 60));
  const diffDays = Math.floor(diffMs / (1000 * 60 * 60 * 24));

  // Just now (less than 1 minute)
  if (diffMins < 1) {
    return "just now";
  }

  // X mins ago (1-59 minutes)
  if (diffMins < 60) {
    return `${diffMins} ${diffMins === 1 ? "min" : "mins"} ago`;
  }

  // X hours ago (1-23 hours)
  if (diffHours < 24) {
    return `${diffHours} ${diffHours === 1 ? "hour" : "hours"} ago`;
  }

  // Check if yesterday
  const yesterday = new Date(now);
  yesterday.setDate(yesterday.getDate() - 1);
  if (
    date.getDate() === yesterday.getDate() &&
    date.getMonth() === yesterday.getMonth() &&
    date.getFullYear() === yesterday.getFullYear()
  ) {
    return "yesterday";
  }

  // X days ago (2-7 days)
  if (diffDays <= 7) {
    return `${diffDays} ${diffDays === 1 ? "day" : "days"} ago`;
  }

  // Month Day format (e.g., "October 23")
  return date.toLocaleDateString("en-US", {
    month: "long",
    day: "numeric",
  });
}
