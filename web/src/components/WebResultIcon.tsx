"use client";

import { ValidSources } from "@/lib/types";
import { SourceIcon } from "./SourceIcon";
import { useState } from "react";

export function WebResultIcon({ url }: { url: string }) {
  const [error, setError] = useState(false);
  const hostname = new URL(url).hostname;
  return (
    <>
      {!error ? (
        <img
          className="my-0 w-5 h-5  rounded-full py-0"
          src={`https://t3.gstatic.com/faviconV2?client=SOCIAL&type=FAVICON&fallback_opts=TYPE,SIZE,URL&url=https://${hostname}&size=128`}
          style={{ background: "transparent" }}
          alt="favicon"
          height={64}
          onError={() => setError(true)}
          width={64}
        />
      ) : (
        <SourceIcon sourceType={ValidSources.Web} iconSize={18} />
      )}
    </>
  );
}
