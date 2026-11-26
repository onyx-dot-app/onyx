// Ported from T3 Code apps/server/src/preview/ServerBrowserPage.ts (MIT, see LICENSE-T3).

import * as NodeCrypto from "node:crypto";
import type { CDPSession, Frame, Locator, Page } from "playwright-core";
import { OperationError, withActionabilityReason } from "./errors.ts";

const noop = () => {};

export const DEFAULT_TIMEOUT_MS = 15_000;
const MAX_EVALUATION_BYTES = 64_000;
export const MAX_SNAPSHOT_CHARS = 20_000;
const SCREENSHOT_TIMEOUT_MS = 3_000;
const WAIT_POLL_MS = 100;
const TARGET_COUNT_MS = 250;
const MAX_TARGET_CHARS = 200;
const SNAPSHOT_TIMEOUT_MS = 10_000;
// Snapshot time kept for the steps after the aria tree, and for each unread iframe.
const SNAPSHOT_MARGIN_MS = 2_000;
const FRAME_ANSWER_MS = 1_000;

export type Target = { readonly ref?: string | undefined; readonly selector?: string | undefined };
export type Point = { readonly x: number; readonly y: number };
type Timed = { readonly timeoutMs: number };

type ClickInput = Target &
  Timed & {
    readonly x?: number | undefined;
    readonly y?: number | undefined;
    readonly button?: "left" | "right" | "middle" | undefined;
    readonly clickCount?: number | undefined;
  };
type TypeInput = Target & Timed & { readonly text: string; readonly clear?: boolean | undefined };
type HoverInput = Target &
  Timed & { readonly x?: number | undefined; readonly y?: number | undefined };
type SelectInput = Target & Timed & { readonly values: ReadonlyArray<string> };
type DragInput = Timed & { readonly source: Target; readonly target: Target };
type PressInput = { readonly key: string; readonly modifiers?: ReadonlyArray<string> | undefined };
type ScrollInput = Target & {
  readonly deltaX?: number | undefined;
  readonly deltaY?: number | undefined;
};
export type UploadInput = Target & Timed & { readonly paths: ReadonlyArray<string> };
export type WaitForInput = Target &
  Timed & { readonly text?: string | undefined; readonly urlIncludes?: string | undefined };

const pageRefs = new WeakMap<Page, { generation: string; refs: Map<string, string> }>();
// A runtime namespace keeps refs from an earlier service process from aliasing.
const refNamespace = NodeCrypto.randomBytes(2).toString("hex");
let snapshotSequence = 0;
const nextRefGeneration = () => `${refNamespace}${(++snapshotSequence).toString(36)}`;

/** A takeover revokes previously issued refs even when the document stays unchanged. */
export const invalidateRefs = (page: Page) => {
  const state = pageRefs.get(page);
  if (state) {
    state.generation = nextRefGeneration();
    state.refs.clear();
  }
};

const refsFor = (page: Page) => {
  let state = pageRefs.get(page);
  if (!state) {
    state = { generation: nextRefGeneration(), refs: new Map<string, string>() };
    pageRefs.set(page, state);
  }
  return state;
};

const staleRef = () =>
  new OperationError(
    "stale_ref",
    "This element ref is stale or belongs to another tab. Take a fresh snapshot and use its refs.",
  );

const refLocator = (page: Page, raw: string) => {
  const ref = raw.trim().replace(/^\[?(?:aria-)?ref=/, "").replace(/\]$/, "");
  const nativeRef = pageRefs.get(page)?.refs.get(ref);
  if (nativeRef === undefined) throw staleRef();
  return page.locator(`aria-ref=${nativeRef}`);
};

const targetLocator = (page: Page, input: Target): Locator | null => {
  if (input.ref !== undefined) return refLocator(page, input.ref);
  const selector = input.selector;
  if (selector === undefined) return null;
  const engines = selector.replace(
    /\\.|"(?:\\.|[^"\\])*"|'(?:\\.|[^'\\])*'|`(?:\\.|[^`\\])*`/g,
    " ",
  );
  if (/(?:^|>>)\s*\*?aria-ref\s*=/.test(engines)) {
    const ref = /^\s*aria-ref\s*=\s*(\S+)\s*$/.exec(selector)?.[1];
    if (ref === undefined) throw staleRef();
    return refLocator(page, ref);
  }
  // Playwright's strict locators reject ambiguous controls rather than acting on row one.
  return page.locator(selector);
};

const describeTarget = (input: Target) => JSON.stringify(input.ref ?? input.selector);

