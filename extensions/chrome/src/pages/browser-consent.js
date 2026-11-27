import { originOf } from "../browser/driver.js";
import { BROWSER_MESSAGES } from "../utils/constants.js";

const requestId = new URLSearchParams(location.search).get("request") ?? "";
const errorText = document.getElementById("error");
const allowButton = document.getElementById("allow");
const denyButton = document.getElementById("deny");
const tabsBox = document.getElementById("tabs");
const originsList = document.getElementById("origins");

const ask = (message) => chrome.runtime.sendMessage(message);

function checkedTabIds() {
  return [...tabsBox.querySelectorAll("input:checked")].map((box) => Number(box.value));
}

// The site that the window shows for each tab; Allow shares only these.
let shownTabOrigins = {};

function renderOrigins(tabs) {
  const chosen = new Set(checkedTabIds());
  const origins = [...new Set(tabs.filter((tab) => chosen.has(tab.id)).map((tab) => originOf(tab.url)))];
  shownTabOrigins = Object.fromEntries(
    tabs.filter((tab) => chosen.has(tab.id)).map((tab) => [String(tab.id), originOf(tab.url)])
  );
  originsList.replaceChildren(
    ...origins.map((origin) => {
      const item = document.createElement("li");
      item.textContent = origin;
      return item;
    })
  );
  allowButton.disabled = origins.length === 0;
}

async function load() {
  const state = await ask({ action: BROWSER_MESSAGES.STATE, request_id: requestId });
  const request = state?.value?.request;
  if (!request) {
    errorText.textContent = "This request expired. Ask again from the Onyx chat.";
    allowButton.disabled = true;
    return;
  }
  document.getElementById("who").textContent = `${request.domain} · ${request.account}`;
  document.getElementById("chat-title").textContent = request.chat_title || "Untitled chat";

  const [active] = await chrome.tabs.query({ active: true, lastFocusedWindow: true, windowType: "normal" });
  const tabs = (await chrome.tabs.query({ windowType: "normal" })).filter((tab) => originOf(tab.url ?? ""));
  tabsBox.replaceChildren(
    ...tabs.map((tab) => {
      const row = document.createElement("label");
      row.className = "tab";
      const box = document.createElement("input");
      box.type = "checkbox";
      box.value = String(tab.id);
      box.checked = active ? tab.id === active.id : tab === tabs[0];
      box.addEventListener("change", () => renderOrigins(tabs));
      const text = document.createElement("span");
      const title = document.createElement("span");
      title.className = "tab-title";
      title.textContent = tab.title || tab.url;
      const url = document.createElement("span");
      url.className = "tab-url";
      url.textContent = tab.url;
      text.append(title, url);
      row.append(box, text);
      return row;
    })
  );
  if (tabs.length === 0) tabsBox.textContent = "Open the page you want to share, then ask again.";
  renderOrigins(tabs);
}

// While a decision is on its way, neither button nor the tab list acts.
function setDeciding(deciding) {
  document.body.toggleAttribute("inert", deciding);
  denyButton.disabled = deciding;
  if (deciding) allowButton.disabled = true;
}

allowButton.addEventListener("click", async () => {
  setDeciding(true);
  let answer;
  try {
    answer = await ask({
      action: BROWSER_MESSAGES.APPROVE,
      request_id: requestId,
      tab_ids: checkedTabIds(),
      minutes: Number(document.getElementById("duration").value),
      tab_origins: shownTabOrigins,
    });
  } catch (error) {
    answer = { ok: false, error: `Chrome did not answer: ${error?.message ?? error}` };
  }
  if (answer?.ok) {
    window.close();
    return;
  }
  setDeciding(false);
  // Show the tabs and the request as they are now; a request that Chrome
  // took meanwhile shows as expired.
  await load();
  errorText.textContent = answer?.error ?? "Could not share the tabs.";
});

denyButton.addEventListener("click", async () => {
  setDeciding(true);
  await ask({ action: BROWSER_MESSAGES.DENY, request_id: requestId }).catch(() => {});
  window.close();
});

void load();
