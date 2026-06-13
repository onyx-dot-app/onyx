"use client";

import { ValidSources } from "@/lib/types";
import { SourceIcon } from "./SourceIcon";
import { useState } from "react";
import { SvgGithub } from "@opal/logos";
import { GlomiLogoMark } from "@/refresh-components/GlomiLogo";

export function WebResultIcon({
  url,
  size = 18,
}: {
  url: string;
  size?: number;
}) {
  const [error, setError] = useState(false);
  let hostname;
  try {
    hostname = new URL(url).hostname;
  } catch (e) {
    hostname = "glomi.ai";
  }
  return (
    <>
      {hostname.includes("glomi.ai") ? (
        <GlomiLogoMark size={size} />
      ) : hostname === "github.com" || hostname.endsWith(".github.com") ? (
        <SvgGithub size={size} />
      ) : !error ? (
        <img
          className="my-0 rounded-full py-0"
          src={`https://t3.gstatic.com/faviconV2?client=SOCIAL&type=FAVICON&fallback_opts=TYPE,SIZE,URL&url=https://${hostname}&size=128`}
          alt="favicon"
          height={size}
          onError={() => setError(true)}
          width={size}
          style={{
            height: `${size}px`,
            width: `${size}px`,
            background: "transparent",
          }}
        />
      ) : (
        <SourceIcon sourceType={ValidSources.Web} iconSize={size} />
      )}
    </>
  );
}
