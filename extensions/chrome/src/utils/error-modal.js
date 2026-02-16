import {
  CHROME_SPECIFIC_STORAGE_KEYS,
  DEFAULT_ONYX_DOMAIN,
  ACTIONS,
} from "./constants.js";

const errorModalHTML = `
  <div id="error-modal">
    <div class="modal-backdrop"></div>
    <div class="modal-content">
      <div class="modal-header">
        <div class="modal-icon">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
            <circle cx="12" cy="12" r="10"></circle>
            <line x1="12" y1="8" x2="12" y2="12"></line>
            <line x1="12" y1="16" x2="12.01" y2="16"></line>
          </svg>
        </div>
        <h2>Configuration Error</h2>
      </div>
      <div class="modal-body">
        <p class="modal-description">The Onyx configuration needs to be updated. Please check your settings or contact your Onyx administrator.</p>
        <div class="url-display">
          <span class="url-label">Attempted to load:</span>
          <span id="attempted-url" class="url-value"></span>
        </div>
      </div>
      <div class="modal-footer">
        <div class="button-container">
          <button id="open-options" class="button primary">Open Extension Options</button>
          <button id="disable-override" class="button secondary">Disable New Tab Override</button>
        </div>
      </div>
    </div>
  </div>
`;

const style = document.createElement("style");
style.textContent = `
  :root {
    --background-900: #0a0a0a;
    --background-800: #1a1a1a;
    --text-light-05: rgba(255, 255, 255, 0.95);
    --text-light-03: rgba(255, 255, 255, 0.6);
    --white-10: rgba(255, 255, 255, 0.1);
    --white-15: rgba(255, 255, 255, 0.15);
    --white-20: rgba(255, 255, 255, 0.2);
    --white-30: rgba(255, 255, 255, 0.3);
  }

  #error-modal {
    position: fixed;
    top: 0;
    left: 0;
    width: 100%;
    height: 100%;
    display: none;
    align-items: center;
    justify-content: center;
    z-index: 2000;
    font-family: var(--font-hanken-grotesk), 'Hanken Grotesk', sans-serif;
  }

  #error-modal .modal-backdrop {
    position: absolute;
    top: 0;
    left: 0;
    width: 100%;
    height: 100%;
    background: rgba(0, 0, 0, 0.7);
    backdrop-filter: blur(8px);
  }

  #error-modal .modal-content {
    position: relative;
    background: linear-gradient(to bottom, rgba(10, 10, 10, 0.95), rgba(26, 26, 26, 0.95));
    backdrop-filter: blur(24px);
    border-radius: 16px;
    border: 1px solid var(--white-10);
    max-width: 95%;
    width: 500px;
    box-shadow: 0 8px 32px rgba(0, 0, 0, 0.4);
    overflow: hidden;
  }

  #error-modal .modal-header {
    padding: 24px;
    border-bottom: 1px solid var(--white-10);
    display: flex;
    align-items: center;
    gap: 12px;
  }

  #error-modal .modal-icon {
    width: 40px;
    height: 40px;
    border-radius: 12px;
    background: rgba(255, 87, 87, 0.15);
    display: flex;
    align-items: center;
    justify-content: center;
    flex-shrink: 0;
  }

  #error-modal .modal-icon svg {
    width: 24px;
    height: 24px;
    stroke: #ff5757;
  }

  #error-modal .modal-icon.auth-icon {
    background: rgba(66, 133, 244, 0.15);
  }

  #error-modal .modal-icon.auth-icon svg {
    stroke: #4285f4;
  }

  #error-modal h2 {
    margin: 0;
    color: var(--text-light-05);
    font-size: 20px;
    font-weight: 600;
  }

  #error-modal .modal-body {
    padding: 24px;
  }

  #error-modal .modal-description {
    color: var(--text-light-05);
    margin: 0 0 20px 0;
    font-size: 14px;
    line-height: 1.6;
    font-weight: 400;
  }

  #error-modal .url-display {
    background: rgba(255, 255, 255, 0.05);
    border-radius: 8px;
    padding: 12px;
    border: 1px solid var(--white-10);
  }

  #error-modal .url-label {
    display: block;
    font-size: 12px;
    color: var(--text-light-03);
    margin-bottom: 6px;
    font-weight: 500;
    text-transform: uppercase;
    letter-spacing: 0.05em;
  }

  #error-modal .url-value {
    display: block;
    font-size: 13px;
    color: var(--text-light-05);
    word-break: break-all;
    font-family: monospace;
    line-height: 1.5;
  }

  #error-modal .modal-footer {
    padding: 0 24px 24px 24px;
  }

  #error-modal .button-container {
    display: flex;
    flex-direction: column;
    gap: 10px;
    margin-bottom: 16px;
  }

  #error-modal .button {
    padding: 12px 20px;
    border-radius: 8px;
    border: none;
    cursor: pointer;
    font-size: 14px;
    font-weight: 500;
    transition: all 0.2s;
    font-family: var(--font-hanken-grotesk), 'Hanken Grotesk', sans-serif;
  }

  #error-modal .button.primary {
    background: rgba(255, 255, 255, 0.15);
    color: var(--text-light-05);
    border: 1px solid var(--white-10);
  }

  #error-modal .button.primary:hover {
    background: rgba(255, 255, 255, 0.2);
    border-color: var(--white-20);
  }

  #error-modal .button.secondary {
    background: rgba(255, 255, 255, 0.05);
    color: var(--text-light-05);
    border: 1px solid var(--white-10);
  }

  #error-modal .button.secondary:hover {
    background: rgba(255, 255, 255, 0.1);
    border-color: var(--white-15);
  }

  #error-modal kbd {
    background: rgba(255, 255, 255, 0.1);
    border: 1px solid var(--white-10);
    border-radius: 4px;
    padding: 2px 6px;
    font-family: monospace;
    font-weight: 500;
    color: var(--text-light-05);
    font-size: 11px;
  }

  @media (min-width: 768px) {
    #error-modal .button-container {
      flex-direction: row;
    }

    #error-modal .button {
      flex: 1;
    }
  }
`;

