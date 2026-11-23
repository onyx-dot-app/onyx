"use client";

import { useState } from "react";
import { SvgGlobe } from "@opal/icons";
import type { IconFunctionComponent, IconProps } from "@opal/types";
import { cn } from "@opal/utils";

// One icon component per host, so a chip keeps the same component (and its
// loaded image) across renders.
const FAVICON_ICONS = new Map<string, IconFunctionComponent>();

function hostnameOf(url: string): string | null {
  try {
    return new URL(url).hostname || null;
  } catch {
    return null;
  }
}

/**
 * An icon that shows a web page's favicon, and the globe when the URL has no
 * host or its favicon fails to load. The favicon comes from Google's favicon
 * service, as in the search results.
 */
export function faviconIcon(url: string): IconFunctionComponent {
  const host = hostnameOf(url);
  if (host === null) return SvgGlobe;
  const cached = FAVICON_ICONS.get(host);
  if (cached) return cached;

  const src = `https://t3.gstatic.com/faviconV2?client=SOCIAL&type=FAVICON&fallback_opts=TYPE,SIZE,URL&url=${encodeURIComponent(`https://${host}`)}&size=64`;

  function Favicon({ size = 16, className }: IconProps) {
    const [failed, setFailed] = useState(false);
    if (failed) return <SvgGlobe size={size} className={className} />;
    return (
      <img
        src={src}
        alt=""
        width={size}
        height={size}
        className={cn("shrink-0 rounded-full", className)}
        onError={() => setFailed(true)}
      />
    );
  }

  FAVICON_ICONS.set(host, Favicon);
  return Favicon;
}
