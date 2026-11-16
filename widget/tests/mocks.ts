import { spyOn } from "bun:test";

/** Answers every fetch with `respond` until the test's `mock.restore()`. */
export const mockFetch = (
  respond: (input: RequestInfo | URL, init?: RequestInit) => Promise<Response>
) =>
  spyOn(globalThis, "fetch").mockImplementation(
    Object.assign(respond, { preconnect: globalThis.fetch.preconnect })
  );

/**
 * Runs every timer with the delay that `delay` maps its own to, until the
 * test's `mock.restore()`.
 */
export const mockTimeouts = (
  delay: (ms: number | undefined) => number | undefined
) => {
  const setTimer = globalThis.setTimeout;
  const shortened = (
    callback: TimerHandler,
    ms?: number,
    ...args: unknown[]
  ): number => setTimer(callback, delay(ms), ...args);
  // `typeof setTimeout` merges the DOM and Node overloads, whose handler and
  // return types differ, so no single function signature implements both.
  return spyOn(globalThis, "setTimeout").mockImplementation(
    Object.assign(shortened, {
      __promisify__: setTimer.__promisify__,
    }) as typeof setTimeout
  );
};
