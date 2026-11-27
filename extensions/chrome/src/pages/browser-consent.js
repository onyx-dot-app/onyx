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

function renderOrigins(tabs) {
  const chosen = new Set(checkedTabIds());
  const origins = [...new Set(tabs.filter((tab) => chosen.has(tab.id)).map((tab) => originOf(tab.url)))];
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

allowButton.addEventListener("click", async () => {
  allowButton.disabled = true;
  const answer = await ask({
    action: BROWSER_MESSAGES.APPROVE,
    request_id: requestId,
    tab_ids: checkedTabIds(),
    minutes: Number(document.getElementById("duration").value),
  });
  if (answer?.ok) window.close();
  else {
    errorText.textContent = answer?.error ?? "Could not share the tabs.";
    allowButton.disabled = false;
  }
});

denyButton.addEventListener("click", async () => {
  await ask({ action: BROWSER_MESSAGES.DENY, request_id: requestId });
  window.close();
});

void load();
