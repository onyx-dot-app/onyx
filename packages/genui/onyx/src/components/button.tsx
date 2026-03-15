import React from "react";
import { z } from "zod";
import { defineComponent } from "@onyx/genui";
import Button from "@/refresh-components/buttons/Button";
import { useTriggerAction } from "@onyx/genui-react";

export const buttonComponent = defineComponent({
  name: "Button",
  description: "An interactive button that triggers an action",
  group: "Interactive",
  props: z.object({
    children: z.string().describe("Button label text"),
    main: z.boolean().optional().describe("Main variant styling"),
    action: z.boolean().optional().describe("Action variant styling"),
    danger: z.boolean().optional().describe("Danger/destructive variant"),
    primary: z.boolean().optional().describe("Primary sub-variant"),
    secondary: z.boolean().optional().describe("Secondary sub-variant"),
    tertiary: z.boolean().optional().describe("Tertiary sub-variant"),
    size: z.enum(["lg", "md"]).optional().describe("Button size"),
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
      children: string;
      main?: boolean;
      action?: boolean;
      danger?: boolean;
      primary?: boolean;
      secondary?: boolean;
      tertiary?: boolean;
      size?: "lg" | "md";
      actionId?: string;
      disabled?: boolean;
    };
  }) => {
    const triggerAction = useTriggerAction();

    return (
      <Button
        main={props.main}
        action={props.action}
        danger={props.danger}
        primary={props.primary}
        secondary={props.secondary}
        tertiary={props.tertiary}
        size={props.size}
        disabled={props.disabled}
        onClick={
          props.actionId ? () => triggerAction(props.actionId!) : undefined
        }
      >
        {props.children}
      </Button>
    );
  },
});
