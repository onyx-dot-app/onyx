// The extension's link to Onyx for chat browser control. It keeps one
// websocket to the Onyx deployment, answers the commands of the chat that
// the user shared tabs with, and keeps that grant. The backend half is
// backend/onyx/browser_extension/relay.py.

import { BROWSER_MESSAGES, CHROME_SPECIFIC_STORAGE_KEYS } from "../utils/constants.js";
import { getOnyxDomain, getManagedSettings } from "../utils/storage.js";
import * as driver from "./driver.js";

const GRANT_KEY = "onyxBrowserGrant";
const REQUESTS_KEY = "onyxBrowserRequests";
const STATUS_KEY = "onyxBrowserStatus";
const INSTALLATION_KEY = "onyxBrowserInstallationId";
// Stops that Onyx has not heard yet: sent on the next welcome.
const PENDING_ENDS_KEY = "onyxBrowserPendingEnds";
export const CONNECT_ALARM = "onyxBrowserConnect";
const PING_MS = 20_000;
const MAX_BACKOFF_MS = 60_000;
const GROUP_TITLE = "Onyx";

let socket = null;
let connecting = false;
let failures = 0;
let retryTimer = null;
let commands = Promise.resolve();
// Each reconnect starts a new generation; an older connect attempt stops.
let generation = 0;
// Changes of the grant run one at a time, so a late write never brings back
// a grant that Stop removed.
let grantChanges = Promise.resolve();

function serial(change) {
  const run = grantChanges.then(change);
  grantChanges = run.catch(() => {});
  return run;
}

// ---- state in chrome.storage.session ----

async function readSession(key, fallback) {
  const stored = await chrome.storage.session.get(key);
  return stored[key] ?? fallback;
}

const getGrant = () => readSession(GRANT_KEY, null);
const setGrant = (grant) => chrome.storage.session.set({ [GRANT_KEY]: grant });

async function setStatus(status) {
  await chrome.storage.session.set({ [STATUS_KEY]: status });
}

async function installationId() {
  const stored = await chrome.storage.local.get(INSTALLATION_KEY);
  if (stored[INSTALLATION_KEY]) return stored[INSTALLATION_KEY];
  const id = crypto.randomUUID();
  await chrome.storage.local.set({ [INSTALLATION_KEY]: id });
  return id;
}

async function controlDisabled() {
  const managed = await getManagedSettings();
  return managed[CHROME_SPECIFIC_STORAGE_KEYS.BROWSER_CONTROL_DISABLED] === true;
}

// ---- socket ----

function sendMessage(message) {
  if (socket?.readyState === WebSocket.OPEN) {
    socket.send(JSON.stringify(message));
    return true;
  }
  return false;
}

// The 1-minute alarm also calls connect(), so the backoff stays short.
function scheduleRetry() {
  failures += 1;
  clearTimeout(retryTimer);
  retryTimer = setTimeout(connect, Math.min(1000 * 2 ** failures, MAX_BACKOFF_MS));
}

export async function connect() {
  if (socket || connecting) return;
  connecting = true;
  const attempt = generation;
  // A reconnect started a newer attempt: this one changes nothing more.
  const stale = () => attempt !== generation;
  try {
    if (await controlDisabled()) {
      if (!stale()) await setStatus({ state: "disabled" });
      return;
    }
    if (stale()) return;
    const domain = await getOnyxDomain();
    const response = await fetch(`${domain}/api/chat/browser/extension/token`, {
      method: "POST",
      credentials: "include",
    });
    if (stale()) return;
    if (!response.ok) {
      await setStatus({
        state: response.status === 401 || response.status === 403 ? "signed_out" : "offline",
      });
      scheduleRetry();
      return;
    }
    const { token } = await response.json();
    // A reconnect or a policy change while the token was on its way wins.
    if (stale() || (await controlDisabled()) || stale()) return;
    const url = `${domain.replace(/^http/, "ws")}/api/chat/browser/extension/ws?token=${encodeURIComponent(token)}`;
    const ws = new WebSocket(url);
    socket = ws;
    let wsPing = null;
    ws.onopen = async () => {
      ws.send(
        JSON.stringify({
          type: "hello",
          installation_id: await installationId(),
          label: `Chrome on ${navigator.userAgentData?.platform || navigator.platform}`,
          version: chrome.runtime.getManifest().version,
        })
      );
      wsPing = setInterval(() => {
        if (ws.readyState === WebSocket.OPEN) ws.send(JSON.stringify({ type: "ping" }));
      }, PING_MS);
    };
    ws.onmessage = (event) => {
      let message;
      try {
        message = JSON.parse(event.data);
      } catch {
        return;
      }
      void handleMessage(message).catch((error) => console.error("[Onyx browser]", error));
    };
    ws.onclose = (event) => {
      clearInterval(wsPing);
      // An old socket's close leaves its replacement alone.
      if (socket !== ws) return;
      socket = null;
      void setStatus({ state: event.code === 4403 ? "disabled" : "offline" });
      scheduleRetry();
    };
  } catch (error) {
    if (stale()) return;
    socket = null;
    await setStatus({ state: "offline" });
    scheduleRetry();
  } finally {
    if (!stale()) connecting = false;
  }
}

