import { STORAGE_KEYS } from "../utils/constants.js";

document.addEventListener("DOMContentLoaded", async function () {
  const defaultNewTabToggle = document.getElementById("defaultNewTabToggle");
  const openSidebarButton = document.getElementById("openSidebar");
  const openOptionsButton = document.getElementById("openOptions");

  async function loadSetting() {
    const result = await browser.storage.local.get({
      [STORAGE_KEYS.USE_ONYX_AS_DEFAULT_NEW_TAB]: false,
    });
    if (defaultNewTabToggle) {
      defaultNewTabToggle.checked =
        result[STORAGE_KEYS.USE_ONYX_AS_DEFAULT_NEW_TAB];
    }
  }

  async function toggleSetting() {
    const currentValue = defaultNewTabToggle.checked;
    await browser.storage.local.set({
      [STORAGE_KEYS.USE_ONYX_AS_DEFAULT_NEW_TAB]: currentValue,
    });
  }

  async function openSidebar() {
    try {
      await browser.sidebarAction.open();
      window.close();
    } catch (error) {
      console.error("Error opening sidebar:", error);
    }
  }

  function openOptions() {
    browser.runtime.openOptionsPage();
    window.close();
  }

  await loadSetting();

  if (defaultNewTabToggle) {
    defaultNewTabToggle.addEventListener("change", toggleSetting);
  }

  if (openSidebarButton) {
    openSidebarButton.addEventListener("click", openSidebar);
  }

  if (openOptionsButton) {
    openOptionsButton.addEventListener("click", openOptions);
  }
});
