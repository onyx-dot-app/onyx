"use client";

import { Tag, type TagProps } from "@opal/components";
import { PLUGIN_KIND_TAGS } from "@/lib/plugins/constants";
import type { PluginKind } from "@/lib/plugins/types";

export interface PluginKindTagProps {
  kind: PluginKind;
  size?: TagProps["size"];
}

/** A plugin type's badge: "MCP", "OpenAPI" or "Craft". */
export default function PluginKindTag({ kind, size }: PluginKindTagProps) {
  return <Tag {...PLUGIN_KIND_TAGS[kind]} size={size} />;
}
