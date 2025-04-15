"use client";

import { getSourceMetadata } from "@/lib/sources";
import { ValidSources } from "@/lib/types";

export function SourceIcon({
  sourceType,
  iconSize,
}: {
  sourceType: ValidSources;
  iconSize: number;
}) {
  try {
    return getSourceMetadata(sourceType).icon({
      size: iconSize,
    });
  } catch (error) {
    console.error("Error getting source icon:", error);
    return null;
  }
}
