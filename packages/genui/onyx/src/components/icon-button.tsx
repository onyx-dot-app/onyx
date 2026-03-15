import React from "react";
import { z } from "zod";
import { defineComponent } from "@onyx/genui";
import IconButton from "@/refresh-components/buttons/IconButton";
import { useTriggerAction } from "@onyx/genui-react";
import {
  SvgCopy,
  SvgDownload,
  SvgExternalLink,
  SvgMoreHorizontal,
  SvgPlus,
  SvgRefreshCw,
  SvgSearch,
  SvgSettings,
  SvgTrash,
  SvgX,
} from "@opal/icons";
import type { IconFunctionComponent } from "@opal/types";

const iconMap: Record<string, IconFunctionComponent> = {
  copy: SvgCopy,
  download: SvgDownload,
  "external-link": SvgExternalLink,
  more: SvgMoreHorizontal,
  plus: SvgPlus,
  refresh: SvgRefreshCw,
  search: SvgSearch,
  settings: SvgSettings,
  trash: SvgTrash,
  close: SvgX,
};

export const iconButtonComponent = defineComponent({
  name: "IconButton",
  description: "A button that displays an icon with an optional tooltip",
  group: "Interactive",
  props: z.object({
    icon: z
      .string()
      .describe(
        "Icon name (copy, download, external-link, more, plus, refresh, search, settings, trash, close)",
      ),
    tooltip: z.string().optional().describe("Tooltip text on hover"),
    main: z.boolean().optional().describe("Main variant styling"),
    action: z.boolean().optional().describe("Action variant styling"),
    danger: z.boolean().optional().describe("Danger/destructive variant"),
    primary: z.boolean().optional().describe("Primary sub-variant"),
    secondary: z.boolean().optional().describe("Secondary sub-variant"),
    actionId: z
      .string()
      .optional()
      .describe("Action identifier for event handling"),
    disabled: z.boolean().optional().describe("Disable the button"),
  }),
  component: ({
    props,
  }: {
    props: {
      icon: string;
      tooltip?: string;
      main?: boolean;
      action?: boolean;
      danger?: boolean;
      primary?: boolean;
      secondary?: boolean;
      actionId?: string;
      disabled?: boolean;
    };
  }) => {
    const triggerAction = useTriggerAction();
    const IconComponent = iconMap[props.icon] ?? SvgMoreHorizontal;

    return (
      <IconButton
        icon={IconComponent}
        tooltip={props.tooltip}
        main={props.main}
        action={props.action}
        danger={props.danger}
        primary={props.primary}
        secondary={props.secondary}
        disabled={props.disabled}
        onClick={
          props.actionId ? () => triggerAction(props.actionId!) : undefined
        }
      />
    );
  },
});
