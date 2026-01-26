import {
  DEFAULT_ONYX_DOMAIN,
  CHROME_SPECIFIC_STORAGE_KEYS,
  ACTIONS,
  SIDE_PANEL_PATH,
} from "./src/utils/constants.js";

// Track side panel state per window
const sidePanelOpenState = new Map();

// Open welcome page on first install
chrome.runtime.onInstalled.addListener((details) => {
  if (details.reason === "install") {
    chrome.storage.local.get(
      { [CHROME_SPECIFIC_STORAGE_KEYS.ONBOARDING_COMPLETE]: false },
      (result) => {
        if (!result[CHROME_SPECIFIC_STORAGE_KEYS.ONBOARDING_COMPLETE]) {
          chrome.tabs.create({ url: "src/pages/welcome.html" });
        }
      },
    );
  }
});

async function setupSidePanel() {
  if (chrome.sidePanel) {
    try {
      // Don't auto-open side panel on action click since we have a popup menu
      await chrome.sidePanel.setPanelBehavior({
        openPanelOnActionClick: false,
      });
    } catch (error) {
      console.error("Error setting up side panel:", error);
    }
  }
}

async function openSidePanel(tabId) {
  try {
    await chrome.sidePanel.open({ tabId });
  } catch (error) {
    console.error("Error opening side panel:", error);
  }
}

async function sendToOnyx(info, tab) {
  const selectedText = encodeURIComponent(info.selectionText);
  const currentUrl = encodeURIComponent(tab.url);

  try {
    const result = await chrome.storage.local.get({
      [CHROME_SPECIFIC_STORAGE_KEYS.ONYX_DOMAIN]: DEFAULT_ONYX_DOMAIN,
    });
    const url = `${
      result[CHROME_SPECIFIC_STORAGE_KEYS.ONYX_DOMAIN]
    }${SIDE_PANEL_PATH}?user-prompt=${selectedText}`;

    await openSidePanel(tab.id);
    chrome.runtime.sendMessage({
      action: ACTIONS.OPEN_SIDE_PANEL_WITH_INPUT,
      url: url,
      pageUrl: tab.url,
    });
  } catch (error) {
    console.error("Error sending to Onyx:", error);
  }
}

async function toggleNewTabOverride() {
  try {
    const result = await chrome.storage.local.get(
      CHROME_SPECIFIC_STORAGE_KEYS.USE_ONYX_AS_DEFAULT_NEW_TAB,
    );
    const newValue =
      !result[CHROME_SPECIFIC_STORAGE_KEYS.USE_ONYX_AS_DEFAULT_NEW_TAB];
    await chrome.storage.local.set({
      [CHROME_SPECIFIC_STORAGE_KEYS.USE_ONYX_AS_DEFAULT_NEW_TAB]: newValue,
    });

    chrome.notifications.create({
      type: "basic",
      iconUrl: "icon.png",
      title: "Onyx New Tab",
      message: `New Tab Override ${newValue ? "enabled" : "disabled"}`,
    });

    // Send a message to inform all tabs about the change
    chrome.tabs.query({}, (tabs) => {
      tabs.forEach((tab) => {
        chrome.tabs.sendMessage(tab.id, {
          action: "newTabOverrideToggled",
          value: newValue,
        });
      });
    });
  } catch (error) {
    console.error("Error toggling new tab override:", error);
  }
}

// Note: This listener won't fire when a popup is defined in manifest.json
// The popup will show instead. This is kept as a fallback if popup is removed.
chrome.action.onClicked.addListener((tab) => {
  openSidePanel(tab.id);
});

chrome.commands.onCommand.addListener(async (command) => {
  if (command === ACTIONS.SEND_TO_ONYX) {
    try {
      const [tab] = await chrome.tabs.query({
        active: true,
        lastFocusedWindow: true,
      });
      if (tab) {
        const response = await chrome.tabs.sendMessage(tab.id, {
          action: ACTIONS.GET_SELECTED_TEXT,
        });
        const selectedText = response?.selectedText || "";
        sendToOnyx({ selectionText: selectedText }, tab);
      }
    } catch (error) {
      console.error("Error sending to Onyx:", error);
    }
  } else if (command === ACTIONS.TOGGLE_NEW_TAB_OVERRIDE) {
    toggleNewTabOverride();
  } else if (command === ACTIONS.CLOSE_SIDE_PANEL) {
    try {
      await chrome.sidePanel.hide();
    } catch (error) {
      console.error("Error closing side panel via command:", error);
    }
  } else if (command === ACTIONS.OPEN_SIDE_PANEL) {
    chrome.tabs.query({ active: true, lastFocusedWindow: true }, (tabs) => {
      if (tabs && tabs.length > 0) {
        const tab = tabs[0];
        const windowId = tab.windowId;
        const isOpen = sidePanelOpenState.get(windowId) || false;

        if (isOpen) {
          chrome.sidePanel.setOptions({ enabled: false }, () => {
            chrome.sidePanel.setOptions({ enabled: true });
            sidePanelOpenState.set(windowId, false);
          });
        } else {
          chrome.sidePanel.open({ tabId: tab.id });
          sidePanelOpenState.set(windowId, true);
        }
      }
    });
    return;
  } else {
    console.log("Unhandled command:", command);
  }
});

