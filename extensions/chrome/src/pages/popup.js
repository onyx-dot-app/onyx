import {
  getUseOnyxAsDefaultNewTab,
  setUseOnyxAsDefaultNewTab,
  isNewTabOverrideManaged,
} from "../utils/storage.js";
import { BROWSER_MESSAGES } from "../utils/constants.js";

document.addEventListener("DOMContentLoaded", async function () {
  const defaultNewTabToggle = document.getElementById("defaultNewTabToggle");
  const openSidePanelButton = document.getElementById("openSidePanel");
  const openOptionsButton = document.getElementById("openOptions");
  const newTabManagedNotice = document.getElementById("newTabManagedNotice");

  async function loadSetting() {
    const [value, managed] = await Promise.all([
      getUseOnyxAsDefaultNewTab(),
      isNewTabOverrideManaged(),
    ]);
    if (defaultNewTabToggle) {
      defaultNewTabToggle.checked = !!value;
      defaultNewTabToggle.disabled = managed;
    }
    if (newTabManagedNotice) {
      newTabManagedNotice.style.display = managed ? "block" : "none";
    }
  }

  async function toggleSetting() {
    const updated = await setUseOnyxAsDefaultNewTab(
      defaultNewTabToggle.checked
    );
    if (!updated) await loadSetting();
  }

  async function openSidePanel() {
    try {
      const [tab] = await chrome.tabs.query({
        active: true,
        currentWindow: true,
      });
      if (tab && chrome.sidePanel) {
        await chrome.sidePanel.open({ tabId: tab.id });
        window.close();
      }
    } catch (error) {
      console.error("Error opening side panel:", error);
    }
  }

  function openOptions() {
    chrome.runtime.openOptionsPage();
    window.close();
  }

  const STATE_LABELS = {
    connected: "Connected",
    offline: "Offline",
    signed_out: "Sign in to Onyx",
    disabled: "Turned off",
  };

  async function loadBrowserControl() {
    const answer = await chrome.runtime.sendMessage({
      action: BROWSER_MESSAGES.STATE,
    });
    const status = answer?.value?.status ?? { state: "offline" };
    const grant = answer?.value?.grant;
    document.getElementById("browserState").textContent =
      STATE_LABELS[status.state] ?? "Offline";
    const grantRow = document.getElementById("browserGrant");
    grantRow.hidden = !grant;
    if (grant) {
      const count = grant.tabs.length;
      document.getElementById("browserGrantText").textContent =
        `Onyx is using ${count} tab${count === 1 ? "" : "s"} for "${grant.chat_title || "a chat"}".`;
    }
  }

  document.getElementById("browserStop").addEventListener("click", async () => {
    await chrome.runtime.sendMessage({ action: BROWSER_MESSAGES.STOP });
    await loadBrowserControl();
  });

  await loadSetting();
  await loadBrowserControl();

  if (defaultNewTabToggle) {
    defaultNewTabToggle.addEventListener("change", toggleSetting);
  }

  if (openSidePanelButton) {
    openSidePanelButton.addEventListener("click", openSidePanel);
  }

  if (openOptionsButton) {
    openOptionsButton.addEventListener("click", openOptions);
  }
});
