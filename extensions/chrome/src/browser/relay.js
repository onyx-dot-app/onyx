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
export const CONNECT_ALARM = "onyxBrowserConnect";
const PING_MS = 20_000;
const MAX_BACKOFF_MS = 60_000;
const GROUP_TITLE = "Onyx";

let socket = null;
let connecting = false;
let pingTimer = null;
let failures = 0;
let retryTimer = null;
let commands = Promise.resolve();

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
  if (await controlDisabled()) {
    await setStatus({ state: "disabled" });
    return;
  }
  connecting = true;
  try {
    const domain = await getOnyxDomain();
    const response = await fetch(`${domain}/api/chat/browser/extension/token`, {
      method: "POST",
      credentials: "include",
    });
    if (!response.ok) {
      await setStatus({
        state: response.status === 401 || response.status === 403 ? "signed_out" : "offline",
      });
      scheduleRetry();
      return;
    }
    const { token } = await response.json();
    const url = `${domain.replace(/^http/, "ws")}/api/chat/browser/extension/ws?token=${encodeURIComponent(token)}`;
    const ws = new WebSocket(url);
    socket = ws;
    ws.onopen = async () => {
      ws.send(
        JSON.stringify({
          type: "hello",
          installation_id: await installationId(),
          label: `Chrome on ${navigator.userAgentData?.platform || navigator.platform}`,
          version: chrome.runtime.getManifest().version,
        })
      );
      clearInterval(pingTimer);
      pingTimer = setInterval(() => sendMessage({ type: "ping" }), PING_MS);
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
      if (socket === ws) socket = null;
      clearInterval(pingTimer);
      void setStatus({ state: event.code === 4403 ? "disabled" : "offline" });
      scheduleRetry();
    };
  } catch (error) {
    socket = null;
    await setStatus({ state: "offline" });
    scheduleRetry();
  } finally {
    connecting = false;
  }
}

export async function reconnect() {
  socket?.close();
  socket = null;
  failures = 0;
  await connect();
}

async function handleMessage(message) {
  switch (message.type) {
    case "welcome":
      failures = 0;
      await setStatus({ state: "connected" });
      await reportGrant();
      break;
    case "command":
      commands = commands.then(() => runCommand(message));
      break;
    case "grant_request":
      await showConsent(message);
      break;
    case "grant_saved": {
      const grant = await getGrant();
      if (grant && grant.chat_session_id === message.chat_session_id && grant.request_id) {
        await setGrant({ ...grant, request_id: null });
      }
      break;
    }
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
    const work = driver.call(grant, message.method, message.params ?? {}, {
      addTab: (tabId) => addTab(tabId),
      setCurrent: (tabId) => setCurrent(tabId),
    });
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

async function tabsFor(grant) {
  const tabs = [];
  for (const id of grant.tabs) {
    const tab = await chrome.tabs.get(id).catch(() => null);
    if (tab) tabs.push({ id: String(tab.id), title: tab.title ?? "", url: tab.url ?? "" });
  }
  return tabs;
}

async function reportGrant() {
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

async function showConsent(message) {
  const requests = await readSession(REQUESTS_KEY, {});
  requests[message.request_id] = {
    request_id: message.request_id,
    chat_session_id: message.chat_session_id,
    chat_title: message.chat_title,
    account: message.account,
    domain: await getOnyxDomain(),
  };
  await chrome.storage.session.set({ [REQUESTS_KEY]: requests });
  await chrome.windows.create({
    url: chrome.runtime.getURL(`src/pages/browser-consent.html?request=${message.request_id}`),
    type: "popup",
    width: 480,
    height: 680,
    focused: true,
  });
}

async function takeRequest(requestId) {
  const requests = await readSession(REQUESTS_KEY, {});
  const request = requests[requestId];
  delete requests[requestId];
  await chrome.storage.session.set({ [REQUESTS_KEY]: requests });
  return request ?? null;
}

async function groupTabs(tabIds) {
  try {
    const groupId = await chrome.tabs.group({ tabIds });
    await chrome.tabGroups.update(groupId, { title: GROUP_TITLE, color: "purple" });
  } catch (error) {
    console.warn("[Onyx browser] Could not group tabs", error);
  }
}

async function approve(requestId, tabIds, minutes) {
  const request = await takeRequest(requestId);
  if (!request) throw new Error("This request expired. Ask again from the Onyx chat.");
  const tabs = [];
  for (const id of tabIds) {
    const tab = await chrome.tabs.get(id).catch(() => null);
    if (tab && driver.originOf(tab.url ?? "")) tabs.push(tab);
  }
  if (tabs.length === 0) throw new Error("Pick at least one web page tab.");
  await endGrant(true);
  const origins = [...new Set(tabs.map((tab) => driver.originOf(tab.url)))];
  const grant = {
    chat_session_id: request.chat_session_id,
    chat_title: request.chat_title,
    request_id: request.request_id,
    tabs: tabs.map((tab) => tab.id),
    origins,
    expires_at: Date.now() / 1000 + Math.min(Math.max(minutes, 5), 480) * 60,
    current: tabs[0].id,
  };
  await setGrant(grant);
  for (const tab of tabs) await driver.attach(tab.id);
  await groupTabs(grant.tabs);
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

export async function endGrant(notify) {
  const grant = await getGrant();
  if (!grant) return;
  await chrome.storage.session.remove(GRANT_KEY);
  for (const tabId of grant.tabs) {
    await driver.detach(tabId);
    await chrome.tabs.ungroup(tabId).catch(() => {});
  }
  if (notify) sendMessage({ type: "grant_ended", chat_session_id: grant.chat_session_id });
}

async function addTab(tabId) {
  const grant = await getGrant();
  if (!grant) return;
  grant.tabs = [...new Set([...grant.tabs, tabId])];
  grant.current = tabId;
  await setGrant(grant);
  await groupTabs([tabId]);
  await reportGrant();
}

async function setCurrent(tabId) {
  const grant = await getGrant();
  if (grant && grant.current !== tabId) await setGrant({ ...grant, current: tabId });
}

export async function onTabRemoved(tabId) {
  driver.forgetTab(tabId);
  const grant = await getGrant();
  if (!grant || !grant.tabs.includes(tabId)) return;
  grant.tabs = grant.tabs.filter((id) => id !== tabId);
  if (grant.tabs.length === 0) {
    await endGrant(true);
    return;
  }
  if (grant.current === tabId) grant.current = grant.tabs[0];
  await setGrant(grant);
  await reportGrant();
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
      return respond(approve(request.request_id, request.tab_ids, request.minutes));
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