export async function reconnect() {
  generation += 1;
  socket?.close();
  socket = null;
  connecting = false;
  failures = 0;
  await connect();
}

async function handleMessage(message) {
  switch (message.type) {
    case "welcome":
      failures = 0;
      await setStatus({ state: "connected" });
      await sendPendingEnds();
      await reportGrant();
      break;
    case "command":
      commands = commands.then(() => runCommand(message));
      break;
    case "grant_request":
      await showConsent(message);
      break;
    case "grant_saved":
      await serial(async () => {
        const grant = await getGrant();
        if (grant && grant.chat_session_id === message.chat_session_id && grant.request_id)
          await setGrant({ ...grant, request_id: null });
      });
      break;
    case "end_grant": {
      const grant = await getGrant();
      if (grant && grant.chat_session_id === message.chat_session_id) await endGrant(false);
      break;
    }
    default:
      break;
  }
}

// ---- commands ----

async function runCommand(message) {
  let reply;
  try {
    if (message.deadline * 1000 <= Date.now())
      throw new driver.OperationError("timeout", "The call expired before Chrome could start it.");
    const grant = await getGrant();
    if (!grant || grant.chat_session_id !== message.chat_session_id)
      throw new driver.OperationError(
        "no_grant",
        "The user's Chrome is no longer shared with this chat. Ask the user to share a tab again."
      );
    if (grant.expires_at * 1000 <= Date.now()) {
      await endGrant(true);
      throw new driver.OperationError("no_grant", "The user's share of Chrome with this chat ended.");
    }
    // The server stops waiting at the deadline; a call never holds the queue past it.
    let timer;
    const expired = new Promise((_, reject) => {
      timer = setTimeout(
        () => reject(new driver.OperationError("timeout", "Chrome did not finish in time. Check the page before you retry.")),
        Math.max(0, message.deadline * 1000 - Date.now())
      );
    });
    // The hooks act only on the grant that the command started with.
    const work = driver.call(
      grant,
      message.method,
      message.params ?? {},
      {
        addTab: (tabId) => addTab(tabId, grant.id),
        setCurrent: (tabId) => setCurrent(tabId, grant.id),
      },
      message.deadline * 1000
    );
    work.catch(() => {});
    const result = await Promise.race([work, expired]).finally(() => clearTimeout(timer));
    reply = { ok: true, result };
  } catch (error) {
    reply = {
      ok: false,
      error: {
        code: error.code ?? "failed",
        message: String(error.message ?? error).slice(0, 2000),
      },
    };
  }
  sendMessage({ type: "result", command_id: message.command_id, ...reply });
}

// ---- grants ----

// The relay's limits on a tab's title and URL.
const MAX_TITLE_CHARS = 500;
const MAX_URL_CHARS = 2048;

/** The shared tabs as Onyx shows them. A tab on a site that the user did not
 * share goes without its title and URL. */
async function tabsFor(grant) {
  const tabs = [];
  for (const id of grant.tabs) {
    const tab = await chrome.tabs.get(id).catch(() => null);
    if (!tab) continue;
    const origin = driver.originOf(tab.url ?? "");
    const shared = origin !== null && grant.origins.includes(origin);
    tabs.push({
      id: String(tab.id),
      title: shared ? (tab.title ?? "").slice(0, MAX_TITLE_CHARS) : "",
      url: shared ? (tab.url ?? "").slice(0, MAX_URL_CHARS) : "",
    });
  }
  return tabs;
}

/** Report the grant to Onyx, in turn with the other grant changes, so a
 * report never overtakes a Stop. */
function reportGrant() {
  return serial(sendGrant);
}

async function sendGrant() {
  const grant = await getGrant();
  if (!grant) return;
  sendMessage({
    type: "grant",
    grant: {
      chat_session_id: grant.chat_session_id,
      request_id: grant.request_id,
      tabs: await tabsFor(grant),
      origins: grant.origins,
      expires_at: grant.expires_at,
    },
  });
}

// Changes of the request table run one at a time, so two requests that
// arrive together both stay.
let requestChanges = Promise.resolve();

function changeRequests(change) {
  const run = requestChanges.then(async () => {
    const requests = await readSession(REQUESTS_KEY, {});
    const result = await change(requests);
    await chrome.storage.session.set({ [REQUESTS_KEY]: requests });
    return result;
  });
  requestChanges = run.catch(() => {});
  return run;
}