export type PointerReporter = (point: Point, phase: "move" | "click") => Promise<void>;
const noPointer: PointerReporter = async () => {};

// Locator.scrollIntoViewIfNeeded resolves its node once and fails when the page replaces it; the
// input actions after it re-resolve, so the scroll does too, within the same timeout.
const DETACHED = /^locator\.scrollIntoViewIfNeeded: Element is not attached to the DOM(?:\n|$)/;

const scrollIntoView = async (locator: Locator, timeout: number) => {
  const deadline = Date.now() + timeout;
  for (;;) {
    try {
      return await locator.scrollIntoViewIfNeeded({ timeout: Math.max(1, deadline - Date.now()) });
    } catch (cause) {
      if (!(cause instanceof Error && DETACHED.test(cause.message)) || Date.now() >= deadline) {
        throw cause;
      }
    }
  }
};

const targetPoint = async (
  page: Page,
  locator: Locator | null,
  input: { readonly x?: number | undefined; readonly y?: number | undefined },
  timeout: () => number,
): Promise<Point> => {
  if (locator === null) return { x: input.x ?? 0, y: input.y ?? 0 };
  await scrollIntoView(locator, timeout());
  const box = await locator.boundingBox({ timeout: timeout() });
  if (box) return { x: box.x + box.width / 2, y: box.y + box.height / 2 };
  const viewport = page.viewportSize();
  return { x: (viewport?.width ?? 0) / 2, y: (viewport?.height ?? 0) / 2 };
};

export const TITLE_LIMIT = 512;

/**
 * Reads the main frame's URL and title, cut in an isolated world: a whole title can be larger
 * than one CDP message, which would close the browser connection. Chromium keeps one world per
 * name and document, so a new document gets a new contextId.
 */
export const readPageState = async (
  cdp: CDPSession,
): Promise<{ url: string; title: string; contextId: number }> => {
  const { frameTree } = await cdp.send("Page.getFrameTree");
  const world = await cdp.send("Page.createIsolatedWorld", {
    frameId: frameTree.frame.id,
    worldName: "onyx-browser",
  });
  const { result, exceptionDetails } = await cdp.send("Runtime.evaluate", {
    contextId: world.executionContextId,
    expression: `({ url: location.href, title: document.title.slice(0, ${TITLE_LIMIT}) })`,
    returnByValue: true,
  });
  if (exceptionDetails) throw new Error("The page state could not be read.");
  return { ...(result.value as { url: string; title: string }), contextId: world.executionContextId };
};

const MASKED_VALUE = "••••••••";

/**
 * A `data:` URL carries its content, which can be a whole file. Keeps only the media type: the
 * payload can hold any character and parameters are page-chosen too.
 */
