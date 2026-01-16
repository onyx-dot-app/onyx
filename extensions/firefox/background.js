import {
  DEFAULT_ONYX_DOMAIN,
  STORAGE_KEYS,
  ACTIONS,
  SIDEBAR_PATH,
} from "./src/utils/constants.js";

// Open welcome page on first install
browser.runtime.onInstalled.addListener((details) => {
  if (details.reason === "install") {
    browser.storage.local
      .get({ [STORAGE_KEYS.ONBOARDING_COMPLETE]: false })
      .then((result) => {
        if (!result[STORAGE_KEYS.ONBOARDING_COMPLETE]) {
          browser.tabs.create({ url: "src/pages/welcome.html" });
        }
      });
  }
});

async function openSidebar() {
  try {
    await browser.sidebarAction.open();
  } catch (error) {
    console.error("Error opening sidebar:", error);
  }
}

async function closeSidebar() {
  try {
    await browser.sidebarAction.close();
  } catch (error) {
    console.error("Error closing sidebar:", error);
  }
}

async function toggleSidebar() {
  try {
    const isOpen = await browser.sidebarAction.isOpen({});
    if (isOpen) {
      await browser.sidebarAction.close();
    } else {
      await browser.sidebarAction.open();
    }
  } catch (error) {
    console.error("Error toggling sidebar:", error);
  }
}

async function sendToOnyx(info, tab) {
  const selectedText = encodeURIComponent(info.selectionText);

  try {
    const result = await browser.storage.local.get({
      [STORAGE_KEYS.ONYX_DOMAIN]: DEFAULT_ONYX_DOMAIN,
    });
    const url = `${
      result[STORAGE_KEYS.ONYX_DOMAIN]
    }${SIDEBAR_PATH}?user-prompt=${selectedText}`;

    await openSidebar();
    browser.runtime.sendMessage({
      action: ACTIONS.OPEN_SIDEBAR_WITH_INPUT,
      url: url,
      pageUrl: tab.url,
    });
  } catch (error) {
    console.error("Error sending to Onyx:", error);
  }
}

async function toggleNewTabOverride() {
  try {
    const result = await browser.storage.local.get(
      STORAGE_KEYS.USE_ONYX_AS_DEFAULT_NEW_TAB,
    );
    const newValue = !result[STORAGE_KEYS.USE_ONYX_AS_DEFAULT_NEW_TAB];
    await browser.storage.local.set({
      [STORAGE_KEYS.USE_ONYX_AS_DEFAULT_NEW_TAB]: newValue,
    });

    browser.notifications.create({
      type: "basic",
      iconUrl: "public/icon48.png",
      title: "Onyx New Tab",
      message: `New Tab Override ${newValue ? "enabled" : "disabled"}`,
    });

    // Send a message to inform all tabs about the change
    const tabs = await browser.tabs.query({});
    tabs.forEach((tab) => {
      browser.tabs
        .sendMessage(tab.id, {
          action: "newTabOverrideToggled",
          value: newValue,
        })
        .catch(() => {
          // Ignore errors for tabs that can't receive messages
        });
    });
  } catch (error) {
    console.error("Error toggling new tab override:", error);
  }
}

// Handle browser action click (when no popup is defined)
browser.action.onClicked.addListener((tab) => {
  openSidebar();
});

browser.commands.onCommand.addListener(async (command) => {
  if (command === ACTIONS.SEND_TO_ONYX) {
    try {
      const [tab] = await browser.tabs.query({
        active: true,
        lastFocusedWindow: true,
      });
      if (tab) {
        const response = await browser.tabs.sendMessage(tab.id, {
          action: ACTIONS.GET_SELECTED_TEXT,
        });
        const selectedText = response?.selectedText || "";
        sendToOnyx({ selectionText: selectedText }, tab);
      }
    } catch (error) {
      console.error("Error sending to Onyx:", error);
    }
  } else if (
    command === ACTIONS.TOGGLE_NEW_TAB_OVERRIDE ||
    command === "toggleNewTabOverride"
  ) {
    toggleNewTabOverride();
  } else if (command === ACTIONS.CLOSE_SIDEBAR) {
    await closeSidebar();
  } else if (command === ACTIONS.OPEN_SIDEBAR || command === "openSidebar") {
    await toggleSidebar();
  } else {
    console.log("Unhandled command:", command);
  }
});

