(function () {
  const OPEN_SIDE_PANEL_WITH_INPUT = "openSidePanelWithInput";

  let selectionIcon = null;
  let currentSelectedText = "";

  function createSelectionIcon() {
    if (selectionIcon) return;

    selectionIcon = document.createElement("div");
    selectionIcon.id = "onyx-selection-icon";

    const img = document.createElement("img");
    img.src = chrome.runtime.getURL("public/icon32.png");
    img.alt = "Search with Onyx";

    selectionIcon.appendChild(img);
    document.body.appendChild(selectionIcon);

    selectionIcon.addEventListener("mousedown", handleIconClick);
  }

  function showIcon(text) {
    if (!selectionIcon) {
      createSelectionIcon();
    }

    currentSelectedText = text;

    const selection = window.getSelection();
    if (!selection.rangeCount) return;

    const range = selection.getRangeAt(0);
    const rect = range.getBoundingClientRect();

    const iconSize = 32;
    const offset = 4;

    let posX = rect.right + offset;
    let posY = rect.bottom + offset;

    if (posX + iconSize > window.innerWidth) {
      posX = rect.left - iconSize - offset;
    }
    if (posY + iconSize > window.innerHeight) {
      posY = rect.top - iconSize - offset;
    }

    posX = Math.max(
      offset,
      Math.min(posX, window.innerWidth - iconSize - offset),
    );
    posY = Math.max(
      offset,
      Math.min(posY, window.innerHeight - iconSize - offset),
    );

    selectionIcon.style.left = `${posX}px`;
    selectionIcon.style.top = `${posY}px`;
    selectionIcon.classList.add("visible");
  }

  function hideIcon() {
    if (selectionIcon) {
      selectionIcon.classList.remove("visible");
    }
    currentSelectedText = "";
  }

  function handleIconClick(e) {
    e.preventDefault();
    e.stopPropagation();

    const textToSend = currentSelectedText;

    if (textToSend) {
      chrome.runtime.sendMessage(
        {
          action: OPEN_SIDE_PANEL_WITH_INPUT,
          selectedText: textToSend,
          pageUrl: window.location.href,
        },
        (response) => {
          if (chrome.runtime.lastError) {
            console.error(
              "[Onyx] Error sending message:",
              chrome.runtime.lastError.message,
            );
          } else {
          }
        },
      );
    }

    hideIcon();
  }

  document.addEventListener("mouseup", (e) => {
    if (
      e.target.id === "onyx-selection-icon" ||
      e.target.closest("#onyx-selection-icon")
    ) {
      return;
    }

    setTimeout(() => {
      const selection = window.getSelection();
      const selectedText = selection.toString().trim();

      if (selectedText && selectedText.length > 0) {
        showIcon(selectedText);
      } else {
        hideIcon();
      }
    }, 10);
  });

  document.addEventListener("mousedown", (e) => {
    if (
      e.target.id !== "onyx-selection-icon" &&
      !e.target.closest("#onyx-selection-icon")
    ) {
      const selection = window.getSelection();
      const selectedText = selection.toString().trim();
      if (!selectedText) {
        hideIcon();
      }
    }
  });

  document.addEventListener(
    "scroll",
    () => {
      hideIcon();
    },
    true,
  );

  document.addEventListener("selectionchange", () => {
    const selection = window.getSelection();
    const selectedText = selection.toString().trim();
    if (!selectedText) {
      hideIcon();
    }
  });

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", createSelectionIcon);
  } else {
    createSelectionIcon();
  }
})();
