import { nextPreviewReadiness } from "@/app/craft/utils/previewReadiness";

/** Folds a sequence of readiness polls, returning which polls signalled a remount. */
function remountsFor(polls: boolean[]): number[] {
  const remountIndexes: number[] = [];
  let consecutiveUnready = 0;
  polls.forEach((ready, index) => {
    const decision = nextPreviewReadiness(consecutiveUnready, ready);
    consecutiveUnready = decision.consecutiveUnready;
    if (decision.remount) remountIndexes.push(index);
  });
  return remountIndexes;
}

describe("nextPreviewReadiness", () => {
  it("remounts exactly once when a booting dev server comes up", () => {
    // First app creation / restore: the iframe captured the offline page
    // (no HMR client), so the first healthy poll must trigger a remount —
    // and continued healthy polls must not remount again.
    expect(remountsFor([false, false, false, true, true, true])).toEqual([3]);
  });

  it("never remounts while the server stays healthy", () => {
    expect(remountsFor([true, true, true, true])).toEqual([]);
  });

  it("ignores a single flaky probe", () => {
    // One timed-out probe during a heavy compile: the page is still live and
    // HMR-connected, so reloading it would throw away state for no reason.
    expect(remountsFor([true, false, true, true])).toEqual([]);
  });

  it("remounts after each genuine outage, not once globally", () => {
    // Two dev-server restarts in one session (e.g. crash then dep install).
    expect(
      remountsFor([false, false, true, false, false, false, true])
    ).toEqual([2, 6]);
  });
});
