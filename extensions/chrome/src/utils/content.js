let sidePanel = null;

function createSidePanel() {
  sidePanel = document.createElement("div");
  sidePanel.id = "onyx-side-panel";
  sidePanel.style.cssText = `
    position: fixed;
    top: 0;
    right: -400px;
    width: 400px;
    height: 100%;
    background-color: white;
    box-shadow: -2px 0 5px rgba(0,0,0,0.2);
    transition: right 0.3s ease-in-out;
    z-index: 9999;
  `;

  const iframe = document.createElement("iframe");
  iframe.style.cssText = `
    width: 100%;
    height: 100%;
    border: none;
  `;

  chrome.runtime.sendMessage(
    { action: ACTIONS.GET_CURRENT_ONYX_DOMAIN },
    function (response) {
      iframe.src = response[CHROME_SPECIFIC_STORAGE_KEYS.ONYX_DOMAIN];
    },
  );

  sidePanel.appendChild(iframe);
  document.body.appendChild(sidePanel);
}