async function showConsent(message) {
  const domain = await getOnyxDomain();
  await changeRequests((requests) => {
    requests[message.request_id] = {
    request_id: message.request_id,
    chat_session_id: message.chat_session_id,
    chat_title: message.chat_title,
    account: message.account,
    deadline: message.deadline,
    domain,
    };
  });
  await chrome.windows.create({
    url: chrome.runtime.getURL(`src/pages/browser-consent.html?request=${message.request_id}`),
    type: "popup",
    width: 480,
    height: 680,
    focused: true,
  });
}

function takeRequest(requestId) {
  return changeRequests((requests) => {
    const request = requests[requestId];
    delete requests[requestId];
    return request ?? null;
  });
}

/** Put the tabs that are in no group into the share's Onyx group. Tabs in
 * the user's own groups stay there. Returns the Onyx group's ID. */
async function groupTabs(tabIds, groupId) {
  try {
    const loose = [];
    for (const id of tabIds) {
      const tab = await chrome.tabs.get(id).catch(() => null);
      if (tab && tab.groupId === chrome.tabGroups.TAB_GROUP_ID_NONE) loose.push(id);
    }
    if (loose.length === 0) return groupId;
    if (groupId != null) {
      const group = await chrome.tabGroups.get(groupId).catch(() => null);
      if (group) return await chrome.tabs.group({ tabIds: loose, groupId });
    }
    const created = await chrome.tabs.group({ tabIds: loose });
    await chrome.tabGroups.update(created, { title: GROUP_TITLE, color: "purple" });
    return created;
  } catch (error) {
    console.warn("[Onyx browser] Could not group tabs", error);
    return groupId;
  }
}

// The relay's limit on the tabs of one grant.
const MAX_GRANT_TABS = 50;

async function approve(requestId, tabIds, minutes, shownOrigins) {
  // `shownOrigins` maps each tab ID to the site that the window showed for it.
  const request = (await readSession(REQUESTS_KEY, {}))[requestId];
  if (!request || request.deadline * 1000 <= Date.now()) {
    await takeRequest(requestId);
    throw new Error("This request expired. Ask again from the Onyx chat.");
  }
  // The request belongs to the deployment and policy that the window showed.
  if (request.domain !== (await getOnyxDomain()) || (await controlDisabled())) {
    await takeRequest(requestId);
    throw new Error("Onyx settings changed. Ask again from the Onyx chat.");
  }
  const tabs = [];
  for (const id of tabIds) {
    const tab = await chrome.tabs.get(id).catch(() => null);
    if (tab && driver.originOf(tab.url ?? "")) tabs.push(tab);
  }
  if (tabs.length === 0) throw new Error("Pick at least one web page tab.");
  if (tabs.length > MAX_GRANT_TABS) throw new Error(`Pick ${MAX_GRANT_TABS} tabs or fewer.`);
  const origins = [...new Set(tabs.map((tab) => driver.originOf(tab.url)))];
  // Each tab must still be on the site that the window showed for it.
  if (tabs.some((tab) => shownOrigins[String(tab.id)] !== driver.originOf(tab.url)))
    throw new Error("A tab moved to another site. Check the sites and allow again.");
  await serial(async () => {
    // The deployment or policy may have changed during the lookups above.
    if (request.domain !== (await getOnyxDomain()) || (await controlDisabled())) {
      await takeRequest(requestId);
      throw new Error("Onyx settings changed. Ask again from the Onyx chat.");
    }
    await endGrantNow(true);
    // The grant is saved only once every tab is under control; on a failure
    // the request stays, so Allow can try again.
    const attached = [];
    try {
      for (const tab of tabs) {
        await driver.attach(tab.id);
        attached.push(tab.id);
      }
    } catch (error) {
      for (const tabId of attached) await driver.detach(tabId);
      throw error;
    }
    await takeRequest(requestId);
    const grant = {
      id: crypto.randomUUID(),
      chat_session_id: request.chat_session_id,
      chat_title: request.chat_title,
      request_id: request.request_id,
      tabs: tabs.map((tab) => tab.id),
      origins,
      expires_at: Date.now() / 1000 + Math.min(Math.max(minutes, 5), 480) * 60,
      current: tabs[0].id,
      group_id: null,
    };
    await setGrant({ ...grant, group_id: await groupTabs(grant.tabs, null) });
  });
  await reportGrant();
}

async function deny(requestId) {
  const request = await takeRequest(requestId);
  if (request) sendMessage({
      type: "grant_denied",
      chat_session_id: request.chat_session_id,
      request_id: requestId,
    });
}

export function endGrant(notify) {
  return serial(() => endGrantNow(notify));
}

