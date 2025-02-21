"use client";

import { ArrayHelpers, ErrorMessage, Field, useFormikContext } from "formik";
import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from "@/components/ui/tooltip";
import { useEffect, useState } from "react";
import { FiTrash2, FiRefreshCcw, FiRefreshCw } from "react-icons/fi";
import { StarterMessage } from "./interfaces";
import { Button } from "@/components/ui/button";
import { SwapIcon } from "@/components/icons/icons";
import { TextFormField } from "@/components/admin/connectors/Field";

export default function StarterMessagesList({
  values,
  arrayHelpers,
  isRefreshing,
  debouncedRefreshPrompts,
  autoStarterMessageEnabled,
  setFieldValue,
}: {
  values: StarterMessage[];
  arrayHelpers: ArrayHelpers;
  isRefreshing: boolean;
  debouncedRefreshPrompts: () => void;
  autoStarterMessageEnabled: boolean;
  setFieldValue: any;
}) {
  const [tooltipOpen, setTooltipOpen] = useState(false);

  const handleInputChange = (index: number, value: string) => {
    setFieldValue(`starter_messages.${index}.message`, value);

    if (value && index === values.length - 1 && values.length < 4) {
      arrayHelpers.push({ message: "" });
    } else if (
      !value &&
      index === values.length - 2 &&
      !values[values.length - 1].message
    ) {
      arrayHelpers.pop();
    }
  };

  return (
    <div className="flex flex-col gap-2">
      {values.map((starterMessage, index) => (
        <div key={index} className="flex items-center gap-2">
          <TextFormField
            name={`starter_messages.${index}.message`}
            label=""
            value={starterMessage.message}
            onChange={(e) => handleInputChange(index, e.target.value)}
            className="flex-grow"
            removeLabel
            small
          />
          <Button
            type="button"
            variant="ghost"
            size="icon"
            onClick={() => {
              arrayHelpers.remove(index);
            }}
            className={`text-text-400 hover:text-red-500 ${
              index === values.length - 1 && !starterMessage.message
                ? "opacity-50 cursor-not-allowed"
                : ""
            }`}
            disabled={
              (index === values.length - 1 && !starterMessage.message) ||
              (values.length === 1 && index === 0) // should never happen, but just in case
            }
          >
            <FiTrash2 className="h-4 w-4" />
          </Button>
        </div>
      ))}

      <div className="flex items-center gap-2 ">
        <TooltipProvider delayDuration={50}>
          <Tooltip onOpenChange={setTooltipOpen} open={tooltipOpen}>
            <TooltipTrigger asChild>
              <Button
                type="button"
                size="sm"
                onMouseEnter={() => setTooltipOpen(true)}
                onMouseLeave={() => setTooltipOpen(false)}
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
                className={`
                  ${
                    values.filter((msg) => msg.message.trim() !== "").length >=
                      4 ||
                    isRefreshing ||
                    !autoStarterMessageEnabled
                      ? "bg-background-800 text-text-300 cursor-not-allowed"
                      : ""
                  }
                `}
              >
                <div className="flex text-xs items-center gap-x-2">
                  {isRefreshing ? (
                    <FiRefreshCw className="w-4 h-4 animate-spin text-white" />
                  ) : (
                    <SwapIcon className="w-4 h-4 text-white" />
                  )}
                  Generate
                </div>
              </Button>
            </TooltipTrigger>
            {!autoStarterMessageEnabled && (
              <TooltipContent side="top" align="center">
                <p className="bg-background-950 max-w-[200px] text-sm p-1.5 text-white">
                  No LLM providers configured. Generation is not available.
                </p>
              </TooltipContent>
            )}
            {values.filter((msg) => msg.message.trim() !== "").length >= 4 && (
              <TooltipContent side="top" align="center">
                <p className="bg-background-950 max-w-[200px] text-sm p-1.5 text-white">
                  Max four starter messages
                </p>
              </TooltipContent>
            )}
          </Tooltip>
        </TooltipProvider>
      </div>
    </div>
  );
}
