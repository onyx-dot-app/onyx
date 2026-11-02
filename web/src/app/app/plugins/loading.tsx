import { PluginsPageLoader } from "@/lib/plugins/components";

/**
 * Shown the moment the plugins page is opened, while it renders: Next
 * prefetches this shell, so the switch from a sidebar tab is instant.
 */
export default function Loading() {
  return <PluginsPageLoader />;
}
