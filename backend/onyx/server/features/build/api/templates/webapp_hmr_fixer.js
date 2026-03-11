(function () {
  var B = "__WEBAPP_BASE__";

  function h(u) {
    if (!u) return false;
    try {
      var x = new URL(String(u), window.location.href);
      return (
        x.pathname.indexOf("/_next/webpack-hmr") === 0 ||
        x.pathname.indexOf("/_next/hmr") === 0
      );
    } catch (e) {}
    if (typeof u === "string") {
      return (
        u.indexOf("/_next/webpack-hmr") === 0 || u.indexOf("/_next/hmr") === 0
      );
    }
    return false;
  }

  function r(u) {
    if (!u) return u;
    try {
      var x = new URL(String(u), window.location.href);
      if (x.pathname.indexOf("/_next/") === 0) {
        return B + x.pathname + x.search + x.hash;
      }
    } catch (e) {}
    if (typeof u === "string" && u.indexOf("/_next/") === 0) {
      return B + u;
    }
    return u;
  }

  function e(t) {
    return typeof Event === "function" ? new Event(t) : { type: t };
  }

  function H(u) {
    this.url = String(u);
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
    var s = this;
    setTimeout(function () {
      s._d("open", e("open"));
    }, 0);
  }

  H.CONNECTING = 0;
  H.OPEN = 1;
  H.CLOSING = 2;
  H.CLOSED = 3;

  H.prototype.addEventListener = function (t, c) {
    (this._l[t] || (this._l[t] = [])).push(c);
  };

  H.prototype.removeEventListener = function (t, c) {
    var a = this._l[t] || [];
    this._l[t] = a.filter(function (f) {
      return f !== c;
    });
  };

  H.prototype._d = function (t, v) {
    var a = this._l[t] || [];
    for (var i = 0; i < a.length; i++) {
      a[i].call(this, v);
    }
    var n = this["on" + t];
    if (typeof n === "function") {
      n.call(this, v);
    }
  };

  H.prototype.send = function () {};

  H.prototype.close = function (c, reason) {
    if (this.readyState >= 2) return;
    this.readyState = 3;
    var v = e("close");
    v.code = c === undefined ? 1000 : c;
    v.reason = reason || "";
    v.wasClean = true;
    this._d("close", v);
  };

  if (window.WebSocket) {
    var O = window.WebSocket;
    window.WebSocket = function (u, p) {
      if (h(u)) return new H(r(u));
      return p === undefined ? new O(u) : new O(u, p);
    };
    window.WebSocket.prototype = O.prototype;
    Object.setPrototypeOf(window.WebSocket, O);
    ["CONNECTING", "OPEN", "CLOSING", "CLOSED"].forEach(function (k) {
      window.WebSocket[k] = O[k];
    });
  }
})();
