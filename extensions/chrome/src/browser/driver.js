// Drives the tabs that the user shared with a chat, through the Chrome
// DevTools Protocol (chrome.debugger). It answers the same methods, with the
// same result shapes, as the browser service in the chat VM
// (deployment/craft-runtime/browser-service/src/service.ts).

const DEFAULT_TIMEOUT_MS = 15_000;
const MAX_SNAPSHOT_CHARS = 20_000;
const MAX_TABS = 8;
const POLL_MS = 100;
// User input in a tab holds it this long after the last input.
const HUMAN_HOLD_MS = 8_000;
// Input events up to this long after an agent dispatch are the agent's.
const AGENT_INPUT_MARGIN_MS = 400;
const HUMAN_BINDING = "__onyxHumanInput";
const MASKED = "••••••";

const HUMAN_CONTROL_MESSAGE =
  "The user is using this tab. Wait a few seconds and try again, or ask the user to stop.";

export class OperationError extends Error {
  constructor(code, message) {
    super(message);
    this.code = code;
  }
}

const invalid = (message) => new OperationError("invalid_argument", message);

// Hooks the page and its frames that are already loaded and that it can
// reach (same origin); new documents get it from
// Page.addScriptToEvaluateOnNewDocument.
const HUMAN_INPUT_SCRIPT = `(() => {
  const hook = (win) => {
    try {
      if (!win.__onyxHumanHooked) {
        win.__onyxHumanHooked = true;
        for (const type of ["pointerdown", "keydown"]) {
          win.addEventListener(type, (event) => {
            if (!event.isTrusted) return;
            try { ${HUMAN_BINDING}(type); } catch {}
          }, true);
        }
      }
      for (let i = 0; i < win.frames.length; i += 1) hook(win.frames[i]);
    } catch {}
  };
  hook(window);
})()`;

// Per tab: refs of the last snapshot, a pending dialog, and who acts.
const tabStates = new Map();
let refGeneration = 0;

function stateOf(tabId) {
  let state = tabStates.get(tabId);
  if (!state) {
    state = {
      refs: new Map(),
      dialog: null,
      humanUntil: 0,
      agentInputUntil: 0,
      dialogWaiters: [],
      ready: null,
    };
    tabStates.set(tabId, state);
  }
  return state;
}

// Grants that ended while one of their calls still ran.
const endedGrants = new Set();

/** Mark a grant as ended, so its running calls stop. */
export function grantEnded(grantId) {
  endedGrants.add(grantId);
}

const grantEndedError = () =>
  new OperationError("no_grant", "The user's share of Chrome with this chat ended.");

export function forgetTab(tabId) {
  tabStates.delete(tabId);
}

function isHumanControlled(tabId) {
  return (tabStates.get(tabId)?.humanUntil ?? 0) > Date.now();
}

const send = (tabId, method, params = {}) =>
  chrome.debugger.sendCommand({ tabId }, method, params);

/** Attach the debugger to a tab and turn on what the driver reads. */
export function attach(tabId) {
  const state = stateOf(tabId);
  if (!state.ready) {
    state.ready = (async () => {
      try {
        await chrome.debugger.attach({ tabId }, "1.3");
      } catch (error) {
        // A worker restart keeps the extension's attachment.
        if (!/already attached/i.test(String(error?.message))) throw error;
      }
      await send(tabId, "Page.enable");
      await send(tabId, "DOM.enable");
      await send(tabId, "Runtime.enable");
      await send(tabId, "Runtime.addBinding", { name: HUMAN_BINDING });
      await send(tabId, "Page.addScriptToEvaluateOnNewDocument", {
        source: HUMAN_INPUT_SCRIPT,
      });
      await send(tabId, "Runtime.evaluate", { expression: HUMAN_INPUT_SCRIPT });
    })().catch((error) => {
      state.ready = null;
      throw new OperationError(
        "failed",
        `Could not control the tab: ${error?.message ?? error}`
      );
    });
  }
  return state.ready;
}

export async function detach(tabId) {
  tabStates.delete(tabId);
  try {
    await chrome.debugger.detach({ tabId });
  } catch {
    // Already detached.
  }
}

/** Debugger events of attached tabs. */
export function handleEvent(source, method, params) {
  const tabId = source.tabId;
  if (tabId === undefined || !tabStates.has(tabId)) return;
  const state = stateOf(tabId);
  switch (method) {
    case "Page.javascriptDialogOpening":
      state.dialog = {
        type: params.type,
        message: String(params.message ?? "").slice(0, 2000),
        origin: params.url ?? "",
      };
      state.refs.clear();
      for (const resolve of state.dialogWaiters.splice(0)) resolve();
      break;
    case "Page.javascriptDialogClosed":
      state.dialog = null;
      break;
    case "Page.frameNavigated":
      if (!params.frame?.parentId) state.refs.clear();
      break;
    case "Runtime.bindingCalled":
      if (
        params.name === HUMAN_BINDING &&
        Date.now() > state.agentInputUntil + AGENT_INPUT_MARGIN_MS
      ) {
        state.humanUntil = Date.now() + HUMAN_HOLD_MS;
        state.refs.clear();
      }
      break;
    default:
      break;
  }
}

