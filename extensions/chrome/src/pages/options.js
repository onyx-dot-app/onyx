import { CHROME_SPECIFIC_STORAGE_KEYS } from "../utils/constants.js";
import {
  getOnyxDomain,
  getUseOnyxAsDefaultNewTab,
  getManagedSettings,
  normalizeOnyxDomain,
} from "../utils/storage.js";

document.addEventListener("DOMContentLoaded", function () {
  const domainInput = document.getElementById("onyxDomain");
  const useOnyxAsDefaultToggle = document.getElementById("useOnyxAsDefault");
  const domainManagedNotice = document.getElementById("domainManagedNotice");
  const newTabManagedNotice = document.getElementById("newTabManagedNotice");
  const statusContainer = document.getElementById("statusContainer");
  const statusElement = document.getElementById("status");
  const newTabButton = document.getElementById("newTab");
  const themeToggle = document.getElementById("themeToggle");
  const themeIcon = document.getElementById("themeIcon");

  let currentTheme = "dark";

  function updateThemeIcon(theme) {
    if (!themeIcon) return;

    if (theme === "light") {
      themeIcon.innerHTML = `
        <circle cx="12" cy="12" r="4"></circle>
        <path d="M12 2v2m0 16v2M4.93 4.93l1.41 1.41m11.32 11.32l1.41 1.41M2 12h2m16 0h2M4.93 19.07l1.41-1.41M17.66 6.34l1.41-1.41"></path>
      `;
    } else {
      themeIcon.innerHTML = `
        <path d="M21 12.79A9 9 0 1 1 11.21 3 7 7 0 0 0 21 12.79z"></path>
      `;
    }
  }

  let domainManaged = false;
  let newTabManaged = false;

  async function loadStoredValues() {
    const managed = await getManagedSettings();
    domainManaged =
      typeof managed[CHROME_SPECIFIC_STORAGE_KEYS.ONYX_DOMAIN] === "string";
    newTabManaged =
      typeof managed[
        CHROME_SPECIFIC_STORAGE_KEYS.USE_ONYX_AS_DEFAULT_NEW_TAB
      ] === "boolean";

    const [domain, useOnyxAsDefault, themeResult] = await Promise.all([
      getOnyxDomain(),
      getUseOnyxAsDefaultNewTab(),
      chrome.storage.local.get({
        [CHROME_SPECIFIC_STORAGE_KEYS.THEME]: "dark",
      }),
    ]);

    if (domainInput) {
      domainInput.value = domain;
      domainInput.disabled = domainManaged;
    }
    if (domainManagedNotice) {
      domainManagedNotice.style.display = domainManaged ? "block" : "none";
    }
    if (useOnyxAsDefaultToggle) {
      useOnyxAsDefaultToggle.checked = !!useOnyxAsDefault;
      useOnyxAsDefaultToggle.disabled = newTabManaged;
    }
    if (newTabManagedNotice) {
      newTabManagedNotice.style.display = newTabManaged ? "block" : "none";
    }

    currentTheme = themeResult[CHROME_SPECIFIC_STORAGE_KEYS.THEME] || "dark";
    updateThemeIcon(currentTheme);

    document.body.className = currentTheme === "light" ? "light-theme" : "";
  }

  function saveSettings() {
    const useOnyxAsDefault = useOnyxAsDefaultToggle
      ? useOnyxAsDefaultToggle.checked
      : false;

    const values = { [CHROME_SPECIFIC_STORAGE_KEYS.THEME]: currentTheme };
    if (!domainManaged) {
      values[CHROME_SPECIFIC_STORAGE_KEYS.ONYX_DOMAIN] = normalizeOnyxDomain(
        domainInput.value
      );
    }
    if (!newTabManaged) {
      values[CHROME_SPECIFIC_STORAGE_KEYS.USE_ONYX_AS_DEFAULT_NEW_TAB] =
        useOnyxAsDefault;
    }

    chrome.storage.local.set(values, () => {
      showStatusMessage(
        useOnyxAsDefault
          ? "Settings updated. Open a new tab to test it out. Click on the extension icon to bring up Onyx from any page."
          : "Settings updated."
      );
    });
  }

  function showStatusMessage(message) {
    if (statusElement) {
      const useOnyxAsDefault = useOnyxAsDefaultToggle
        ? useOnyxAsDefaultToggle.checked
        : false;

      statusElement.textContent =
        message ||
        (useOnyxAsDefault
          ? "Settings updated. Open a new tab to test it out. Click on the extension icon to bring up Onyx from any page."
          : "Settings updated.");

      if (newTabButton) {
        newTabButton.style.display = useOnyxAsDefault ? "block" : "none";
      }
    }

    if (statusContainer) {
      statusContainer.classList.add("show");
    }

    setTimeout(hideStatusMessage, 5000);
  }

  function hideStatusMessage() {
    if (statusContainer) {
      statusContainer.classList.remove("show");
    }
  }

  function toggleTheme() {
    currentTheme = currentTheme === "light" ? "dark" : "light";
    updateThemeIcon(currentTheme);

    document.body.className = currentTheme === "light" ? "light-theme" : "";

    chrome.storage.local.set({
      [CHROME_SPECIFIC_STORAGE_KEYS.THEME]: currentTheme,
    });
  }

  function openNewTab() {
    chrome.tabs.create({});
  }

  if (domainInput) {
    domainInput.addEventListener("input", () => {
      clearTimeout(domainInput.saveTimeout);
      domainInput.saveTimeout = setTimeout(saveSettings, 1000);
    });
    domainInput.addEventListener("blur", () => {
      domainInput.value = normalizeOnyxDomain(domainInput.value);
    });
  }

  chrome.storage.onChanged.addListener((changes, namespace) => {
    if (namespace === "managed") {
      loadStoredValues();
    }
  });

  if (useOnyxAsDefaultToggle) {
    useOnyxAsDefaultToggle.addEventListener("change", saveSettings);
  }

  if (themeToggle) {
    themeToggle.addEventListener("click", toggleTheme);
  }

  if (newTabButton) {
    newTabButton.addEventListener("click", openNewTab);
  }

  loadStoredValues();
});
