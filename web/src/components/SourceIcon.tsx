"use client";

import { getSourceMetadata } from "@/lib/sources";
import { ValidSources } from "@/lib/types";

export interface SourceIconProps {
  sourceType: ValidSources;
  iconSize: number;
}

export function SourceIcon({ sourceType, iconSize }: SourceIconProps) {
  // shrink-0: when a flex row overflows, the icon must not be the item that gives way.
  return getSourceMetadata(sourceType).icon({
    size: iconSize,
    className: "text-text-04 shrink-0",
  });
}
