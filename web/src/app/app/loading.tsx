/**
 * The /app pages' loading boundary. With it, Next prefetches each page's
 * shell, so leaving a page for another (More Agents, Plugins, Settings, or
 * back to a chat) switches the URL and the sidebar at once instead of
 * waiting for the server render. The chat view shows its own skeleton.
 */
export default function Loading() {
  return null;
}
