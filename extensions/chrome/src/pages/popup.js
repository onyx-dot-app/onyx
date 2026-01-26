import { CHROME_SPECIFIC_STORAGE_KEYS } from "../utils/constants.js";

document.addEventListener("DOMContentLoaded", async function () {
  const defaultNewTabToggle = document.getElementById("defaultNewTabToggle");
  const openSidePanelButton = document.getElementById("openSidePanel");
  const openOptionsButton = document.getElementById("openOptions");

  async function loadSetting() {
    const result = await chrome.storage.local.get({
      [CHROME_SPECIFIC_STORAGE_KEYS.USE_ONYX_AS_DEFAULT_NEW_TAB]: false,
    });
    if (defaultNewTabToggle) {
      defaultNewTabToggle.checked =
        result[CHROME_SPECIFIC_STORAGE_KEYS.USE_ONYX_AS_DEFAULT_NEW_TAB];
    }
  }

  async function toggleSetting() {
    const currentValue = defaultNewTabToggle.checked;
    await chrome.storage.local.set({
      [CHROME_SPECIFIC_STORAGE_KEYS.USE_ONYX_AS_DEFAULT_NEW_TAB]: currentValue,
    });
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
