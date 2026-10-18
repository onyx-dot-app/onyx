import type { TagProps } from "@opal/components";
import type { PluginKind } from "@/lib/plugins/types";

/**
 * Each plugin type's tag. The titles are product names, so they are not
 * translated. Craft is blue; the rest are gray.
 */
export const PLUGIN_KIND_TAGS: Record<
  PluginKind,
  Pick<TagProps, "title" | "color">
> = {
  mcp: { title: "MCP", color: "gray" },
  openapi: { title: "OpenAPI", color: "gray" },
  "external-app": { title: "Craft", color: "blue" },
};
