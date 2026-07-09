"use client";

import { SvgOnyxLogo, SvgOnyxLogoTyped } from "@opal/logos";
import type { IconFunctionComponent } from "@opal/types";

function makeImgIcon(src: string): IconFunctionComponent {
  return function AppLogoImg({ size = 48 }) {
    return (
      // eslint-disable-next-line @next/next/no-img-element
      <img
        alt="Logo"
        src={src}
        className="rounded-full object-cover object-center"
        style={{ width: size, height: size }}
      />
    );
  };
}

export function getAppLogo(
  logoSrc: string | null | undefined,
  folded: boolean
): IconFunctionComponent {
  if (logoSrc) return makeImgIcon(logoSrc);
  return folded ? SvgOnyxLogo : SvgOnyxLogoTyped;
}