browser.runtime.onMessage.addListener((request, sender, sendResponse) => {
  if (request.action === ACTIONS.GET_CURRENT_ONYX_DOMAIN) {
    browser.storage.local
      .get({
        [STORAGE_KEYS.ONYX_DOMAIN]: DEFAULT_ONYX_DOMAIN,
      })
      .then((result) => {
        sendResponse({
          [STORAGE_KEYS.ONYX_DOMAIN]: result[STORAGE_KEYS.ONYX_DOMAIN],
        });
      });
    return true;
  }

  if (request.action === ACTIONS.CLOSE_SIDEBAR) {
    closeSidebar();
    browser.storage.local
      .get({
        [STORAGE_KEYS.ONYX_DOMAIN]: DEFAULT_ONYX_DOMAIN,
      })
      .then((result) => {
        browser.tabs.create({
          url: `${result[STORAGE_KEYS.ONYX_DOMAIN]}/auth/login`,
          active: true,
        });
      });
    return true;
  }

  if (request.action === ACTIONS.OPEN_SIDEBAR_WITH_INPUT) {
    const { selectedText, pageUrl } = request;

    browser.storage.local
      .get({
        [STORAGE_KEYS.ONYX_DOMAIN]: DEFAULT_ONYX_DOMAIN,
      })
      .then((result) => {
        const encodedText = encodeURIComponent(selectedText);
        const onyxDomain = result[STORAGE_KEYS.ONYX_DOMAIN];
        const url = `${onyxDomain}${SIDEBAR_PATH}?user-prompt=${encodedText}`;

        browser.storage.session.set({
          pendingInput: {
            url: url,
            pageUrl: pageUrl,
            timestamp: Date.now(),
          },
        });

        openSidebar()
          .then(() => {
            browser.runtime.sendMessage({
              action: ACTIONS.OPEN_ONYX_WITH_INPUT,
              url: url,
              pageUrl: pageUrl,
            });
          })
          .catch((error) => {
            console.error("[Onyx] Error opening sidebar with text:", error);
          });
      });
    return true;
  }

  if (request.action === ACTIONS.OPEN_SIDEBAR) {
    openSidebar();
    return true;
  }

  return false;
});

browser.storage.onChanged.addListener((changes, namespace) => {
  if (
    namespace === "local" &&
    changes[STORAGE_KEYS.USE_ONYX_AS_DEFAULT_NEW_TAB]
  ) {
    const newValue = changes[STORAGE_KEYS.USE_ONYX_AS_DEFAULT_NEW_TAB].newValue;

    if (newValue === false) {
      browser.runtime.openOptionsPage();
    }
  }
});

// Omnibox support
browser.omnibox.setDefaultSuggestion({
  description: 'Search Onyx for "%s"',
});

browser.omnibox.onInputEntered.addListener(async (text) => {
  try {
    const result = await browser.storage.local.get({
      [STORAGE_KEYS.ONYX_DOMAIN]: DEFAULT_ONYX_DOMAIN,
    });

    const domain = result[STORAGE_KEYS.ONYX_DOMAIN];
    const searchUrl = `${domain}/chat?user-prompt=${encodeURIComponent(text)}`;

    browser.tabs.update({ url: searchUrl });
  } catch (error) {
    console.error("Error handling omnibox search:", error);
  }
});

browser.omnibox.onInputChanged.addListener((text, suggest) => {
  if (text.trim()) {
    suggest([
      {
        content: text,
        description: `Search Onyx for "${text}"`,
      },
    ]);
  }
});
