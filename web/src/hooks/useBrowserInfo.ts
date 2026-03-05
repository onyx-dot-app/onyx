"use client";

import { useEffect, useState } from "react";

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

const DEFAULT_BROWSER_INFO: BrowserInfo = {
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

export default function useBrowserInfo(): BrowserInfo {
  const [browserInfo, setBrowserInfo] =
    useState<BrowserInfo>(DEFAULT_BROWSER_INFO);

  useEffect(() => {
    if (typeof window === "undefined") return;

    const userAgent = window.navigator.userAgent;
    const isEdge = /Edg/i.test(userAgent);
    const isOpera = /OPR|Opera/i.test(userAgent);
    const isFirefox = /Firefox|FxiOS/i.test(userAgent);
    const isChrome = /Chrome|CriOS/i.test(userAgent) && !isEdge && !isOpera;
    const isChromium = /Chromium/i.test(userAgent) || isChrome;
    const isSafari =
      /Safari/i.test(userAgent) &&
      !isChrome &&
      !isChromium &&
      !isEdge &&
      !isOpera &&
      !isFirefox;
    const isIOS = /iPhone|iPad|iPod/i.test(userAgent);
    const isMac = /Macintosh|Mac OS X/i.test(userAgent);
    const isWindows = /Win/i.test(userAgent);

    setBrowserInfo({
      isSafari,
      isFirefox,
      isChrome,
      isChromium,
      isEdge,
      isOpera,
      isIOS,
      isMac,
      isWindows,
    });
  }, []);

  return browserInfo;
}
