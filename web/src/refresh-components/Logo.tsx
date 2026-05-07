"use client";

import { useSettingsContext } from "@/providers/SettingsProvider";
import { DEFAULT_LOGO_SIZE_PX } from "@/lib/constants";
import { cn } from "@opal/utils";
import { useMemo } from "react";
import { Flame } from "lucide-react";

export interface LogoProps {
  folded?: boolean;
  size?: number;
  className?: string;
}

/**
 * Brand mark for the operator-brain rebrand. Renders the flame
 * (Ember) icon in the brand blue inside a rounded white tile,
 * paired with the application name when not folded.
 *
 * Enterprise customisation still wins:
 *   - `use_custom_logo` true → render the uploaded image
 *   - `application_name` set → use that as the displayed name
 *   - `logo_display_style` "logo_only" / "name_only" honoured
 *
 * Default brand defaults to "Ember" when the operator hasn't
 * configured an enterprise application name. The component never
 * shows "Powered by Onyx" anymore.
 */
export default function Logo({ folded, size, className }: LogoProps) {
  const resolvedSize = size ?? DEFAULT_LOGO_SIZE_PX;
  const settings = useSettingsContext();
  const logoDisplayStyle = settings.enterpriseSettings?.logo_display_style;
  const applicationName =
    settings.enterpriseSettings?.application_name?.trim() || "Ember";

  // Cache-buster: the logo URL never changes (/api/enterprise-settings/logo)
  // so the browser serves the in-memory cached image even after an admin
  // uploads a new one. Generating a fresh timestamp each time enterprise
  // settings are revalidated by SWR appends a unique query param to force
  // the browser to re-fetch the image.
  const logoBuster = useMemo(
    () => Date.now(),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [settings.enterpriseSettings]
  );

  const tileSize = resolvedSize;
  const flameSize = Math.max(12, Math.round(tileSize * 0.55));

  const customMark = settings.enterpriseSettings?.use_custom_logo;
  const mark = customMark ? (
    <div
      className={cn(
        "aspect-square rounded-full overflow-hidden relative flex-shrink-0",
        className
      )}
      style={{ height: tileSize, width: tileSize }}
    >
      {/* eslint-disable-next-line @next/next/no-img-element */}
      <img
        alt="Logo"
        src={`/api/enterprise-settings/logo?v=${logoBuster}`}
        className="object-cover object-center w-full h-full"
      />
    </div>
  ) : (
    <div
      className={cn(
        "flex items-center justify-center rounded-xl border border-neutral-200 bg-white flex-shrink-0",
        className
      )}
      style={{ width: tileSize, height: tileSize, color: "#295EFF" }}
      aria-hidden="true"
    >
      <Flame
        size={flameSize}
        strokeWidth={2}
        color="#295EFF"
        style={{ color: "#295EFF" }}
      />
    </div>
  );

  const nameNode = (
    <span
      className="font-semibold tracking-tight text-neutral-900 leading-none truncate"
      style={{ fontSize: Math.max(13, Math.round(tileSize * 0.5)) }}
    >
      {applicationName}
    </span>
  );

  if (folded) return mark;

  if (logoDisplayStyle === "logo_only") return mark;

  if (logoDisplayStyle === "name_only") {
    return <div className="flex items-center min-w-0">{nameNode}</div>;
  }

  // Default + "logo_and_name": both, side by side.
  return (
    <div className="flex items-center min-w-0 gap-2.5">
      {mark}
      {nameNode}
    </div>
  );
}
