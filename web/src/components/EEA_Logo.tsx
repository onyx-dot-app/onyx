"use client";

import { useContext } from "react";
import { SettingsContext } from "./settings/SettingsProvider";
import Image from "next/image";
import { defaultTailwindCSS, IconProps } from "./icons/icons";
import { SiZeromq } from "react-icons/si";

export function Logo({
  height,
  width,
  className,
}: {
  height?: number;
  width?: number;
  className?: string;
}) {
  const settings = useContext(SettingsContext);

  height = height || 32;
  width = width || 70;

  if (
    !settings ||
    !settings.enterpriseSettings ||
    !settings.enterpriseSettings.use_custom_logo
  ) {
    return (
      <div style={{ height, width }} className={className}>
        <Image src="/EEA_logo_compact_EN.svg" alt="Logo" width={width} height={height} />
      </div>
    );
  }

  return (
    <div
      style={{ height, width }}
      className={`flex-none relative ${className}`}
    >
      {/* TODO: figure out how to use Next Image here */}
      <img
        src="/api/enterprise-settings/logo"
        alt="Logo"
        style={{ objectFit: "contain", height, width }}
      />
    </div>
  );
}
export function Logo_empty({
  height,
  width,
  className,
}: {
  height?: number;
  width?: number;
  className?: string;
}) {
  const settings = useContext(SettingsContext);

  height = height || 32;
  width = width || 32;
  if (
    !settings ||
    !settings.enterpriseSettings ||
    !settings.enterpriseSettings.use_custom_logo
  ) {
    return (
      <div style={{ height, width }} className={className}>
      </div>
    );
  }

  return (
    <div
      style={{ height, width }}
      className={`flex-none relative ${className}`}
    >
      {/* TODO: figure out how to use Next Image here */}
      <img
        src="/api/enterprise-settings/logo"
        alt="Logo"
        style={{ objectFit: "contain", height, width }}
      />
    </div>
  );
}

export const EEAIcon = ({

  size = 16,
  className = defaultTailwindCSS,
}: IconProps) => {
  const width = size*2;
  const height = size;
  return (
    <Image src="/EEA_logo_compact_EN.svg" alt="Logo" width={width} height={height} />
  );
};