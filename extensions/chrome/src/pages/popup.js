import {
  getUseOnyxAsDefaultNewTab,
  setUseOnyxAsDefaultNewTab,
  isNewTabOverrideManaged,
} from "../utils/storage.js";

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

  await loadSetting();

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
