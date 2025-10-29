"use client";

import { getSourceMetadata } from "@/lib/sources";
import { ValidSources } from "@/lib/types";

export interface SourceIconProps {
  sourceType: ValidSources;
  iconSize: number;
}

export function SourceIcon({ sourceType, iconSize }: SourceIconProps) {
  return getSourceMetadata(sourceType).icon({
    size: iconSize,
  });
}