// ---- urls and origins ----

const LOOPBACK = /^(localhost|127(?:\.\d{1,3}){3}|\[::1\])(?::\d+)?(?:[/?#]|$)/i;

function normalizeUrl(raw) {
  const trimmed = String(raw).trim();
  if (!trimmed) throw invalid("The URL is empty.");
  if (trimmed === "about:blank") return trimmed;
  const hasScheme =
    !/^[^\s:/?#]+:\d+(?:[/?#]|$)/.test(trimmed) &&
    /^[a-z][a-z\d+.-]*:/i.test(trimmed);
  const candidate = hasScheme
    ? trimmed
    : `${LOOPBACK.test(trimmed) ? "http" : "https"}://${trimmed}`;
  let parsed;
  try {
    parsed = new URL(candidate);
  } catch {
    throw invalid(`Not a valid URL: ${trimmed.slice(0, 200)}`);
  }
  if (parsed.protocol !== "http:" && parsed.protocol !== "https:")
    throw invalid("Only http and https URLs open.");
  return parsed.href;
}

export function originOf(url) {
  try {
    const parsed = new URL(url);
    return parsed.protocol === "http:" || parsed.protocol === "https:"
      ? parsed.origin
      : null;
  } catch {
    return null;
  }
}

const UNSHARED_TAB_MESSAGE =
  "The tab is on a site that the user did not share with this chat. Ask the user to share it, or go back to a shared site.";

function outsideMessage(url) {
  return `${originOf(url) ?? url} is not a site that the user shared with this chat. Ask the user to share it.`;
}

// ---- tabs ----

async function tabJson(grant, tabId) {
  const tab = await chrome.tabs.get(tabId);
  const state = stateOf(tabId);
  const shared = isShared(grant, tab.url ?? "");
  return {
    id: String(tab.id),
    url: shared ? (tab.url ?? "") : "(a site that the user did not share)",
    title: shared ? (tab.title ?? "") : "",
    loading: tab.status === "loading",
    controller: isHumanControlled(tabId) ? "human" : "agent",
    // A dialog of a site that the user did not share stays hidden.
    dialog: shared && state.dialog && isShared(grant, state.dialog.origin) ? state.dialog : null,
  };
}

function isShared(grant, url) {
  // Blank and srcdoc documents take the origin of the shared page around them.
  if (url === "about:blank" || url === "about:srcdoc" || url === "") return true;
  const origin = originOf(url);
  return origin !== null && grant.origins.includes(origin);
}

function resolveTab(grant, params) {
  const raw = params.tab;
  // A grant always has a current tab.
  if (raw === undefined || raw === null) return grant.current;
  const tabId = Number(raw);
  if (!grant.tabs.includes(tabId))
    throw new OperationError(
      "tab_not_found",
      `Tab ${String(raw).slice(0, 50)} is not one of this chat's tabs. Read browser_status.`
    );
  return tabId;
}

async function sharedTab(grant, tabId) {
  if (endedGrants.has(grant.id)) throw grantEndedError();
  const tab = await chrome.tabs.get(tabId).catch(() => null);
  if (!tab)
    throw new OperationError("tab_not_found", "The tab closed.");
  // The tab's own site may be private: the refusal does not name it.
  if (!isShared(grant, tab.url ?? ""))
    throw new OperationError("failed", UNSHARED_TAB_MESSAGE);
  await attach(tabId);
  return tab;
}

function checkWritable(tabId) {
  const state = stateOf(tabId);
  if (state.dialog) throw dialogPending();
  if (isHumanControlled(tabId))
    throw new OperationError("human_control", HUMAN_CONTROL_MESSAGE);
}

const dialogPending = () =>
  new OperationError(
    "dialog_pending",
    "A browser dialog is pending. Read browser_status and use browser_dialog first."
  );

// ---- snapshot ----

const PASS_THROUGH_ROLES = new Set(["generic", "none", "GenericContainer", "WebArea"]);
const VALUE_ROLES = new Set(["textbox", "searchbox", "combobox", "spinbutton", "slider"]);
const STATE_PROPERTIES = ["checked", "disabled", "expanded", "level", "selected", "pressed", "focused", "required"];

const quote = (text) => `"${String(text).replace(/\s+/g, " ").trim().replace(/"/g, '\\"').slice(0, 300)}"`;

async function readFrameTree(tabId, frameId) {
  const { nodes } = await send(
    tabId,
    "Accessibility.getFullAXTree",
    frameId ? { frameId } : {}
  );
  return nodes;
}

async function isPasswordField(tabId, backendNodeId) {
  try {
    const { node } = await send(tabId, "DOM.describeNode", { backendNodeId });
    const attributes = node.attributes ?? [];
    for (let i = 0; i < attributes.length; i += 2) {
      if (attributes[i] === "type" && String(attributes[i + 1]).toLowerCase() === "password")
        return true;
    }
  } catch {
    return false;
  }
  return false;
}

async function iframeFrameId(tabId, backendNodeId) {
  try {
    const { node } = await send(tabId, "DOM.describeNode", { backendNodeId, depth: 1 });
    return node.contentDocument?.frameId ?? node.frameId ?? null;
  } catch {
    return null;
  }
}

async function frameUrls(tabId) {
  const urls = new Map();
  const walk = (node) => {
    urls.set(node.frame.id, node.frame.url);
    for (const child of node.childFrames ?? []) walk(child);
  };
  walk((await send(tabId, "Page.getFrameTree")).frameTree);
  return urls;
}

const outsideFrame = () =>
  new OperationError(
    "failed",
    "That part of the page is a frame from a site that the user did not share. Ask the user to share it."
  );

/** Refuse input at a point whose frame is not shared: the frame of the
 * element there, and the frame that an iframe element there holds. */
async function checkPoint(grant, tabId, { x, y }) {
  const answer = await send(tabId, "DOM.getNodeForLocation", {
    x: Math.round(x),
    y: Math.round(y),
    ignorePointerEventsNone: true,
  }).catch(() => null);
  if (!answer)
    throw new OperationError("failed", "Chrome could not tell what is at that point. Scroll it into view and retry.");
  const frames = await frameUrls(tabId);
  const frameIds = [answer.frameId];
  const inner = await iframeFrameId(tabId, answer.backendNodeId);
  if (inner) frameIds.push(inner);
  for (const frameId of frameIds) {
    if (frameId && !isShared(grant, frames.get(frameId) ?? "-")) throw outsideFrame();
  }
}

/** Refuse keys when focus is in a password field or in a frame that is not
 * shared. Focus in a frame of another origin stops at its iframe element. */
async function checkFocus(grant, tabId) {
  const { result } = await send(tabId, "Runtime.evaluate", {
    expression: `(() => {
      let element = document.activeElement;
      for (;;) {
        if (element?.shadowRoot?.activeElement) element = element.shadowRoot.activeElement;
        else if (element?.contentDocument?.activeElement) element = element.contentDocument.activeElement;
        else break;
      }
      return element;
    })()`,
  });
  if (!result.objectId) return;
  const kind = await callOn(tabId, result.objectId, function () {
    if (this.tagName === "IFRAME" || this.tagName === "FRAME") return "frame";
    return this.tagName === "INPUT" && (this.getAttribute("type") || "").toLowerCase() === "password"
      ? "password"
      : "other";
  });
  if (kind === "password") throw passwordRefused();
  if (kind === "frame") {
    const { node } = await send(tabId, "DOM.describeNode", { objectId: result.objectId, depth: 1 });
    const frameId = node.contentDocument?.frameId ?? node.frameId;
    const frames = await frameUrls(tabId);
    if (!isShared(grant, frames.get(frameId) ?? "-")) throw outsideFrame();
  }
}

const passwordRefused = () =>
  new OperationError("failed", "Onyx does not type into password fields. Ask the user to type it.");

async function snapshotText(grant, tab, state) {
  const tabId = tab.id;
  const frames = await frameUrls(tabId);
  refGeneration += 1;
  const generation = refGeneration.toString(36);
  state.refs.clear();
  let refCount = 0;
  const lines = [`Title: ${tab.title ?? ""}`, `URL: ${tab.url ?? ""}`, ""];
  let length = lines.join("\n").length;
  let full = false;
  const push = (line) => {
    if (full) return;
    length += line.length + 1;
    if (length > MAX_SNAPSHOT_CHARS) {
      full = true;
      lines.push("- (the snapshot stops here: the page is longer)");
      return;
    }
    lines.push(line);
  };

  const renderTree = async (nodes, depth, frameDepth) => {
    const byId = new Map(nodes.map((node) => [node.nodeId, node]));
    const root = nodes.find((node) => !node.parentId) ?? nodes[0];
    const render = async (node, level) => {
      if (!node || full) return;
      const role = node.role?.value ?? "";
      const children = (node.childIds ?? []).map((id) => byId.get(id));
      if (role === "LineBreak") return;
      const name = node.name?.value ?? "";
      if (role === "StaticText") {
        if (name.trim()) push(`${"  ".repeat(level)}- text: ${quote(name)}`);
        return;
      }
      if (
        node.ignored ||
        role === "RootWebArea" ||
        (PASS_THROUGH_ROLES.has(role) && !name.trim())
      ) {
        for (const child of children) await render(child, level);
        return;
      }
      const parts = [`${"  ".repeat(level)}- ${role === "Iframe" ? "iframe" : role}`];
      if (name.trim()) parts.push(quote(name));
      for (const property of node.properties ?? []) {
        if (!STATE_PROPERTIES.includes(property.name)) continue;
        const value = property.value?.value;
        if (value === false || value === undefined || value === "false") continue;
        parts.push(value === true || value === "true" ? `[${property.name}]` : `[${property.name}=${value}]`);
      }
      if (node.backendDOMNodeId !== undefined) {
        refCount += 1;
        const ref = `e${generation}_${refCount}`;
        state.refs.set(ref, node.backendDOMNodeId);
        parts.push(`[ref=${ref}]`);
      }
      let line = parts.join(" ");
      if (VALUE_ROLES.has(role) && node.value?.value !== undefined && node.value.value !== "") {
        const masked =
          node.backendDOMNodeId !== undefined &&
          (await isPasswordField(tabId, node.backendDOMNodeId));
        line += `: ${masked ? MASKED : quote(node.value.value)}`;
      }
      if (role === "Iframe" && node.backendDOMNodeId !== undefined && frameDepth < 3) {
        push(`${line}:`);
        const frameId = await iframeFrameId(tabId, node.backendDOMNodeId);
        // A frame of a site that the user did not share stays unread.
        const frameNodes =
          frameId && isShared(grant, frames.get(frameId) ?? "-")
            ? await readFrameTree(tabId, frameId).catch(() => null)
            : null;
        if (frameNodes && frameNodes.length > 0)
          await renderTree(frameNodes, level + 1, frameDepth + 1);
        else push(`${"  ".repeat(level + 1)}- text: "(this frame cannot be read)"`);
        return;
      }
      const visible = children.filter(Boolean);
      push(visible.length ? `${line}:` : line);
      for (const child of visible) await render(child, level + 1);
    };
    await render(root, depth);
  };

  await renderTree(await readFrameTree(tabId, null), 0, 0);
  return lines.join("\n");
}

// ---- elements ----

function parseRef(raw) {
  return String(raw).trim().replace(/^\[?(?:aria-)?ref=/, "").replace(/\]$/, "");
}

const staleRef = () =>
  new OperationError(
    "stale_ref",
    "This element ref is stale or belongs to another tab. Take a fresh snapshot and use its refs."
  );

async function resolveTarget(tabId, target, deadline) {
  if (target.ref !== undefined) {
    const backendNodeId = stateOf(tabId).refs.get(parseRef(target.ref));
    if (backendNodeId === undefined) throw staleRef();
    try {
      const { object } = await send(tabId, "DOM.resolveNode", { backendNodeId });
      return object.objectId;
    } catch {
      throw staleRef();
    }
  }
  if (target.selector !== undefined) {
    const expression = `document.querySelector(${JSON.stringify(target.selector)})`;
    for (;;) {
      const { result, exceptionDetails } = await send(tabId, "Runtime.evaluate", { expression });
      if (exceptionDetails)
        throw invalid(`Bad selector: ${String(target.selector).slice(0, 200)}`);
      if (result.objectId) return result.objectId;
      if (Date.now() >= deadline)
        throw new OperationError("timeout", `No element matches ${String(target.selector).slice(0, 200)}.`);
      await sleep(POLL_MS);
    }
  }
  throw invalid("Pass ref or selector.");
}

async function focusedElement(tabId) {
  const { result } = await send(tabId, "Runtime.evaluate", {
    expression: `(() => {
      let element = document.activeElement;
      while (element?.contentDocument?.activeElement) element = element.contentDocument.activeElement;
      while (element?.shadowRoot?.activeElement) element = element.shadowRoot.activeElement;
      return element === document.body ? null : element;
    })()`,
  });
  if (!result.objectId)
    throw new OperationError("not_editable", "No field has focus. Pass ref or selector, or click the field first.");
  return result.objectId;
}

const callOn = async (tabId, objectId, fn, args = []) => {
  const { result, exceptionDetails } = await send(tabId, "Runtime.callFunctionOn", {
    objectId,
    functionDeclaration: fn.toString(),
    arguments: args.map((value) => ({ value })),
    returnByValue: true,
    awaitPromise: true,
  });
  if (exceptionDetails)
    throw new OperationError("failed", exceptionDetails.exception?.description?.split("\n")[0] ?? "The page refused the action.");
  return result.value;
};

/** The element's center, once it is visible and not covered. */
async function actionPoint(tabId, objectId, deadline) {
  let reason = "is not visible";
  for (;;) {
    await send(tabId, "DOM.scrollIntoViewIfNeeded", { objectId }).catch(() => {});
    const quads = await send(tabId, "DOM.getContentQuads", { objectId })
      .then((answer) => answer.quads)
      .catch(() => []);
    if (quads.length > 0) {
      const quad = quads[0];
      const x = (quad[0] + quad[2] + quad[4] + quad[6]) / 4;
      const y = (quad[1] + quad[3] + quad[5] + quad[7]) / 4;
      const hit = await callOn(
        tabId,
        objectId,
        function (px, py) {
          const view = this.ownerDocument.defaultView;
          if (view !== view.top) return true;
          // Look through open shadow roots to the element that takes the point.
          let found = this.ownerDocument.elementFromPoint(px, py);
          while (found?.shadowRoot) {
            const inner = found.shadowRoot.elementFromPoint(px, py);
            if (!inner || inner === found) break;
            found = inner;
          }
          return !!found && (found === this || this.contains(found));
        },
        [x, y]
      ).catch(() => true);
      if (hit) return { x, y };
      reason = "is covered by another element";
    }
    if (Date.now() >= deadline)
      throw new OperationError("timeout", `The element ${reason}. Close what covers it, or scroll, then retry.`);
    await sleep(POLL_MS);
  }
}

/** Send input. A page dialog blocks input events until it closes, so the
 * send also ends when a dialog opens; the event finishes after the answer. */
/** Stop a write when its call ran past its deadline (the server already
 * gave up on it), its grant ended, the user took the tab, or the tab left
 * the shared sites meanwhile. `ctx` is the write's grant, tab and deadline. */
async function checkLive(ctx) {
  if (Date.now() > ctx.deadline)
    throw new OperationError("timeout", "The call ran out of time before Chrome could act. Check the page before you retry.");
  if (endedGrants.has(ctx.grant.id)) throw grantEndedError();
  if (isHumanControlled(ctx.tabId))
    throw new OperationError("human_control", HUMAN_CONTROL_MESSAGE);
  const tab = await chrome.tabs.get(ctx.tabId).catch(() => null);
  if (!tab) throw new OperationError("tab_not_found", "The tab closed.");
  if (!isShared(ctx.grant, tab.url ?? "")) throw new OperationError("failed", UNSHARED_TAB_MESSAGE);
}

async function input(ctx, method, params) {
  await checkLive(ctx);
  const state = stateOf(ctx.tabId);
  state.agentInputUntil = Date.now() + 1_000;
  const sent = send(ctx.tabId, method, params);
  sent.catch(() => {});
  const dialog = dialogOpened(state);
  try {
    await Promise.race([sent, dialog.promise]);
  } finally {
    dialog.cancel();
    state.agentInputUntil = Date.now();
  }
}

function dialogOpened(state) {
  if (state.dialog) return { promise: Promise.resolve(), cancel: () => {} };
  let resolve;
  const promise = new Promise((done) => {
    resolve = done;
  });
  state.dialogWaiters.push(resolve);
  return {
    promise,
    cancel: () => {
      const index = state.dialogWaiters.indexOf(resolve);
      if (index >= 0) state.dialogWaiters.splice(index, 1);
    },
  };
}

async function mouseClick(ctx, { x, y }, button = "left", clickCount = 1) {
  await input(ctx, "Input.dispatchMouseEvent", { type: "mouseMoved", x, y });
  for (let count = 1; count <= clickCount; count += 1) {
    await input(ctx, "Input.dispatchMouseEvent", { type: "mousePressed", x, y, button, clickCount: count });
    await input(ctx, "Input.dispatchMouseEvent", { type: "mouseReleased", x, y, button, clickCount: count });
  }
}

const KEYS = {
  Enter: { code: "Enter", keyCode: 13, text: "\r" },
  Tab: { code: "Tab", keyCode: 9 },
  Escape: { code: "Escape", keyCode: 27 },
  Backspace: { code: "Backspace", keyCode: 8 },
  Delete: { code: "Delete", keyCode: 46 },
  ArrowUp: { code: "ArrowUp", keyCode: 38 },
  ArrowDown: { code: "ArrowDown", keyCode: 40 },
  ArrowLeft: { code: "ArrowLeft", keyCode: 37 },
  ArrowRight: { code: "ArrowRight", keyCode: 39 },
  Home: { code: "Home", keyCode: 36 },
  End: { code: "End", keyCode: 35 },
  PageUp: { code: "PageUp", keyCode: 33 },
  PageDown: { code: "PageDown", keyCode: 34 },
  Space: { code: "Space", keyCode: 32, text: " ", key: " " },
  " ": { code: "Space", keyCode: 32, text: " " },
};
const MODIFIER_BITS = { Alt: 1, Control: 2, Meta: 4, Shift: 8 };

function keyDefinition(key) {
  if (KEYS[key]) return { key: KEYS[key].key ?? key, ...KEYS[key] };
  if (/^F([1-9]|1[0-2])$/.test(key))
    return { key, code: key, keyCode: 111 + Number(key.slice(1)) };
  if ([...key].length === 1) {
    const upper = key.toUpperCase();
    const code = /[a-z]/i.test(key) ? `Key${upper}` : /\d/.test(key) ? `Digit${key}` : "";
    return { key, code, keyCode: upper.charCodeAt(0), text: key };
  }
  throw invalid(`Unknown key ${key.slice(0, 50)}.`);
}

async function pressKey(ctx, key, modifiers = []) {
  const definition = keyDefinition(key);
  const bits = modifiers.reduce((sum, name) => sum | (MODIFIER_BITS[name] ?? 0), 0);
  const text = bits & (MODIFIER_BITS.Control | MODIFIER_BITS.Meta | MODIFIER_BITS.Alt) ? undefined : definition.text;
  const base = {
    key: definition.key,
    code: definition.code,
    windowsVirtualKeyCode: definition.keyCode,
    nativeVirtualKeyCode: definition.keyCode,
    modifiers: bits,
  };
  await input(ctx, "Input.dispatchKeyEvent", {
    ...base,
    type: text ? "keyDown" : "rawKeyDown",
    ...(text ? { text, unmodifiedText: text } : {}),
  });
  await input(ctx, "Input.dispatchKeyEvent", { ...base, type: "keyUp" });
}

async function viewportCenter(tabId) {
  const { cssLayoutViewport } = await send(tabId, "Page.getLayoutMetrics");
  return { x: cssLayoutViewport.clientWidth / 2, y: cssLayoutViewport.clientHeight / 2 };
}

// ---- page waits ----

const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

async function waitForReady(tabId, readiness, deadline) {
  while (Date.now() < deadline) {
    const state = await send(tabId, "Runtime.evaluate", { expression: "document.readyState" })
      .then((answer) => answer.result?.value)
      .catch(() => null);
    if (state === "complete" || (readiness === "domcontentloaded" && state === "interactive"))
      return;
    if (stateOf(tabId).dialog) return;
    await sleep(POLL_MS);
  }
  throw new OperationError(
    "timeout",
    "The page did not finish loading in time. Check it with browser_status or browser_snapshot before you retry."
  );
}

async function navigateTab(grant, tabId, target, readiness, deadline) {
  await checkLive({ grant, tabId, deadline });
  if (target.url !== undefined) {
    if (!isShared(grant, target.url))
      throw new OperationError("failed", outsideMessage(target.url));
    const answer = await send(tabId, "Page.navigate", { url: target.url });
    if (answer.errorText)
      throw new OperationError("failed", `Navigation to ${target.url} failed: ${answer.errorText}`);
  } else if (target.history === "reload") {
    await send(tabId, "Page.reload");
  } else {
    const { currentIndex, entries } = await send(tabId, "Page.getNavigationHistory");
    const entry = entries[currentIndex + (target.history === "back" ? -1 : 1)];
    if (!entry) throw new OperationError("failed", `There is no page to go ${target.history} to.`);
    if (!isShared(grant, entry.url))
      throw new OperationError("failed", "That page is on a site that the user did not share with this chat.");
    await send(tabId, "Page.navigateToHistoryEntry", { entryId: entry.id });
    // A page restored from the back-forward cache stays "interactive" with
    // the debugger attached, so a history move waits for its parsed page.
    readiness = "domcontentloaded";
  }
  stateOf(tabId).refs.clear();
  await sleep(POLL_MS);
  await waitForReady(tabId, readiness, deadline);
}

// ---- methods ----

const optString = (params, key) => (typeof params[key] === "string" ? params[key] : undefined);
const optNumber = (params, key) => (typeof params[key] === "number" ? params[key] : undefined);
const targetOf = (params) => ({ ref: optString(params, "ref"), selector: optString(params, "selector") });
const hasTarget = (target) => target.ref !== undefined || target.selector !== undefined;

/**
 * Run one tool call. `grant` is the chat's grant; `hooks.addTab` adds a tab
 * that the agent opened to it, and `hooks.setCurrent` sets the current tab.
 */
export async function call(grant, method, params, hooks, commandDeadline = Infinity) {
  const timeoutMs = Math.min(optNumber(params, "timeoutMs") ?? DEFAULT_TIMEOUT_MS, 60_000);
  // The server stops waiting at the command's deadline; so does the call.
  const deadline = Math.min(Date.now() + timeoutMs, commandDeadline);
  switch (method) {
    case "status": {
      const tabs = [];
      for (const tabId of grant.tabs) tabs.push(await tabJson(grant, tabId).catch(() => null));
      return {
        tabs: tabs.filter(Boolean),
        current: String(grant.current),
      };
    }
    case "open": {
      const raw = optString(params, "url");
      const url = raw === undefined ? undefined : normalizeUrl(raw);
      if (url !== undefined && !isShared(grant, url))
        throw new OperationError("failed", outsideMessage(url));
      const newTab = params.newTab === true;
      if (!newTab) {
        const tabId = grant.current;
        await sharedTab(grant, tabId);
        checkWritable(tabId);
        if (url !== undefined) await navigateTab(grant, tabId, { url }, "domcontentloaded", deadline);
        return { tab: await tabJson(grant, tabId) };
      }
      if (grant.tabs.length >= MAX_TABS)
        throw new OperationError("tab_limit", `This chat has ${MAX_TABS} tabs. Close one first.`);
      const opener = await chrome.tabs.get(grant.current).catch(() => null);
      const tab = await chrome.tabs.create({
        url: url ?? "about:blank",
        active: true,
        ...(opener ? { windowId: opener.windowId, openerTabId: opener.id } : {}),
      });
      await hooks.addTab(tab.id);
      await attach(tab.id);
      await waitForReady(tab.id, "domcontentloaded", deadline);
      return { tab: await tabJson(grant, tab.id) };
    }
    case "navigate": {
      const tabId = resolveTab(grant, params);
      await sharedTab(grant, tabId);
      checkWritable(tabId);
      const url = optString(params, "url");
      const history = optString(params, "history");
      if ((url === undefined) === (history === undefined))
        throw invalid("Pass exactly one of url or history.");
      if (history !== undefined && !["back", "forward", "reload"].includes(history))
        throw invalid("history must be back, forward or reload.");
      await hooks.setCurrent(tabId);
      await navigateTab(grant, tabId, url === undefined ? { history } : { url: normalizeUrl(url) }, "load", deadline);
      return { tab: await tabJson(grant, tabId) };
    }
    case "snapshot": {
      const tabId = resolveTab(grant, params);
      const tab = await sharedTab(grant, tabId);
      const state = stateOf(tabId);
      if (state.dialog) throw dialogPending();
      if (optString(params, "screenshotPath") !== undefined)
        throw invalid("screenshot_path is not available in the user's Chrome.");
      await hooks.setCurrent(tabId);
      const text = await snapshotText(grant, tab, state);
      // A page that changed sites during the read gives no snapshot.
      await sharedTab(grant, tabId).catch((error) => {
        state.refs.clear();
        throw error;
      });
      return { tab: await tabJson(grant, tabId), text };
    }
    case "act": {
      const tabId = resolveTab(grant, params);
      await sharedTab(grant, tabId);
      checkWritable(tabId);
      await hooks.setCurrent(tabId);
      const message = await act(grant, tabId, params, deadline);
      return { tab: await tabJson(grant, tabId), ...(message === undefined ? {} : { message }) };
    }
    case "waitFor": {
      const tabId = resolveTab(grant, params);
      await sharedTab(grant, tabId);
      const target = targetOf(params);
      const text = optString(params, "text");
      const urlIncludes = optString(params, "urlIncludes");
      if (!hasTarget(target) && text === undefined && urlIncludes === undefined)
        throw invalid("Pass ref, selector, text or urlIncludes.");
      for (;;) {
        // A tab that left the shared sites ends the wait.
        await sharedTab(grant, tabId);
        if (stateOf(tabId).dialog) throw dialogPending();
        if (await conditionsMet(grant, tabId, target, text, urlIncludes))
          return { tab: await tabJson(grant, tabId) };
        if (Date.now() >= deadline)
          throw new OperationError("timeout", `The page did not match within ${timeoutMs}ms.`);
        await sleep(POLL_MS);
      }
    }
    case "dialog": {
      const tabId = resolveTab(grant, params);
      await sharedTab(grant, tabId);
      if (typeof params.accept !== "boolean") throw invalid("accept is required.");
      if (isHumanControlled(tabId))
        throw new OperationError("human_control", HUMAN_CONTROL_MESSAGE);
      const state = stateOf(tabId);
      if (!state.dialog) throw new OperationError("failed", "No dialog is pending.");
      await checkLive({ grant, tabId, deadline });
      await send(tabId, "Page.handleJavaScriptDialog", {
        accept: params.accept,
        ...(optString(params, "promptText") === undefined ? {} : { promptText: params.promptText }),
      });
      state.dialog = null;
      state.refs.clear();
      await hooks.setCurrent(tabId);
      return { tab: await tabJson(grant, tabId) };
    }
    case "evaluate":
      throw new OperationError("failed", "Page scripts do not run in the user's Chrome.");
    default:
      throw invalid(`Unknown method ${String(method).slice(0, 50)}.`);
  }
}

async function conditionsMet(grant, tabId, target, text, urlIncludes) {
  if (urlIncludes !== undefined || text !== undefined) {
    // One read of one document checks both.
    const found = await send(tabId, "Runtime.evaluate", {
      expression: `location.href.includes(${JSON.stringify(urlIncludes ?? "")}) &&
        (document.body?.innerText ?? "").includes(${JSON.stringify(text ?? "")})`,
      returnByValue: true,
    }).then((answer) => answer.result?.value === true).catch(() => false);
    if (!found) return false;
  }
  if (hasTarget(target)) {
    try {
      await resolveTarget(tabId, target, 0);
    } catch (error) {
      if (error.code === "stale_ref") throw error;
      return false;
    }
  }
  return true;
}

async function act(grant, tabId, params, deadline) {
  const ctx = { grant, tabId, deadline };
  const action = optString(params, "action");
  const target = targetOf(params);
  switch (action) {
    case "click":
    case "hover": {
      const x = optNumber(params, "x");
      const y = optNumber(params, "y");
      let point;
      if (hasTarget(target)) {
        const objectId = await resolveTarget(tabId, target, deadline);
        point = await actionPoint(tabId, objectId, deadline);
      } else if (x !== undefined && y !== undefined) {
        point = { x, y };
      } else {
        throw invalid(`${action} needs ref, selector, or x and y.`);
      }
      await checkPoint(grant, tabId, point);
      if (action === "hover") {
        await input(ctx, "Input.dispatchMouseEvent", { type: "mouseMoved", ...point });
        return undefined;
      }
      const button = optString(params, "button") ?? "left";
      if (!["left", "right", "middle"].includes(button))
        throw invalid("button must be left, right or middle.");
      await mouseClick(ctx, point, button, Math.min(Math.max(optNumber(params, "clickCount") ?? 1, 1), 3));
      return undefined;
    }
    case "type": {
      const text = optString(params, "text");
      if (text === undefined) throw invalid("type needs text.");
      // Without a target, type into the focused element, as the sandbox's browser does.
      const objectId = hasTarget(target)
        ? await resolveTarget(tabId, target, deadline)
        : await focusedElement(tabId);
      const kind = await callOn(tabId, objectId, function () {
        if (this.isContentEditable) return "ok";
        const tag = this.tagName;
        if (tag === "TEXTAREA") return this.disabled || this.readOnly ? "no" : "ok";
        if (tag !== "INPUT") return "no";
        const type = (this.getAttribute("type") || "text").toLowerCase();
        if (type === "password") return "password";
        if (this.disabled || this.readOnly) return "no";
        if (["date", "time", "datetime-local", "month", "week"].includes(type)) return "picker";
        const textual = ["text", "search", "email", "url", "tel", "number"];
        return textual.includes(type) ? "ok" : "no";
      });
      if (kind === "password") throw passwordRefused();
      if (kind === "picker") {
        // Picker fields take a whole value, not typed text.
        await checkLive(ctx);
        const taken = await callOn(
          tabId,
          objectId,
          function (value) {
            // Check the value on a detached field first, so a bad value
            // leaves the live field and its listeners alone.
            const probe = this.ownerDocument.createElement("input");
            probe.type = this.type;
            probe.value = value;
            if (probe.value !== value) return false;
            const setter = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value").set;
            setter.call(this, value);
            this.dispatchEvent(new Event("input", { bubbles: true }));
            this.dispatchEvent(new Event("change", { bubbles: true }));
            return this.value === value;
          },
          [text]
        );
        if (!taken)
          throw invalid(
            "The field did not take the value. Use its value format, such as 2026-12-01, 13:30, 2026-12-01T13:30, 2026-12 or 2026-W49."
          );
        return undefined;
      }
      if (kind !== "ok") throw new OperationError("not_editable", "The element is not an editable field.");
      await send(tabId, "DOM.focus", { objectId });
      await checkFocus(grant, tabId);
      if (params.clear === true) {
        await callOn(tabId, objectId, function () {
          if (typeof this.select === "function") this.select();
          else this.ownerDocument.getSelection().selectAllChildren(this);
        });
        if (text === "") await pressKey(ctx, "Delete");
      }
      if (text !== "") await input(ctx, "Input.insertText", { text });
      return undefined;
    }
    case "select": {
      const values = Array.isArray(params.values) ? params.values.map(String) : undefined;
      if (!hasTarget(target) || values === undefined)
        throw invalid("select needs ref or selector, and values.");
      const objectId = await resolveTarget(tabId, target, deadline);
      await checkLive(ctx);
      const selected = await callOn(
        tabId,
        objectId,
        function (wanted) {
          if (this.tagName !== "SELECT") return { error: "The element is not a <select>." };
          const options = [...this.options];
          const picked = wanted.map((value) =>
            options.find((option) => option.value === value || option.label === value || option.text.trim() === value)
          );
          if (picked.some((option) => !option)) return { error: "No option matches." };
          if (!this.multiple && picked.length > 1) return { error: "The <select> takes one value." };
          for (const option of options) option.selected = picked.includes(option);
          this.dispatchEvent(new Event("input", { bubbles: true }));
          this.dispatchEvent(new Event("change", { bubbles: true }));
          return { labels: picked.map((option) => option.label) };
        },
        [values]
      );
      if (selected?.error) throw new OperationError("failed", selected.error);
      return `Selected: ${selected.labels.join(", ")}`;
    }
    case "drag": {
      const targetRef = optString(params, "targetRef");
      if (!hasTarget(target) || targetRef === undefined)
        throw invalid("drag needs ref or selector, and targetRef.");
      const from = await actionPoint(tabId, await resolveTarget(tabId, target, deadline), deadline);
      const to = await actionPoint(tabId, await resolveTarget(tabId, { ref: targetRef }, deadline), deadline);
      await checkPoint(grant, tabId, from);
      await checkPoint(grant, tabId, to);
      await input(ctx, "Input.dispatchMouseEvent", { type: "mouseMoved", ...from });
      await input(ctx, "Input.dispatchMouseEvent", { type: "mousePressed", ...from, button: "left", clickCount: 1 });
      for (let step = 1; step <= 5; step += 1) {
        await input(ctx, "Input.dispatchMouseEvent", {
          type: "mouseMoved",
          x: from.x + ((to.x - from.x) * step) / 5,
          y: from.y + ((to.y - from.y) * step) / 5,
          button: "left",
          buttons: 1,
        });
      }
      await input(ctx, "Input.dispatchMouseEvent", { type: "mouseReleased", ...to, button: "left", clickCount: 1 });
      return undefined;
    }
    case "press": {
      const key = optString(params, "key");
      if (!key) throw invalid("press needs key.");
      const modifiers = Array.isArray(params.modifiers) ? params.modifiers.map(String) : [];
      await checkFocus(grant, tabId);
      await pressKey(ctx, key, modifiers);
      return undefined;
    }
    case "scroll": {
      const point = hasTarget(target)
        ? await actionPoint(tabId, await resolveTarget(tabId, target, deadline), deadline)
        : await viewportCenter(tabId);
      await checkPoint(grant, tabId, point);
      const deltaX = optNumber(params, "deltaX") ?? 0;
      const deltaY = optNumber(params, "deltaY") ?? (optNumber(params, "deltaX") === undefined ? 400 : 0);
      await input(ctx, "Input.dispatchMouseEvent", { type: "mouseWheel", ...point, deltaX, deltaY });
      return undefined;
    }
    case "upload":
      throw new OperationError("failed", "upload is not available in the user's Chrome.");
    default:
      throw invalid("action must be click, type, hover, select, drag, press or scroll.");
  }
}