const authModalHTML = `
  <div id="error-modal">
    <div class="modal-backdrop"></div>
    <div class="modal-content">
      <div class="modal-header">
        <div class="modal-icon auth-icon">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
            <rect x="3" y="11" width="18" height="11" rx="2" ry="2"></rect>
            <path d="M7 11V7a5 5 0 0 1 10 0v4"></path>
          </svg>
        </div>
        <h2>Authentication Required</h2>
      </div>
      <div class="modal-body">
        <p class="modal-description">You need to log in to access Onyx. Click the button below to authenticate.</p>
      </div>
      <div class="modal-footer">
        <div class="button-container">
          <button id="open-auth" class="button primary">Log In to Onyx</button>
        </div>
      </div>
    </div>
  </div>
`;

let errorModal, attemptedUrlSpan, openOptionsButton, disableOverrideButton;

let authModal, openAuthButton;

export function initErrorModal() {
  if (!document.getElementById("error-modal")) {
    const link = document.createElement("link");
    link.rel = "stylesheet";
    link.href = "../styles/shared.css";
    document.head.appendChild(link);

    document.body.insertAdjacentHTML("beforeend", errorModalHTML);
    document.head.appendChild(style);

    errorModal = document.getElementById("error-modal");
    authModal = document.getElementById("error-modal");
    attemptedUrlSpan = document.getElementById("attempted-url");
    openOptionsButton = document.getElementById("open-options");
    disableOverrideButton = document.getElementById("disable-override");

    openOptionsButton.addEventListener("click", (e) => {
      e.preventDefault();
      chrome.runtime.openOptionsPage();
    });

    disableOverrideButton.addEventListener("click", () => {
      chrome.storage.local.set({ useOnyxAsDefaultNewTab: false }, () => {
        chrome.tabs.update({ url: "chrome://new-tab-page" });
      });
    });
  }
}

export function showErrorModal(url) {
  if (!errorModal) {
    initErrorModal();
  }
  if (errorModal) {
    errorModal.style.display = "flex";
    errorModal.style.zIndex = "9999";
    attemptedUrlSpan.textContent = url;
    document.body.style.overflow = "hidden";
  }
}

export function hideErrorModal() {
  if (errorModal) {
    errorModal.style.display = "none";
    document.body.style.overflow = "auto";
  }
}

export function checkModalVisibility() {
  return errorModal
    ? window.getComputedStyle(errorModal).display !== "none"
    : false;
}

export function initAuthModal() {
  if (!document.getElementById("error-modal")) {
    const link = document.createElement("link");
    link.rel = "stylesheet";
    link.href = "../styles/shared.css";
    document.head.appendChild(link);

    document.body.insertAdjacentHTML("beforeend", authModalHTML);
    document.head.appendChild(style);

    authModal = document.getElementById("error-modal");
    openAuthButton = document.getElementById("open-auth");

    openAuthButton.addEventListener("click", (e) => {
      e.preventDefault();
      chrome.storage.local.get(
        { [CHROME_SPECIFIC_STORAGE_KEYS.ONYX_DOMAIN]: DEFAULT_ONYX_DOMAIN },
        (result) => {
          const onyxDomain = result[CHROME_SPECIFIC_STORAGE_KEYS.ONYX_DOMAIN];
          chrome.runtime.sendMessage(
            { action: ACTIONS.CLOSE_SIDE_PANEL },
            () => {
              if (chrome.runtime.lastError) {
                console.error(
                  "Error closing side panel:",
                  chrome.runtime.lastError,
                );
              }
              chrome.tabs.create(
                {
                  url: `${onyxDomain}/auth/login`,
                  active: true,
                },
                (_) => {
                  if (chrome.runtime.lastError) {
                    console.error(
                      "Error opening auth tab:",
                      chrome.runtime.lastError,
                    );
                  }
                },
              );
            },
          );
        },
      );
    });
  }
}

export function showAuthModal() {
  if (!authModal) {
    initAuthModal();
  }
  if (authModal) {
    authModal.style.display = "flex";
    authModal.style.zIndex = "9999";
    document.body.style.overflow = "hidden";
  }
}

export function hideAuthModal() {
  if (authModal) {
    authModal.style.display = "none";
    document.body.style.overflow = "auto";
  }
}
