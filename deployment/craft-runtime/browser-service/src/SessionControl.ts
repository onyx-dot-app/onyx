// Ported from T3 Code apps/server/src/preview/SessionControl.ts (MIT, see LICENSE-T3).

export type ControlReason = "interrupted" | "closed" | "humanControl";

export class BrowserControlInterrupted extends Error {
  readonly reason: ControlReason;

  constructor(
    message = "Browser control changed. Refresh the snapshot before trying again.",
    reason: ControlReason = "interrupted",
  ) {
    super(message);
    this.name = "BrowserControlInterrupted";
    this.reason = reason;
  }
}

const settle = (work: Promise<unknown>) =>
  work.then(
    () => undefined,
    () => undefined,
  );

const humanControl = () => new BrowserControlInterrupted("A human controls this tab.", "humanControl");

const notController = () => new BrowserControlInterrupted("You do not control this browser tab.");

type LatestEntry = {
  key: string;
  input: unknown;
  run: (input: never) => Promise<void>;
};

/** Reserves control immediately, but drains running work before the new owner can act. */
export class SessionControl {
  private readonly onGenerationChange: () => void;
  private tail: Promise<unknown> = Promise.resolve();
  private latestHuman: { entry: LatestEntry; result: Promise<void> } | null = null;
  private readonly handoff = new Set<Promise<void>>();
  private owner: string | null = null;
  private epoch = 0;
  private closed = false;

  constructor(onGenerationChange: () => void = () => {}) {
    this.onGenerationChange = onGenerationChange;
  }

  get controller() {
    return this.owner;
  }

  private enqueue<A>(run: () => Promise<A>): Promise<A> {
    this.latestHuman = null;
    const result = this.tail.then(run);
    this.tail = settle(result);
    return result;
  }

  /** Viewer input stays responsive, but control handoffs still drain its navigations. */
  trackUntilHandoff(work: Promise<unknown>) {
    const settled: Promise<void> = settle(work).finally(() => {
      this.handoff.delete(settled);
    });
    this.handoff.add(settled);
  }

  private assertOpen() {
    if (this.closed) throw new BrowserControlInterrupted("This browser tab is closed.", "closed");
  }

  private changeOwner(owner: string | null) {
    this.latestHuman = null;
    this.owner = owner;
    this.epoch++;
    this.onGenerationChange();
  }

  private async action<A>(
    allowed: () => boolean,
    run: () => Promise<A>,
    refusal: () => Error,
    deadlineMs?: number,
  ) {
    this.assertOpen();
    if (!allowed()) throw refusal();
    const epoch = this.epoch;
    return this.enqueue(async () => {
      this.assertOpen();
      if (!allowed()) throw refusal();
      if (epoch !== this.epoch) throw new BrowserControlInterrupted();
      if (deadlineMs !== undefined && performance.now() >= deadlineMs) {
        throw new DOMException(
          "This browser request expired before it could start.",
          "TimeoutError",
        );
      }
      return run();
    });
  }

  /** Work queued before a human takeover fails with humanControl when it reaches the queue head. */
  agent<A>(run: () => Promise<A>, deadlineMs?: number) {
    return this.action(() => this.owner === null, run, humanControl, deadlineMs);
  }

  /** Read without control or queueing so agents can observe without delaying human input. */
  observe<A>(run: () => Promise<A>) {
    this.assertOpen();
    return run();
  }

  human<A>(viewerId: string, run: () => Promise<A>) {
    return this.action(() => this.owner === viewerId, run, notController);
  }

  /**
   * Merge into only adjacent waiting work with the same key; the running action and
   * intervening actions keep their order. Work sharing a key must share its input type.
   */
  humanLatest<A>(
    viewerId: string,
    key: string,
    input: A,
    run: (input: A) => Promise<void>,
    merge: (waiting: A, next: A) => A = (_waiting, next) => next,
  ): Promise<void> {
    if (this.closed || this.owner !== viewerId) return this.human(viewerId, () => run(input));
    const latest = this.latestHuman;
    if (latest?.entry.key === key) {
      latest.entry.input = merge(latest.entry.input as A, input);
      latest.entry.run = run as (input: never) => Promise<void>;
      return latest.result;
    }
    const entry: LatestEntry = { key, input, run: run as (input: never) => Promise<void> };
    const result = this.human(viewerId, async () => {
      if (this.latestHuman?.entry === entry) this.latestHuman = null;
      await (entry.run as (input: unknown) => Promise<void>)(entry.input);
    });
    this.latestHuman = { entry, result };
    return result;
  }

  async take(viewerId: string) {
    this.assertOpen();
    if (this.owner !== null && this.owner !== viewerId) {
      throw new BrowserControlInterrupted("Another viewer controls this browser tab.");
    }
    if (this.owner !== viewerId) this.changeOwner(viewerId);
    return this.human(viewerId, async () => {});
  }

  async release(viewerId: string, afterDrain: () => Promise<void> = async () => {}) {
    this.assertOpen();
    if (this.owner !== viewerId) {
      throw new BrowserControlInterrupted(
        "Only the controlling viewer can release this browser tab.",
      );
    }
    this.changeOwner(null);
    await this.enqueue(async () => {
      await Promise.all(this.handoff);
      await afterDrain();
    });
  }

  async disconnect(viewerId: string, afterDrain?: () => Promise<void>) {
    if (!this.closed && this.owner === viewerId) await this.release(viewerId, afterDrain);
  }

  async close() {
    if (!this.closed) {
      this.closed = true;
      this.changeOwner(null);
    }
    await this.tail;
  }
}
