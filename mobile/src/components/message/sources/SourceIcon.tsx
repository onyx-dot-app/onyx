// Mobile has no per-connector glyph set: web/internet -> globe, everything else
// -> file. (Web uses favicons + curated connector icons; deferred.)

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
