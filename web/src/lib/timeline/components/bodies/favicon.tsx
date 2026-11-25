"use client";

import { useState } from "react";
import { SvgGlobe } from "@opal/icons";
import type { IconFunctionComponent, IconProps } from "@opal/types";
import { cn } from "@opal/utils";

// One icon component per host, so a chip keeps the same component (and its
// loaded image) across renders.
const FAVICON_ICONS = new Map<string, IconFunctionComponent>();

const PRIVATE_SUFFIXES = [
  ".local",
  ".internal",
  ".lan",
  ".home",
  ".home.arpa",
  ".corp",
];

/** Whether four IPv4 octets are loopback, private or link-local. */
function isPrivateIpv4([a = 0, b = 0]: number[]): boolean {
  return (
    a === 10 ||
    a === 127 ||
    (a === 172 && b >= 16 && b <= 31) ||
    (a === 192 && b === 168) ||
    (a === 169 && b === 254)
  );
}

/** The IPv4 octets of an IPv4-mapped IPv6 address (`::ffff:a00:1`). */
function mappedIpv4(name: string): number[] | null {
  const dotted = /^::ffff:(\d+)\.(\d+)\.(\d+)\.(\d+)$/.exec(name);
  if (dotted) return dotted.slice(1).map(Number);
  const hex = /^::ffff:([0-9a-f]{1,4}):([0-9a-f]{1,4})$/.exec(name);
  if (!hex) return null;
  const high = parseInt(hex[1] ?? "0", 16);
  const low = parseInt(hex[2] ?? "0", 16);
  return [high >> 8, high & 0xff, low >> 8, low & 0xff];
}

/**
 * Whether a host is private: a lookup in Google's favicon service would
 * reveal it. `localhost`, single-label names, private DNS suffixes, and
 * loopback, private and link-local IP addresses.
 */
function isPrivateHost(host: string): boolean {
  // Without IPv6 brackets or a terminal DNS dot (`payroll.internal.`).
  const name = host
    .toLowerCase()
    .replace(/^\[|\]$/g, "")
    .replace(/\.+$/, "");
  if (name === "localhost" || name.endsWith(".localhost")) return true;
  if (
    PRIVATE_SUFFIXES.some(
      (suffix) => name === suffix.slice(1) || name.endsWith(suffix)
    )
  )
    return true;
  if (name.includes(":")) {
    // An IPv4-mapped address is private when its IPv4 address is.
    const mapped = mappedIpv4(name);
    if (mapped) return isPrivateIpv4(mapped);
    // IPv6: loopback, unique local (fc00::/7) and link-local (fe80::/10).
    return name === "::1" || /^f[cd]/.test(name) || /^fe[89ab]/.test(name);
  }
  const octets = name.split(".").map(Number);
  if (octets.length === 4 && octets.every((octet) => Number.isInteger(octet))) {
    return isPrivateIpv4(octets);
  }
  // A name without a dot only resolves on a private network.
  return !name.includes(".");
}

function hostnameOf(url: string): string | null {
  try {
    return new URL(url).hostname || null;
  } catch {
    return null;
  }
}

/**
 * An icon that shows a web page's favicon, and the globe when the URL has no
 * host, its host is private, or its favicon fails to load. The favicon comes
 * from Google's favicon service, as in the search results, so a private host
 * is never sent there.
 */
export function faviconIcon(url: string): IconFunctionComponent {
  const host = hostnameOf(url);
  if (host === null || isPrivateHost(host)) return SvgGlobe;
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
        // The lookup never tells Google which deployment asked.
        referrerPolicy="no-referrer"
        className={cn("shrink-0 rounded-full", className)}
        onError={() => setFailed(true)}
      />
    );
  }

  FAVICON_ICONS.set(host, Favicon);
  return Favicon;
}
