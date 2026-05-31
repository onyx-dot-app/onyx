// SourceIcon.tsx — glyph for a citation source (amendment M7).
//
// Mobile has no per-connector glyph set, so we use a documented fallback:
// web/internet sources -> globe; everything else -> file. (Web uses favicons +
// curated connector icons; that fidelity is deferred.)

import { SvgGlobe, SvgFileText } from "@/components/icons";
import type { IconProps } from "@/components/icons/Icon";

interface SourceIconProps extends IconProps {
  sourceType?: string;
  isInternet?: boolean;
}

export function SourceIcon({ sourceType, isInternet, ...props }: SourceIconProps) {
  const web = isInternet || sourceType === "web";
  return web ? <SvgGlobe {...props} /> : <SvgFileText {...props} />;
}

export default SourceIcon;
