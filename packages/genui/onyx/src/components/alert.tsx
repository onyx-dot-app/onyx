import React from "react";
import { z } from "zod";
import { defineComponent } from "@onyx/genui";
import Message from "@/refresh-components/messages/Message";

export const alertComponent = defineComponent({
  name: "Alert",
  description: "A status message banner (info, success, warning, error)",
  group: "Feedback",
  props: z.object({
    text: z.string().describe("Alert message text"),
    description: z.string().optional().describe("Additional description"),
    level: z
      .enum(["default", "info", "success", "warning", "error"])
      .optional()
      .describe("Alert severity level"),
    showIcon: z.boolean().optional().describe("Show status icon"),
  }),
  component: ({
    props,
  }: {
    props: {
      text: string;
      description?: string;
      level?: "default" | "info" | "success" | "warning" | "error";
      showIcon?: boolean;
    };
  }) => {
    const level = props.level ?? "default";

    return (
      <Message
        static
        text={props.text}
        description={props.description}
        default={level === "default"}
        info={level === "info"}
        success={level === "success"}
        warning={level === "warning"}
        error={level === "error"}
        icon={props.showIcon !== false}
        close={false}
      />
    );
  },
});
