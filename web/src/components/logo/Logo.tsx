"use client";

import { useContext } from "react";
import { SettingsContext } from "@/components/settings/SettingsProvider";
import { OnyxIcon, OnyxLogoTypeIcon } from "@/components/icons/icons";

interface LogoProps {
  height?: number;
  width?: number;
  className?: string;
  size?: "small" | "default" | "large";
}

export function Logo({
  height,
  width,
  className,
  size = "default",
}: LogoProps) {
  const settings = useContext(SettingsContext);

  const sizeMap = {
    small: { height: 24, width: 22 },
    default: { height: 32, width: 30 },
    large: { height: 48, width: 45 },
  };

  const { height: defaultHeight, width: defaultWidth } = sizeMap[size];
  height = height || defaultHeight;
  width = width || defaultWidth;

  if (
    !settings ||
    !settings.enterpriseSettings ||
    !settings.enterpriseSettings.use_custom_logo
  ) {
    return (
      <div style={{ height, width }} className={className}>
        <OnyxIcon size={height} className={className} />
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

interface LogoTypeProps {
  size?: "small" | "default" | "large";
}

export function LogoType({ size = "default" }: LogoTypeProps) {
  return <OnyxLogoTypeIcon size={115} className="items-center w-full" />;
}
