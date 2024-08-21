"use client";

import { useContext } from "react";
import { SettingsContext } from "./settings/SettingsProvider";
import Image from "next/image";

export function Logo({
  height,
  width,
  className,
  isFullSize
}: {
  height?: number;
  width?: number;
  className?: string;
  isFullSize?: boolean;
}) {
  const settings = useContext(SettingsContext);

  height = height || 32;
  width = width || 30;

  if (
    !settings ||
    !settings.enterpriseSettings ||
    !settings.enterpriseSettings.use_custom_logo
  ) {
    return (
      isFullSize ? 
      <div style={{width}} className={className}>
        <img src="/spectra-logo.svg" alt="Logo" width={width} />
      </div> :
      <div style={{ height, width }} className={className}>
        <Image src="/logo.png" alt="Logo" width={width} height={height} />
      </div>
    );
  }

  return (
    <div style={{ height, width }} className={`relative ${className}`}>
      {/* TODO: figure out how to use Next Image here */}
      <img
        src="/api/enterprise-settings/logo"
        alt="Logo"
        style={{ objectFit: "contain", height, width }}
      />
    </div>
  );
}
