import { CHROME_SPECIFIC_STORAGE_KEYS } from "../utils/constants.js";
import { getManagedSettings, normalizeOnyxDomain } from "../utils/storage.js";

document.addEventListener("DOMContentLoaded", function () {
  const domainInput = document.getElementById("onyxDomain");
  const useOnyxAsDefaultToggle = document.getElementById("useOnyxAsDefault");
  const domainManagedNotice = document.getElementById("domainManagedNotice");
  const newTabManagedNotice = document.getElementById("newTabManagedNotice");
  const continueBtn = document.getElementById("continueBtn");
  const backBtn = document.getElementById("backBtn");
  const finishBtn = document.getElementById("finishBtn");
  const themeToggle = document.getElementById("themeToggle");
  const themeIcon = document.getElementById("themeIcon");

  const step1 = document.getElementById("step1");
  const step2 = document.getElementById("step2");
  const stepDots = document.querySelectorAll(".step-dot");

  let currentStep = 1;
  let currentTheme = "dark";
  let domainManaged = false;
  let newTabManaged = false;

  // Initialize theme based on system preference or stored value
  function initTheme() {
    chrome.storage.local.get(
      { [CHROME_SPECIFIC_STORAGE_KEYS.THEME]: null },
      (result) => {
        const storedTheme = result[CHROME_SPECIFIC_STORAGE_KEYS.THEME];
        if (storedTheme) {
          currentTheme = storedTheme;
        } else {
          // Check system preference
          currentTheme = window.matchMedia("(prefers-color-scheme: light)")
            .matches
            ? "light"
            : "dark";
        }
        applyTheme();
      }
    );
  }

  function applyTheme() {
    document.body.className = currentTheme === "light" ? "light-theme" : "";
    updateThemeIcon();
  }

  function updateThemeIcon() {
    if (!themeIcon) return;

    if (currentTheme === "light") {
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

  function toggleTheme() {
    currentTheme = currentTheme === "light" ? "dark" : "light";
    applyTheme();
    chrome.storage.local.set({
      [CHROME_SPECIFIC_STORAGE_KEYS.THEME]: currentTheme,
    });
  }

  function goToStep(step) {
    if (step === 1) {
      step2.classList.remove("active");
      setTimeout(() => {
        step1.classList.add("active");
      }, 50);
    } else if (step === 2) {
      step1.classList.remove("active");
      setTimeout(() => {
        step2.classList.add("active");
      }, 50);
    }

    stepDots.forEach((dot) => {
      const dotStep = parseInt(dot.dataset.step);
      if (dotStep === step) {
        dot.classList.add("active");
      } else {
        dot.classList.remove("active");
      }
    });

    currentStep = step;
  }

  // Validate domain input
  function validateDomain(domain) {
    if (!domain) return false;
    try {
      new URL(domain);
      return true;
    } catch {
      return false;
    }
  }

  function handleContinue() {
    const domain = domainInput.value.trim();

    if (domain && !validateDomain(domain)) {
      domainInput.style.borderColor = "rgba(255, 100, 100, 0.5)";
      domainInput.focus();
      return;
    }

    domainInput.style.borderColor = "";
    goToStep(2);
  }

  function handleBack() {
    goToStep(1);
  }

  function handleFinish() {
    const useOnyxAsDefault = useOnyxAsDefaultToggle.checked;

    const values = {
      [CHROME_SPECIFIC_STORAGE_KEYS.THEME]: currentTheme,
      [CHROME_SPECIFIC_STORAGE_KEYS.ONBOARDING_COMPLETE]: true,
    };
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
      // Open a new tab if they enabled the new tab feature, otherwise just close
      if (useOnyxAsDefault) {
        chrome.tabs.create({}, () => {
          window.close();
        });
      } else {
        window.close();
      }
    });
  }

  // Lock controls that are set by policy. Unmanaged controls keep whatever
  // the user has entered so far.
  async function applyManagedSettings() {
    const managed = await getManagedSettings();
    const managedDomain = managed[CHROME_SPECIFIC_STORAGE_KEYS.ONYX_DOMAIN];
    const managedNewTab =
      managed[CHROME_SPECIFIC_STORAGE_KEYS.USE_ONYX_AS_DEFAULT_NEW_TAB];
    domainManaged = typeof managedDomain === "string";
    newTabManaged = typeof managedNewTab === "boolean";

    domainInput.disabled = domainManaged;
    domainManagedNotice.style.display = domainManaged ? "block" : "none";
    if (domainManaged) {
      domainInput.value = normalizeOnyxDomain(managedDomain);
    }

    useOnyxAsDefaultToggle.disabled = newTabManaged;
    newTabManagedNotice.style.display = newTabManaged ? "block" : "none";
    if (newTabManaged) {
      useOnyxAsDefaultToggle.checked = managedNewTab;
    }
  }

  // Load any existing values (in case user returns to this page)
  async function loadStoredValues() {
    const result = await chrome.storage.local.get({
      [CHROME_SPECIFIC_STORAGE_KEYS.ONYX_DOMAIN]: "",
      [CHROME_SPECIFIC_STORAGE_KEYS.USE_ONYX_AS_DEFAULT_NEW_TAB]: true,
    });

    if (result[CHROME_SPECIFIC_STORAGE_KEYS.ONYX_DOMAIN]) {
      domainInput.value = result[CHROME_SPECIFIC_STORAGE_KEYS.ONYX_DOMAIN];
    }
    useOnyxAsDefaultToggle.checked =
      result[CHROME_SPECIFIC_STORAGE_KEYS.USE_ONYX_AS_DEFAULT_NEW_TAB];

    await applyManagedSettings();
  }

  chrome.storage.onChanged.addListener((changes, namespace) => {
    if (namespace === "managed") {
      applyManagedSettings();
    }
  });

  if (themeToggle) {
    themeToggle.addEventListener("click", toggleTheme);
  }

  if (continueBtn) {
    continueBtn.addEventListener("click", handleContinue);
  }

  if (backBtn) {
    backBtn.addEventListener("click", handleBack);
  }

  if (finishBtn) {
    finishBtn.addEventListener("click", handleFinish);
  }

  // Allow Enter key to proceed
  if (domainInput) {
    domainInput.addEventListener("keydown", (e) => {
      if (e.key === "Enter") {
        handleContinue();
      }
    });
    domainInput.addEventListener("blur", () => {
      if (domainInput.value.trim()) {
        domainInput.value = normalizeOnyxDomain(domainInput.value);
      }
    });
  }

  initTheme();
  loadStoredValues();
});
