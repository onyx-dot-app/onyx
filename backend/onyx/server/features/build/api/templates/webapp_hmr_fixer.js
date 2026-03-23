(function () {
  var WEBAPP_BASE = "__WEBAPP_BASE__";
  var PROXIED_NEXT_PREFIX = WEBAPP_BASE + "/_next/";
  var PROXIED_HMR_PREFIX = WEBAPP_BASE + "/_next/webpack-hmr";
  var PROXIED_ALT_HMR_PREFIX = WEBAPP_BASE + "/_next/hmr";

  function isHmrWebSocketUrl(url) {
    if (!url) return false;
    try {
      var parsedUrl = new URL(String(url), window.location.href);
      return (
        parsedUrl.pathname.indexOf("/_next/webpack-hmr") === 0 ||
        parsedUrl.pathname.indexOf("/_next/hmr") === 0 ||
        parsedUrl.pathname.indexOf(PROXIED_HMR_PREFIX) === 0 ||
        parsedUrl.pathname.indexOf(PROXIED_ALT_HMR_PREFIX) === 0
      );
    } catch (e) {}
    if (typeof url === "string") {
      return (
        url.indexOf("/_next/webpack-hmr") === 0 ||
        url.indexOf("/_next/hmr") === 0 ||
        url.indexOf(PROXIED_HMR_PREFIX) === 0 ||
        url.indexOf(PROXIED_ALT_HMR_PREFIX) === 0
      );
    }
    return false;
  }

  function rewriteNextAssetUrl(url) {
    if (!url) return url;
    try {
      var parsedUrl = new URL(String(url), window.location.href);
      if (parsedUrl.pathname.indexOf(PROXIED_NEXT_PREFIX) === 0) {
        return parsedUrl.pathname + parsedUrl.search + parsedUrl.hash;
      }
      if (parsedUrl.pathname.indexOf("/_next/") === 0) {
        return (
          WEBAPP_BASE + parsedUrl.pathname + parsedUrl.search + parsedUrl.hash
        );
      }
    } catch (e) {}
    if (typeof url === "string") {
      if (url.indexOf(PROXIED_NEXT_PREFIX) === 0) {
        return url;
      }
      if (url.indexOf("/_next/") === 0) {
        return WEBAPP_BASE + url;
      }
    }
    return url;
  }

  function createEvent(eventType) {
    return typeof Event === "function"
      ? new Event(eventType)
      : { type: eventType };
  }

  function MockHmrWebSocket(url) {
    this.url = String(url);
    this.readyState = 1;
    this.bufferedAmount = 0;
    this.extensions = "";
    this.protocol = "";
    this.binaryType = "blob";
    this.onopen = null;
    this.onmessage = null;
    this.onerror = null;
    this.onclose = null;
    this._l = {};
    var socket = this;
    setTimeout(function () {
      socket._d("open", createEvent("open"));
    }, 0);
  }

  MockHmrWebSocket.CONNECTING = 0;
  MockHmrWebSocket.OPEN = 1;
  MockHmrWebSocket.CLOSING = 2;
  MockHmrWebSocket.CLOSED = 3;

  MockHmrWebSocket.prototype.addEventListener = function (eventType, callback) {
    (this._l[eventType] || (this._l[eventType] = [])).push(callback);
  };

  MockHmrWebSocket.prototype.removeEventListener = function (
    eventType,
    callback,
  ) {
    var listeners = this._l[eventType] || [];
    this._l[eventType] = listeners.filter(function (listener) {
      return listener !== callback;
    });
  };

  MockHmrWebSocket.prototype._d = function (eventType, eventValue) {
    var listeners = this._l[eventType] || [];
    for (var i = 0; i < listeners.length; i++) {
      listeners[i].call(this, eventValue);
    }
    var handler = this["on" + eventType];
    if (typeof handler === "function") {
      handler.call(this, eventValue);
    }
  };

  MockHmrWebSocket.prototype.send = function () {};

  MockHmrWebSocket.prototype.close = function (code, reason) {
    if (this.readyState >= 2) return;
    this.readyState = 3;
    var closeEvent = createEvent("close");
    closeEvent.code = code === undefined ? 1000 : code;
    closeEvent.reason = reason || "";
    closeEvent.wasClean = true;
    this._d("close", closeEvent);
  };

  if (window.WebSocket) {
    var OriginalWebSocket = window.WebSocket;
    window.WebSocket = function (url, protocols) {
      if (isHmrWebSocketUrl(url)) {
        return new MockHmrWebSocket(rewriteNextAssetUrl(url));
      }
      return protocols === undefined
        ? new OriginalWebSocket(url)
        : new OriginalWebSocket(url, protocols);
    };
    window.WebSocket.prototype = OriginalWebSocket.prototype;
    Object.setPrototypeOf(window.WebSocket, OriginalWebSocket);
    ["CONNECTING", "OPEN", "CLOSING", "CLOSED"].forEach(function (stateKey) {
      window.WebSocket[stateKey] = OriginalWebSocket[stateKey];
    });
  }
})();
