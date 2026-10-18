import type { TagProps } from "@opal/components";
import { SvgActions, SvgDevKit, SvgServer } from "@opal/icons";
import type { IconFunctionComponent } from "@opal/types";
import type { PluginKind } from "@/lib/plugins/types";

/**
 * Each plugin type's icon, shared by its tag and its new / edit modals.
 * Craft uses the sidebar's Craft icon.
 */
export const PLUGIN_KIND_ICONS: Record<PluginKind, IconFunctionComponent> = {
  mcp: SvgServer,
  openapi: SvgActions,
  "external-app": SvgDevKit,
};

/**
 * Each plugin type's tag. The titles are product names, so they are not
 * translated. Craft is blue; the rest are gray.
 */
export const PLUGIN_KIND_TAGS: Record<
  PluginKind,
  Pick<TagProps, "title" | "color" | "icon">
> = {
  mcp: { title: "MCP", color: "gray", icon: PLUGIN_KIND_ICONS.mcp },
  openapi: { title: "OpenAPI", color: "gray", icon: PLUGIN_KIND_ICONS.openapi },
  "external-app": {
    title: "Craft",
    color: "blue",
    icon: PLUGIN_KIND_ICONS["external-app"],
  },
};
