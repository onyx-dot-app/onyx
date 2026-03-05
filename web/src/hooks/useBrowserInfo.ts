"use client";

import { useState } from "react";

export interface BrowserInfo {
  isSafari: boolean;
  isFirefox: boolean;
  isChrome: boolean;
  isChromium: boolean;
  isEdge: boolean;
  isOpera: boolean;
  isIOS: boolean;
  isMac: boolean;
  isWindows: boolean;
}

function detectBrowserInfo(): BrowserInfo {
  if (typeof window === "undefined") {
    return {
      isSafari: false,
      isFirefox: false,
      isChrome: false,
      isChromium: false,
      isEdge: false,
      isOpera: false,
      isIOS: false,
      isMac: false,
      isWindows: false,
    };
  }

  const userAgent = window.navigator.userAgent;
  const isEdge = /Edg/i.test(userAgent);
  const isOpera = /OPR|Opera/i.test(userAgent);
  const isFirefox = /Firefox|FxiOS/i.test(userAgent);
  const isChrome = /Chrome|CriOS/i.test(userAgent) && !isEdge && !isOpera;
  const isChromium = /Chromium/i.test(userAgent) || isChrome;
  const isSafari =
    /Safari/i.test(userAgent) &&
    !isChromium &&
    !isEdge &&
    !isOpera &&
    !isFirefox;
  const isIOS = /iPhone|iPad|iPod/i.test(userAgent);
  const isMac = /Macintosh|Mac OS X/i.test(userAgent);
  const isWindows = /Win/i.test(userAgent);

  return {
    isSafari,
    isFirefox,
    isChrome,
    isChromium,
    isEdge,
    isOpera,
    isIOS,
    isMac,
    isWindows,
  };
}

export default function useBrowserInfo(): BrowserInfo {
  const [browserInfo] = useState<BrowserInfo>(detectBrowserInfo);
  return browserInfo;
}