export const withoutDataPayload = (url: string) => {
  const value = url
    .replace(/^["']/, "")
    .replace(/\\(x[\da-f]{2}|u[\da-f]{4}|.)/gi, (_escape, code: string) =>
      code.length > 1
        ? String.fromCharCode(Number.parseInt(code.slice(1), 16))
        : (({ t: "\t", n: "\n", r: "\r", '"': '"', "\\": "\\" }) as Record<string, string>)[code] ??
          "\u0001",
    )
    .replace(/[\t\n\r]/g, "")
    .replace(/^[\u0000-\u0020]+/, "");
  const parsed = /^data:([^,;]*)/i.exec(value);
  if (!parsed) return url;
  const type = (parsed[1] ?? "").trim();
  const mediaType = /^[\w.+-]{1,64}\/[\w.+-]{1,64}$/.test(type) ? type : "";
  return `data:${mediaType},…`;
};

const withoutTreeDataPayloads = (tree: string) =>
  tree
    .split("\n")
    .map((line) => {
      const url = /^(\s*- \/url: )(.*)$/s.exec(line);
      return url ? (url[1] ?? "") + withoutDataPayload(url[2] ?? "") : line;
    })
    .join("\n");

// Include password and CSS-masked text in open shadow roots, normalized like accessible text.
const DOTTED_SCRIPT = `(() => {
  const values = [];
  const visit = (root) => {
    for (const element of root.querySelectorAll("*")) {
      if (element.shadowRoot) visit(element.shadowRoot);
      const field = element.localName === "input" || element.localName === "textarea";
      if (!field && !element.isContentEditable) continue;
      const dots = getComputedStyle(element).getPropertyValue("-webkit-text-security");
      if (element.type !== "password" && (dots === "none" || dots === "")) continue;
      for (const value of field ? [element.value, element.defaultValue] : [element.textContent ?? ""])
        values.push(value, value.replace(/[\\u200b\\u00ad]/g, "").trim().replace(/\\s+/g, " "));
    }
  };
  visit(document);
  return [...new Set(values.filter((value) => value.trim()))];
})()`;

const pageChanged = () =>
  new OperationError("failed", "The page changed while capturing its snapshot. Take another snapshot.");

const snapshotTimedOut = () =>
  new OperationError(
    "timeout",
    `Snapshot capture timed out after ${SNAPSHOT_TIMEOUT_MS}ms. Try the snapshot again.`,
  );

const frameUnanswered = () =>
  new OperationError(
    "timeout",
    `A frame on the page didn't answer within ${FRAME_ANSWER_MS}ms, so its content couldn't be checked for hidden values. Try the snapshot again.`,
  );

const isTimeout = (cause: unknown) => cause instanceof Error && cause.name === "TimeoutError";

const VALUE_TOO_LONG = "A password field holds a value too long to hide, so no snapshot was taken.";

/** Reuse one CDP session per out-of-process frame across snapshots. */
const frameSessions = new WeakMap<Frame, Promise<CDPSession>>();

/** Returns undefined on failure or frame timeout. */
const answered = <A>(promise: Promise<A>) => {
  let timer: ReturnType<typeof setTimeout> | undefined;
  const late = new Promise<undefined>((resolve) => {
    timer = setTimeout(() => resolve(undefined), FRAME_ANSWER_MS);
  });
  return Promise.race([promise.catch(() => undefined), late]).finally(() => clearTimeout(timer));
};

type Reader = { readonly frames: ReadonlyArray<Frame>; readonly read: () => Promise<Array<string>> };

/** Isolated worlds prevent spoofing. Missing own-frame reads or changed frames fail; other missing reads return undefined. */
const openReaders = async (page: Page, cdp: CDPSession) => {
  const frames = page.frames();
  const owners = new Map<Frame, CDPSession | undefined>(
    await Promise.all(
      frames.map(async (frame): Promise<[Frame, CDPSession | undefined]> => {
        if (frame === page.mainFrame()) return [frame, cdp];
        const session = frameSessions.get(frame) ?? page.context().newCDPSession(frame);
        frameSessions.set(frame, session);
        try {
          return [frame, await session];
        } catch {
          frameSessions.delete(frame);
          return [frame, undefined];
        }
      }),
    ),
  );
  const ownerOf = (frame: Frame): CDPSession | null => {
    const owner = owners.get(frame);
    if (owner !== undefined) return owner;
    const parent = frame.parentFrame();
    return parent ? ownerOf(parent) : null;
  };
  const sessionReader = (frame: Frame, session: CDPSession): Reader => {
    const owned = frames.filter((each) => ownerOf(each) === session);
    const open = async () => {
      const { frameTree } = await session.send("Page.getFrameTree");
      const ids = (node: typeof frameTree): Array<string> => [
        node.frame.id,
        ...(node.childFrames ?? []).flatMap(ids),
      ];
      // A frame Playwright knows but this session doesn't would go unread.
      if (ids(frameTree).length !== owned.length) throw pageChanged();
      return Promise.all(
        ids(frameTree).map(async (frameId) => {
          const world = await session.send("Page.createIsolatedWorld", {
            frameId,
            worldName: "onyx-browser",
          });
          return world.executionContextId;
        }),
      );
    };
    let contexts: ReturnType<typeof open> | undefined;
    const read = async () => {
      const values = (contexts ??= open()).then((ids) =>
        Promise.all(
          ids.map(async (contextId) => {
            const { result, exceptionDetails } = await session.send("Runtime.evaluate", {
              contextId,
              expression: DOTTED_SCRIPT,
              returnByValue: true,
            });
            if (exceptionDetails) throw pageChanged();
            return result.value as Array<string>;
          }),
        ),
      );
      try {
        return (await values).flat();
      } catch (cause) {
        // The frame may have moved to another process; the next snapshot opens a new session.
        if (session !== cdp) {
          frameSessions.delete(frame);
          void session.detach().catch(noop);
        }
        throw cause;
      }
    };
    return { frames: owned, read };
  };
  const readers: Array<Reader> = [
    sessionReader(page.mainFrame(), cdp),
    ...frames.flatMap((frame): Array<Reader> => {
      const owner = owners.get(frame);
      if (owner) return owner === cdp ? [] : [sessionReader(frame, owner)];
      const own = () => frame.evaluate(DOTTED_SCRIPT) as Promise<Array<string>>;
      return ownerOf(frame) === null ? [{ frames: [frame], read: own }] : [];
    }),
  ];
  return {
    readers,
    read: async (before?: ReadonlyArray<unknown>) => {
      const now = page.frames();
      if (now.length !== frames.length || now.some((frame, i) => frame !== frames[i])) {
        throw pageChanged();
      }
      return Promise.all(
        readers.map((reader, i) => {
          if (i === 0) return reader.read().catch(() => Promise.reject(pageChanged()));
          return before && !before[i] ? undefined : answered(reader.read());
        }),
      );
    },
  };
};

/** Short values need word boundaries to avoid masking unrelated text. */
const dottedPattern = (values: ReadonlyArray<string>) => {
  const sources = values
    .flatMap((value) => {
      const json = JSON.stringify(value).slice(1, -1);
      // Playwright writes control characters like JSON does, with \xNN for the unnamed ones.
      const quoted = value.replace(/[\\"\p{Cc}]/gu, (char) =>
        '\\"\b\f\n\r\t'.includes(char)
          ? JSON.stringify(char).slice(1, -1)
          : `\\x${char.charCodeAt(0).toString(16).padStart(2, "0")}`,
      );
      const forms = [value, json, quoted].flatMap((form) => [form, form.replaceAll("'", "''")]);
      return [...new Set(forms)].map((form) => ({ form, word: value.length < 4 }));
    })
    // Longest first, so a form inside another never leaves the rest showing.
    .toSorted((a, b) => b.form.length - a.form.length)
    .map(({ form, word }) => {
      const literal = form.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
      return word ? `(?<![\\p{L}\\p{N}_])${literal}(?![\\p{L}\\p{N}_])` : literal;
    });
  if (sources.length === 0) return undefined;
  const pattern = new RegExp(sources.join("|"), "gu");
  try {
    pattern.test("");
    pattern.test("\u2022");
  } catch {
    throw new OperationError("failed", VALUE_TOO_LONG);
  }
  return pattern;
};

// Playwright single-quotes keys containing ': ' and leaves /.../ names unquoted. Recognize only its attributes so name text cannot spoof them.
const TREE_LINE =
  /^(\s*- '?[^\s"':]+)( "(?:[^"\\]|\\.)*"| \/(?:.*?\/)?)?((?: \[(?:active|checked(?:=mixed)?|disabled|expanded|level=\d+|pressed(?:=mixed)?|selected|ref=(?:f\d+)?e\d+|cursor=pointer|box=-?\d+,-?\d+,\d+,\d+)\])*'?)(:.*)?$/;

/** Preserve roles and attributes so refs work; unquoted /.../ names can make matches cross boundaries. */
const maskTree = (tree: string, dotted: RegExp) =>
  tree
    .split("\n")
    .map((line) => {
      const node = TREE_LINE.exec(line);
      const name = node?.[1]?.length ?? 0;
      const attributes = name + (node?.[2]?.length ?? 0);
      const end = attributes + (node?.[3]?.length ?? 0);
      const kept = (from: number, to: number) => to <= name || (from >= attributes && to <= end);
      return line.replace(dotted, (match: string, offset: number) =>
        kept(offset, offset + match.length) ? match : MASKED_VALUE,
      );
    })
    .join("\n");

export const captureViewport = async (
  cdp: CDPSession,
  options: { readonly format: "png" | "jpeg"; readonly quality?: number },
) => {
  const capture = cdp.send("Page.captureScreenshot", {
    format: options.format,
    ...(options.quality === undefined ? {} : { quality: options.quality }),
  });
  let timer: ReturnType<typeof setTimeout> | undefined;
  const expired = new Promise<never>((_, reject) => {
    timer = setTimeout(
      () =>
        reject(new OperationError("failed", "The browser is not producing screenshot frames.")),
      SCREENSHOT_TIMEOUT_MS,
    );
  });
  const { data } = await Promise.race([capture, expired]).finally(() => clearTimeout(timer));
  return data;
};

type SnapshotResult = { readonly url: string; readonly title: string; readonly tree: string };

const capture = async (page: Page, cdp: CDPSession, deadline: number): Promise<SnapshotResult> => {
  const state = refsFor(page);
  invalidateRefs(page);
  const generation = state.generation;
  const { readers, read } = await openReaders(page, cdp);
  const before = await read();
  const pageState = readPageState(cdp);
  void pageState.catch(noop);
  const tree = await page.ariaSnapshot({
    mode: "ai",
    boxes: true,
    timeout: Math.max(1, deadline - Date.now() - SNAPSHOT_MARGIN_MS),
  });
  const after = await read(before);
  // A value that changed meanwhile may be in the tree under neither reading.
  if (after.some((values, i) => values && JSON.stringify(values) !== JSON.stringify(before[i])))
    throw pageChanged();
  const dotted = dottedPattern(after.flatMap((values) => values ?? []));
  // Unread frames can expose values only if their content appears in the tree.
  const unread = readers.flatMap((reader, i) => (after[i] ? [] : reader.frames));
  const filled = /^\s*- iframe (?:\[active\] )?\[ref=(\S+?)\].*:$/gm;
  for (const match of unread.length ? tree.matchAll(filled) : []) {
    const iframe = await page.locator(`aria-ref=${match[1]}`).elementHandle({ timeout: SNAPSHOT_MARGIN_MS });
    if (!iframe) throw pageChanged();
    const frame = await iframe.contentFrame();
    void iframe.dispose().catch(noop);
    if (frame && unread.includes(frame)) throw frameUnanswered();
  }
  const { url, title } = await pageState;
  if (state.generation !== generation) throw pageChanged();
  const redacted = withoutTreeDataPayloads(tree);
  const accessibilityTree = (dotted ? maskTree(redacted, dotted) : redacted)
    .slice(0, MAX_SNAPSHOT_CHARS)
    .replace(/\[ref=((?:f\d+)?e\d+)\]/g, (_match, nativeRef: string) => {
      const ref = `e${generation}_${nativeRef.replace(/^e/, "")}`;
      state.refs.set(ref, nativeRef);
      return `[ref=${ref}]`;
    });
  const mask = (text: string) => (dotted ? text.replace(dotted, MASKED_VALUE) : text);
  return { url: withoutDataPayload(url), title: mask(title), tree: accessibilityTree };
};

/** Snapshots begun per page; observers' snapshots aren't queued, so two can overlap. */
const snapshotTurns = new WeakMap<Page, number>();

export const snapshot = async (page: Page, cdp: CDPSession): Promise<SnapshotResult> => {
  const deadline = Date.now() + SNAPSHOT_TIMEOUT_MS;
  let timer: ReturnType<typeof setTimeout> | undefined;
  const expired = new Promise<never>((_, reject) => {
    timer = setTimeout(() => reject(snapshotTimedOut()), SNAPSHOT_TIMEOUT_MS);
  });
  const turn = (snapshotTurns.get(page) ?? 0) + 1;
  snapshotTurns.set(page, turn);
  // Retry only before the deadline and the next snapshot, whose refs a later retry would revoke.
  const captured = capture(page, cdp, deadline).catch((cause: unknown) =>
    Date.now() < deadline &&
    snapshotTurns.get(page) === turn &&
    !(cause instanceof Error && cause.message === VALUE_TOO_LONG)
      ? capture(page, cdp, deadline)
      : Promise.reject(cause),
  );
  void captured.catch(noop);
  try {
    return await Promise.race([captured, expired]);
  } catch (cause) {
    throw isTimeout(cause) ? snapshotTimedOut() : cause;
  } finally {
    clearTimeout(timer);
  }
};

/** Return when a dialog opens; waiting for the action to finish would block until dialog resolution. */
export const click = async (
  page: Page,
  input: ClickInput,
  pointer: PointerReporter = noPointer,
) => {
  const deadline = Date.now() + input.timeoutMs;
  const remaining = () => Math.max(1, deadline - Date.now());
  const locator = targetLocator(page, input);
  try {
    await clickTarget(page, locator, input, remaining, pointer);
  } catch (cause) {
    throw locator === null ? cause : await namedTargetTimeout(locator, input, cause);
  }
};

/**
 * Playwright's timeout names neither the target nor why it waited. The count describes the page
 * after the timeout, not what the click did.
 */
const namedTargetTimeout = async (locator: Locator, input: Target, cause: unknown) => {
  if (!(cause instanceof Error && cause.name === "TimeoutError")) return cause;
  const selector = describeTarget(input);
  const target =
    selector.length > MAX_TARGET_CHARS ? `${selector.slice(0, MAX_TARGET_CHARS)}...` : selector;
  let timer: ReturnType<typeof setTimeout> | undefined;
  const matches = await Promise.race([
    locator.count().catch(() => undefined),
    new Promise<undefined>((resolve) => {
      timer = setTimeout(() => resolve(undefined), TARGET_COUNT_MS);
    }),
  ]).finally(() => clearTimeout(timer));
  const reason =
    matches === undefined
      ? `The click may have happened; check the page before retrying. Whether ${target} still matches an element is unknown.`
      : matches === 0
        ? `The click may have happened and removed its target or navigated; check the page before retrying. No element matches ${target} after the timeout; take a fresh snapshot and use its refs.`
        : `The click may have happened; check the page before retrying. ${target} still matches an element after the timeout.`;
  return new OperationError("timeout", withActionabilityReason(reason, cause));
};

const clickTarget = async (
  page: Page,
  locator: Locator | null,
  input: ClickInput,
  timeout: () => number,
  pointer: PointerReporter,
) => {
  const point = await targetPoint(page, locator, input, timeout);
  await pointer(point, "click");
  const options = { button: input.button ?? "left", clickCount: input.clickCount ?? 1 } as const;
  const clicked =
    locator === null
      ? page.mouse.click(point.x, point.y, options)
      : locator.click({ ...options, timeout: timeout() });
  await untilDialog(page, clicked);
};

/** A dialog blocks the action until it is answered, so return true as soon as one opens. */
const untilDialog = async (page: Page, action: Promise<void>): Promise<boolean> => {
  let onDialog = noop;
  const dialogOpened = new Promise<"dialog">((resolve) => {
    onDialog = () => resolve("dialog");
    page.once("dialog", onDialog);
  });
  try {
    if ((await Promise.race([action, dialogOpened])) !== "dialog") return false;
    void action.catch(noop);
    return true;
  } finally {
    page.off("dialog", onDialog);
  }
};

type FocusCandidate = {
  readonly tagName: string;
  readonly type?: string;
  readonly disabled?: boolean;
  readonly readOnly?: boolean;
  readonly isContentEditable?: boolean;
  readonly shadowRoot?: { readonly activeElement: FocusCandidate | null } | null;
  readonly focus?: () => void;
  getRootNode(): { readonly activeElement?: FocusCandidate | null };
  contains(other: FocusCandidate): boolean;
};

// Serialized into the page's main world, so it must not reference module scope.
const focusTextTarget = (target: FocusCandidate | null) => {
  let element =
    target ??
    (globalThis as unknown as { document: { activeElement: FocusCandidate | null } }).document
      .activeElement;
  if (target === null) {
    while (element?.shadowRoot?.activeElement) element = element.shadowRoot.activeElement;
    if (element && ["IFRAME", "FRAME", "FENCEDFRAME", "OBJECT", "EMBED"].includes(element.tagName))
      return false;
  }
  if (element == null) return false;
  const nonText = [
    "button",
    "checkbox",
    "color",
    "file",
    "hidden",
    "image",
    "radio",
    "range",
    "reset",
    "submit",
  ];
  const textControl =
    element.tagName === "TEXTAREA" ||
    (element.tagName === "INPUT" && !nonText.includes(element.type ?? "text"));
  if (!(textControl || element.isContentEditable) || element.disabled || element.readOnly) {
    return false;
  }
  element.focus?.();
  const active = element.getRootNode().activeElement;
  return active != null && (active === element || element.contains(active));
};

const pageAnswer = async <A>(answer: Promise<A>, timeout: number) => {
  let timer: ReturnType<typeof setTimeout> | undefined;
  const expired = new Promise<never>((_, reject) => {
    timer = setTimeout(
      () =>
        reject(
          new OperationError(
            "timeout",
            `The page did not answer within ${timeout}ms, so no text was typed.`,
          ),
        ),
      timeout,
    );
  });
  return await Promise.race([answer, expired]).finally(() => clearTimeout(timer));
};

// Serialized into the page's main world, so it must not reference module scope.
const valueOnlyInput = (
  target: FocusCandidate & {
    closest(selector: string): { readonly control: FocusCandidate | null } | null;
  },
) => {
  const element = target.tagName === "INPUT" ? target : target.closest("label")?.control;
  return (
    element?.tagName === "INPUT" &&
    ["color", "date", "datetime-local", "month", "range", "time", "week"].includes(
      element.type ?? "",
    )
  );
};

// Keys reach pages that build their value from keydown. Line breaks stay text: Enter would submit the form.
const typeKeys = async (page: Page, text: string, deadline: number) => {
  let typed = 0;
  for (const [index, part] of text.split(/([\r\n]+)/u).entries()) {
    const pieces = index % 2 === 1 ? [part] : (part.match(/[^]{1,64}/gu) ?? []);
    for (const piece of pieces) {
      if (Date.now() >= deadline) {
        throw new OperationError(
          "timeout",
          `Typing stopped after ${typed} of ${text.length} characters, which the field now holds. Type the rest in another call or raise timeoutMs.`,
        );
      }
      const typing = index % 2 === 1 ? page.keyboard.insertText(piece) : page.keyboard.type(piece);
      if (await untilDialog(page, typing)) return;
      typed += piece.length;
    }
  }
};

export const type = async (page: Page, input: TypeInput) => {
  const deadline = Date.now() + input.timeoutMs;
  const remaining = () => Math.max(1, deadline - Date.now());
  const locator = targetLocator(page, input);
  if (locator !== null && input.clear) {
    // Pickers and sliders take a value such as 2026-01-31 only from fill.
    const timeout = remaining();
    if (await pageAnswer(locator.evaluate(valueOnlyInput, undefined, { timeout }), timeout)) {
      await locator.fill(input.text, { timeout: remaining() });
      return;
    }
    await locator.fill("", { timeout: remaining() });
    await typeKeys(page, input.text, deadline);
    return;
  }
  const focused =
    locator === null
      ? await pageAnswer(page.evaluate(focusTextTarget, null), remaining())
      : await locator.evaluate(focusTextTarget, undefined, { timeout: remaining() });
  if (focused !== true) {
    throw new OperationError(
      "not_editable",
      "The target is not an enabled text field, so no text was typed.",
    );
  }
  if (input.clear) {
    if (await untilDialog(page, page.keyboard.press("ControlOrMeta+A"))) return;
    if (await untilDialog(page, page.keyboard.press("Delete"))) return;
  }
  await typeKeys(page, input.text, deadline);
};

export const hover = async (page: Page, input: HoverInput, pointer: PointerReporter = noPointer) => {
  const deadline = Date.now() + input.timeoutMs;
  const remaining = () => Math.max(1, deadline - Date.now());
  const locator = targetLocator(page, input);
  await pointer(await targetPoint(page, locator, input, remaining), "move");
  if (locator === null) {
    await page.mouse.move(input.x ?? 0, input.y ?? 0);
    return;
  }
  await locator.hover({ timeout: remaining() });
};

const requiredLocator = (page: Page, input: Target): Locator => {
  const locator = targetLocator(page, input);
  if (locator === null) throw new OperationError("invalid_argument", "Pass a ref or a selector.");
  return locator;
};

export const select = async (page: Page, input: SelectInput): Promise<Array<string>> => {
  const locator = requiredLocator(page, input);
  const timeout = input.timeoutMs;
  const options = await locator.evaluate(
    (element) =>
      element.tagName === "SELECT"
        ? Array.from(
            (element as unknown as { options: ArrayLike<{ value: string; label: string }> })
              .options,
            ({ value, label }) => ({ value, label: label.trim() }),
          )
        : null,
    undefined,
    { timeout },
  );
  if (options === null)
    throw new OperationError(
      "not_editable",
      "This element is not a <select>. Click a custom dropdown, then click its option.",
    );
  const values = input.values.map(
    (entry) =>
      (
        options.find((option) => option.value === entry) ??
        options.find((option) => option.label === entry.trim())
      )?.value ?? entry,
  );
  return locator.selectOption(values, { timeout });
};

export const drag = async (page: Page, input: DragInput, pointer: PointerReporter = noPointer) => {
  const deadline = Date.now() + input.timeoutMs;
  const remaining = () => Math.max(1, deadline - Date.now());
  const source = requiredLocator(page, input.source);
  const target = requiredLocator(page, input.target);
  await pointer(await targetPoint(page, source, {}, remaining), "move");
  // Observe drag rejection immediately; steps give the page mousemoves during the drag.
  const dragFailure = source.dragTo(target, { timeout: remaining(), steps: 5 }).then(
    () => null,
    (error: unknown) => ({ error }),
  );
  const end = await target.boundingBox({ timeout: remaining() }).catch(() => null);
  if (end) await pointer({ x: end.x + end.width / 2, y: end.y + end.height / 2 }, "move");
  const failure = await dragFailure;
  if (failure) throw failure.error;
};

export const setInputFiles = async (page: Page, input: UploadInput) => {
  const locator = targetLocator(page, input);
  if (locator === null) return false;
  await locator.setInputFiles([...input.paths], { timeout: input.timeoutMs });
  return true;
};

export const press = async (page: Page, input: PressInput) => {
  await untilDialog(page, page.keyboard.press([...(input.modifiers ?? []), input.key].join("+")));
};

export const scroll = async (page: Page, input: ScrollInput) => {
  const delta: [number, number] = [input.deltaX ?? 0, input.deltaY ?? 0];
  const locator = targetLocator(page, input);
  if (locator === null) {
    await page.evaluate(`scrollBy(${delta[0]}, ${delta[1]})`);
    return;
  }
  await locator.evaluate(
    (element, [x, y]) => (element as unknown as { scrollBy(x: number, y: number): void }).scrollBy(x, y),
    delta,
  );
};

const UNRESPONSIVE_SCRIPT_PROBE_MS = 1_000;

/**
 * A same-site navigation reuses the renderer, so it never commits while a page script holds it.
 * Call before starting the navigation: Chrome does not deliver a terminate once one is pending.
 */
export const stopUnresponsiveScript = async (cdp: CDPSession, budgetMs = Infinity) => {
  let timer: ReturnType<typeof setTimeout> | undefined;
  const responded = cdp.send("Runtime.evaluate", { expression: "0" }).then(
    () => true,
    () => true,
  );
  const expired = new Promise<boolean>((resolve) => {
    timer = setTimeout(() => resolve(false), Math.min(budgetMs, UNRESPONSIVE_SCRIPT_PROBE_MS));
  });
  const responsive = await Promise.race([responded, expired]).finally(() => clearTimeout(timer));
  if (!responsive) void cdp.send("Runtime.terminateExecution").catch(noop);
};

/** Terminate expired page scripts so a hung expression cannot block the tab's control queue. */
export const evaluate = async (cdp: CDPSession, expression: string, timeoutMs: number) => {
  let timer: ReturnType<typeof setTimeout> | undefined;
  let timedOut = false;
  const expired = new Promise<never>((_, reject) => {
    timer = setTimeout(() => {
      timedOut = true;
      void cdp.send("Runtime.terminateExecution").catch(noop);
      reject(
        new OperationError(
          "timeout",
          `Evaluation did not finish within ${timeoutMs}ms and was stopped.`,
        ),
      );
    }, timeoutMs);
  });
  const params = { expression, awaitPromise: true, returnByValue: true };
  // replMode allows top-level await, so it only retries what the page's parser rejected.
  const evaluation = cdp.send("Runtime.evaluate", params).then((classic) => {
    const failure = classic.exceptionDetails;
    const unparsed =
      failure?.exception?.className === "SyntaxError" &&
      failure.scriptId !== undefined &&
      failure.stackTrace === undefined;
    return unparsed && !timedOut && expression.includes("await")
      ? cdp.send("Runtime.evaluate", { ...params, replMode: true })
      : classic;
  });
  void evaluation.catch(noop);
  const result = await Promise.race([evaluation, expired]).finally(() => clearTimeout(timer));
  if (result.exceptionDetails) {
    throw new OperationError(
      "failed",
      result.exceptionDetails.exception?.description ?? result.exceptionDetails.text,
    );
  }
  const value: unknown =
    "value" in result.result ? result.result.value : (result.result.description ?? null);
  const actualBytes = Buffer.byteLength(JSON.stringify(value ?? null), "utf8");
  if (actualBytes > MAX_EVALUATION_BYTES) {
    throw new OperationError(
      "failed",
      `Evaluation result is ${actualBytes} bytes; the limit is ${MAX_EVALUATION_BYTES}.`,
    );
  }
  return value ?? null;
};

export const waitFor = async (page: Page, input: WaitForInput) => {
  const { text, urlIncludes, timeoutMs } = input;
  const locator = targetLocator(page, input);
  const checks: Array<() => Promise<boolean>> = [];
  if (locator !== null) checks.push(async () => (await locator.count()) > 0);
  if (text !== undefined) {
    // A navigation can destroy the context mid-check; that counts as not yet.
    checks.push(() =>
      page
        .evaluate(`(document.body?.innerText ?? "").includes(${JSON.stringify(text)})`)
        .then((found) => found === true)
        .catch(() => false),
    );
  }
  if (urlIncludes !== undefined) checks.push(async () => page.url().includes(urlIncludes));
  let timer: ReturnType<typeof setTimeout> | undefined;
  const expired = new Promise<never>((_, reject) => {
    timer = setTimeout(
      () =>
        reject(new OperationError("timeout", `Waited ${timeoutMs}ms without every condition holding.`)),
      timeoutMs,
    );
  });
  try {
    for (;;) {
      const results = await Promise.race([Promise.all(checks.map((check) => check())), expired]);
      if (results.every(Boolean)) return;
      await Promise.race([new Promise((resolve) => setTimeout(resolve, WAIT_POLL_MS)), expired]);
    }
  } finally {
    clearTimeout(timer);
  }
};
