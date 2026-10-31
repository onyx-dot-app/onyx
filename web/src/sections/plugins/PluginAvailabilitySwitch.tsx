"use client";

import { useTranslations } from "next-intl";
import { InputSwitch } from "@opal/components";
import { ContentAction } from "@opal/layouts";

interface PluginAvailabilitySwitchProps {
  surface?: "chat" | "mcp-craft" | "craft-app" | "workspace";
  enabled: boolean;
  onChange: (enabled: boolean) => void;
  disabled?: boolean;
}

export default function PluginAvailabilitySwitch({
  surface = "craft-app",
  enabled,
  onChange,
  disabled = false,
}: PluginAvailabilitySwitchProps) {
  const t = useTranslations("actions.plugins");
  const label = t(
    surface === "chat"
      ? "controls.enableChat"
      : surface === "workspace"
        ? "controls.enable"
        : "controls.enableCraft"
  );
  const description = t(
    surface === "chat"
      ? "controls.chatDescription"
      : surface === "mcp-craft"
        ? "controls.mcpCraftDescription"
        : surface === "workspace"
          ? "controls.workspaceDescription"
          : "controls.craftAppDescription"
  );
  return (
    <ContentAction
      title={label}
      description={description}
      sizePreset="main-ui"
      variant="section"
      padding={0}
      rightChildren={
        <InputSwitch
          aria-label={label}
          checked={enabled}
          onCheckedChange={onChange}
          disabled={disabled}
        />
      }
    />
  );
}