chrome.runtime.onMessage.addListener((request, sender, sendResponse) => {
  if (request.action === ACTIONS.GET_CURRENT_ONYX_DOMAIN) {
    chrome.storage.local.get(
      { [CHROME_SPECIFIC_STORAGE_KEYS.ONYX_DOMAIN]: DEFAULT_ONYX_DOMAIN },
      (result) => {
        sendResponse({
          [CHROME_SPECIFIC_STORAGE_KEYS.ONYX_DOMAIN]:
            result[CHROME_SPECIFIC_STORAGE_KEYS.ONYX_DOMAIN],
        });
      },
    );
    return true;
  }
  if (request.action === ACTIONS.CLOSE_SIDE_PANEL) {
    closeSidePanel();
    chrome.storage.local.get(
      { [CHROME_SPECIFIC_STORAGE_KEYS.ONYX_DOMAIN]: DEFAULT_ONYX_DOMAIN },
      (result) => {
        chrome.tabs.create({
          url: `${result[CHROME_SPECIFIC_STORAGE_KEYS.ONYX_DOMAIN]}/auth/login`,
          active: true,
        });
      },
    );
    return true;
  }
  if (request.action === ACTIONS.OPEN_SIDE_PANEL_WITH_INPUT) {
    const { selectedText, pageUrl } = request;
    const tabId = sender.tab?.id;
    const windowId = sender.tab?.windowId;

    if (tabId && windowId) {
      chrome.storage.local.get(
        { [CHROME_SPECIFIC_STORAGE_KEYS.ONYX_DOMAIN]: DEFAULT_ONYX_DOMAIN },
        (result) => {
          const encodedText = encodeURIComponent(selectedText);
          const onyxDomain = result[CHROME_SPECIFIC_STORAGE_KEYS.ONYX_DOMAIN];
          const url = `${onyxDomain}${SIDE_PANEL_PATH}?user-prompt=${encodedText}`;

          chrome.storage.session.set({
            pendingInput: {
              url: url,
              pageUrl: pageUrl,
              timestamp: Date.now(),
            },
          });

          chrome.sidePanel
            .open({ windowId })
            .then(() => {
              chrome.runtime.sendMessage({
                action: ACTIONS.OPEN_ONYX_WITH_INPUT,
                url: url,
                pageUrl: pageUrl,
              });
            })
            .catch((error) => {
              console.error(
                "[Onyx SW] Error opening side panel with text:",
                error,
              );
            });
        },
      );
    } else {
      console.error("[Onyx SW] Missing tabId or windowId");
    }
    return true;
  }
});

chrome.storage.onChanged.addListener((changes, namespace) => {
  if (
    namespace === "local" &&
    changes[CHROME_SPECIFIC_STORAGE_KEYS.USE_ONYX_AS_DEFAULT_NEW_TAB]
  ) {
    const newValue =
      changes[CHROME_SPECIFIC_STORAGE_KEYS.USE_ONYX_AS_DEFAULT_NEW_TAB]
        .newValue;

    if (newValue === false) {
      chrome.runtime.openOptionsPage();
    }
  }
});

chrome.windows.onRemoved.addListener((windowId) => {
  sidePanelOpenState.delete(windowId);
});

chrome.omnibox.setDefaultSuggestion({
  description: 'Search Onyx for "%s"',
});

chrome.omnibox.onInputEntered.addListener(async (text) => {
  try {
    const result = await chrome.storage.local.get({
      [CHROME_SPECIFIC_STORAGE_KEYS.ONYX_DOMAIN]: DEFAULT_ONYX_DOMAIN,
    });

    const domain = result[CHROME_SPECIFIC_STORAGE_KEYS.ONYX_DOMAIN];
    const searchUrl = `${domain}/chat?user-prompt=${encodeURIComponent(text)}`;

    chrome.tabs.update({ url: searchUrl });
  } catch (error) {
    console.error("Error handling omnibox search:", error);
  }
});

chrome.omnibox.onInputChanged.addListener((text, suggest) => {
  if (text.trim()) {
    suggest([
      {
        content: text,
        description: `Search Onyx for "<match>${text}</match>"`,
      },
    ]);
  }
});

setupSidePanel();
