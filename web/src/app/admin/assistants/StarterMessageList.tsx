"use client";

import { ArrayHelpers } from "formik";
import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from "@/components/ui/tooltip";
import { useMemo } from "react";
import { StarterMessage } from "./interfaces";
import Button from "@/refresh-components/buttons/Button";
import { TextFormField } from "@/components/Field";
import SvgTrash from "@/icons/trash";
import { cn } from "@/lib/utils";
import SvgRefreshCw from "@/icons/refresh-cw";
import Text from "@/refresh-components/texts/Text";
import { MAX_STARTER_MESSAGES } from "@/lib/constants";
import IconButton from "@/refresh-components/buttons/IconButton";

export interface StarterMessagesListProps {
  values: StarterMessage[];
  arrayHelpers: ArrayHelpers;
  isRefreshing: boolean;
  debouncedRefreshPrompts: () => void;
  autoStarterMessageEnabled: boolean;
  setFieldValue: any;
}

export default function StarterMessagesList({
  values,
  arrayHelpers,
  isRefreshing,
  debouncedRefreshPrompts,
  autoStarterMessageEnabled,
  setFieldValue,
}: StarterMessagesListProps) {
  const handleInputChange = (index: number, value: string) => {
    setFieldValue(`starter_messages.${index}.message`, value);

    if (value && index === values.length - 1 && values.length < 4) {
      arrayHelpers.push({ message: "" });
    } else if (!value && index === values.length - 2) {
      const lastItem = values[values.length - 1];
      if (lastItem !== undefined && !lastItem.message) {
        // Check if lastItem's message is also empty
        arrayHelpers.pop();
      }
    }
  };

  const maxMessagesReached = useMemo(() => {
    const validMessages = values.filter((message) => message.message !== "");
    return validMessages.length >= MAX_STARTER_MESSAGES;
  }, [values]);

  return (
    <div className="flex flex-col gap-spacing-interline">
      {values.map((starterMessage, index) => (
        <div key={index} className="flex items-center gap-2">
          <TextFormField
            name={`starter_messages.${index}.message`}
            label=""
            onChange={(e) => handleInputChange(index, e.target.value)}
            className="flex-grow"
            removeLabel
            small
          />
          <IconButton
            type="button"
            secondary
            onClick={() => {
              arrayHelpers.remove(index);
            }}
            disabled={
              (index === values.length - 1 && !starterMessage.message) ||
              (values.length === 1 && index === 0) // should never happen, but just in case
            }
            icon={SvgTrash}
          />
        </div>
      ))}

      <TooltipProvider>
        <Tooltip>
          <TooltipTrigger asChild>
            <Button
              type="button"
              onClick={() => {
                const shouldSubmit =
                  values.filter((msg) => msg.message.trim() !== "").length <
                    4 &&
                  !isRefreshing &&
                  autoStarterMessageEnabled;
                if (shouldSubmit) {
                  debouncedRefreshPrompts();
                }
              }}
              disabled={isRefreshing || maxMessagesReached}
              leftIcon={({ className }) => (
                <SvgRefreshCw
                  className={cn(className, isRefreshing && "animate-spin")}
                />
              )}
            >
              Generate
            </Button>
          </TooltipTrigger>
          {!autoStarterMessageEnabled && (
            <TooltipContent side="top" align="center">
              <Text inverted>
                No LLM providers configured. Generation is not available.
              </Text>
            </TooltipContent>
          )}
          {maxMessagesReached && (
            <TooltipContent side="top" align="center">
              <Text inverted>Max four starter messages</Text>
            </TooltipContent>
          )}
        </Tooltip>
      </TooltipProvider>
    </div>
  );
}
