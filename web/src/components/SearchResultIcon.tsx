"use client";
import { useState, useEffect } from "react";
import faviconFetch from "favicon-fetch";
import { SourceIcon } from "./SourceIcon";
import { ValidSources } from "@/lib/types";
import { OnyxIcon } from "./icons/icons";

const CACHE_DURATION = 24 * 60 * 60 * 1000;

export async function getFaviconUrl(url: string): Promise<string | null> {
  const getCachedFavicon = () => {
    const cachedData = localStorage.getItem(`favicon_${url}`);
    if (cachedData) {
      const { favicon, timestamp } = JSON.parse(cachedData);
      if (Date.now() - timestamp < CACHE_DURATION) {
        return favicon;
      }
    }
    return null;
  };

  const cachedFavicon = getCachedFavicon();
  if (cachedFavicon) {
    return cachedFavicon;
  }

  const newFaviconUrl = await faviconFetch({ uri: url });
  if (newFaviconUrl) {
    localStorage.setItem(
      `favicon_${url}`,
      JSON.stringify({ favicon: newFaviconUrl, timestamp: Date.now() })
    );
    return newFaviconUrl;
  }

  return null;
}

export function SearchResultIcon({ url }: { url: string }) {
  const [faviconUrl, setFaviconUrl] = useState<string | null>(null);

  useEffect(() => {
    getFaviconUrl(url).then((favicon) => {
      if (favicon) {
        setFaviconUrl(favicon);
      }
    });
  }, [url]);

  if (!faviconUrl) {
    return <SourceIcon sourceType={ValidSources.Web} iconSize={18} />;
  }
  if (url.includes("onyx.app")) {
    return <OnyxIcon size={18} className="dark:text-[#fff] text-[#000]" />;
  }

  return (
    <div className="rounded-full w-[18px] h-[18px] overflow-hidden bg-background-200">
      <img
        height={18}
        width={18}
        className="rounded-full w-full h-full object-cover"
        src={faviconUrl}
        alt="favicon"
        onError={(e) => {
          e.currentTarget.onerror = null;
        }}
      />
    </div>
  );
}
