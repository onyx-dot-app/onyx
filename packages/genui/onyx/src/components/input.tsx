import React, { useState, useCallback } from "react";
import { z } from "zod";
import { defineComponent } from "@onyx/genui";
import InputTypeIn from "@/refresh-components/inputs/InputTypeIn";
import { useTriggerAction } from "@onyx/genui-react";

export const inputComponent = defineComponent({
  name: "Input",
  description: "A text input field",
  group: "Interactive",
  props: z.object({
    placeholder: z.string().optional().describe("Placeholder text"),
    value: z.string().optional().describe("Initial value"),
    actionId: z
      .string()
      .optional()
      .describe("Action identifier for value changes"),
    readOnly: z.boolean().optional().describe("Make the input read-only"),
  }),
  component: ({
    props,
  }: {
    props: {
      placeholder?: string;
      value?: string;
      actionId?: string;
      readOnly?: boolean;
    };
  }) => {
    const triggerAction = useTriggerAction();
    const [value, setValue] = useState(props.value ?? "");

    const handleChange = useCallback(
      (e: React.ChangeEvent<HTMLInputElement>) => {
        setValue(e.target.value);
      },
      [],
    );

    const handleKeyDown = useCallback(
      (e: React.KeyboardEvent<HTMLInputElement>) => {
        if (e.key === "Enter" && props.actionId) {
          triggerAction(props.actionId, { value });
        }
      },
      [props.actionId, triggerAction, value],
    );

    return (
      <InputTypeIn
        placeholder={props.placeholder}
        value={value}
        onChange={handleChange}
        onKeyDown={handleKeyDown}
        variant={props.readOnly ? "readOnly" : "primary"}
      />
    );
  },
});