async function endGrantNow(notify) {
  const grant = await getGrant();
  if (!grant) return;
  // Calls of this grant that still run stop at their next step.
  driver.grantEnded(grant.id);
  await chrome.storage.session.remove(GRANT_KEY);
  for (const tabId of grant.tabs) {
    await driver.detach(tabId);
    // Only tabs still in the share's own group leave it.
    const tab = await chrome.tabs.get(tabId).catch(() => null);
    if (tab && grant.group_id != null && tab.groupId === grant.group_id)
      await chrome.tabs.ungroup(tabId).catch(() => {});
  }
  if (notify) await notifyEnd(grant.chat_session_id);
}

/** Tell Onyx that a share ended; while offline, keep the stop for the next
 * connection. */
async function notifyEnd(chatSessionId) {
  const message = { type: "grant_ended", chat_session_id: chatSessionId };
  if (sendMessage(message)) return;
  const pending = await readSession(PENDING_ENDS_KEY, []);
  if (!pending.includes(chatSessionId))
    await chrome.storage.session.set({ [PENDING_ENDS_KEY]: [...pending, chatSessionId] });
}

async function sendPendingEnds() {
  const pending = await readSession(PENDING_ENDS_KEY, []);
  if (pending.length === 0) return;
  await chrome.storage.session.remove(PENDING_ENDS_KEY);
  const current = await getGrant();
  for (const chatSessionId of pending) {
    // A chat shared again since then keeps its new share.
    if (current?.chat_session_id !== chatSessionId)
      sendMessage({ type: "grant_ended", chat_session_id: chatSessionId });
  }
}

/** Add a tab that the agent opened to the chat's grant. A tab opened for a
 * grant that ended meanwhile is let go. */
async function addTab(tabId, grantId) {
  const added = await serial(async () => {
    const grant = await getGrant();
    if (!grant || grant.id !== grantId) {
      await driver.detach(tabId);
      return false;
    }
    const tabs = [...new Set([...grant.tabs, tabId])];
    await setGrant({ ...grant, tabs, current: tabId });
    const groupId = await groupTabs([tabId], grant.group_id);
    await setGrant({ ...grant, tabs, current: tabId, group_id: groupId });
    return true;
  });
  if (!added)
    throw new driver.OperationError("no_grant", "The user's share of Chrome with this chat ended.");
  await reportGrant();
}

function setCurrent(tabId, grantId) {
  return serial(async () => {
    const grant = await getGrant();
    if (grant && grant.id === grantId && grant.current !== tabId)
      await setGrant({ ...grant, current: tabId });
  });
}

export async function onTabRemoved(tabId) {
  driver.forgetTab(tabId);
  const changed = await serial(async () => {
    const grant = await getGrant();
    if (!grant || !grant.tabs.includes(tabId)) return false;
    const tabs = grant.tabs.filter((id) => id !== tabId);
    if (tabs.length === 0) {
      await endGrantNow(true);
      return false;
    }
    await setGrant({ ...grant, tabs, current: grant.current === tabId ? tabs[0] : grant.current });
    return true;
  });
  if (changed) await reportGrant();
}

export async function onTabUpdated(tabId, changeInfo) {
  if (!changeInfo.url && !changeInfo.title) return;
  const grant = await getGrant();
  if (grant?.tabs.includes(tabId)) await reportGrant();
}

/** The user closed Chrome's "is debugging this browser" bar: stop. */
export async function onDebuggerDetach(source, reason) {
  driver.forgetTab(source.tabId);
  const grant = await getGrant();
  if (!grant || !grant.tabs.includes(source.tabId)) return;
  if (reason === "canceled_by_user") await endGrant(true);
}

export async function checkExpiry() {
  const grant = await getGrant();
  if (grant && grant.expires_at * 1000 <= Date.now()) await endGrant(true);
}

/** Messages from the consent window and the popup. */
export function handleRuntimeMessage(request, sendResponse) {
  const respond = (promise) => {
    promise.then(
      (value) => sendResponse({ ok: true, value }),
      (error) => sendResponse({ ok: false, error: String(error.message ?? error) })
    );
    return true;
  };
  switch (request.action) {
    case BROWSER_MESSAGES.APPROVE:
      return respond(
        approve(request.request_id, request.tab_ids, request.minutes, request.tab_origins ?? {})
      );
    case BROWSER_MESSAGES.DENY:
      return respond(deny(request.request_id));
    case BROWSER_MESSAGES.STOP:
      return respond(endGrant(true));
    case BROWSER_MESSAGES.STATE:
      return respond(
        (async () => ({
          status: await readSession(STATUS_KEY, { state: "offline" }),
          grant: await getGrant(),
          request: (await readSession(REQUESTS_KEY, {}))[request.request_id] ?? null,
        }))()
      );
    default:
      return false;
  }
}
