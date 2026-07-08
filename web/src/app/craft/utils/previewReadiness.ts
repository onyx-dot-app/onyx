export interface PreviewReadinessDecision {
  consecutiveUnready: number;
  remount: boolean;
}

/**
 * Decides when the preview iframe must be force-remounted, from a stream of
 * webapp readiness polls.
 *
 * An iframe that loaded while the dev server was down shows the static
 * offline page, which has no HMR client — nothing inside it can ever
 * recover, so the parent must remount it when the server comes (back) up.
 * This covers restore (the pod was replaced), first app creation (the port
 * is allocated before the dev server serves), and crash-restarts.
 *
 * A remount is signalled only on an unready -> ready transition, and only
 * after two consecutive unready polls: a single failed poll can be a flaky
 * probe (e.g. a 2s timeout during a heavy compile) where the page is still
 * live and HMR-connected — remounting then would needlessly reload it.
 */
export function nextPreviewReadiness(
  consecutiveUnready: number,
  ready: boolean
): PreviewReadinessDecision {
  if (!ready) {
    return { consecutiveUnready: consecutiveUnready + 1, remount: false };
  }
  return { consecutiveUnready: 0, remount: consecutiveUnready >= 2 };
}
