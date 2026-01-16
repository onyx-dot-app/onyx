"use client";

import React, { useRef, useState, useCallback, useEffect } from "react";
import { cn } from "@/lib/utils";
import Text from "@/refresh-components/texts/Text";
import IconButton from "@/refresh-components/buttons/IconButton";
import { SvgArrowUp, SvgStop } from "@opal/icons";

const MAX_INPUT_HEIGHT = 200;

export interface BuildInputBarHandle {
  reset: () => void;
  focus: () => void;
}

interface BuildInputBarProps {
  onSubmit: (message: string) => void;
  onStop?: () => void;
  isRunning: boolean;
  disabled?: boolean;
  placeholder?: string;
}

const BuildInputBar = React.forwardRef<BuildInputBarHandle, BuildInputBarProps>(
  (
    {
      onSubmit,
      onStop,
      isRunning,
      disabled = false,
      placeholder = "Describe your task...",
    },
    ref
  ) => {
    const [message, setMessage] = useState("");
    const textAreaRef = useRef<HTMLTextAreaElement>(null);

    React.useImperativeHandle(ref, () => ({
      reset: () => {
        setMessage("");
        if (textAreaRef.current) {
          textAreaRef.current.style.height = "auto";
        }
      },
      focus: () => {
        textAreaRef.current?.focus();
      },
    }));

    const handleSubmit = useCallback(() => {
      if (!message.trim() || disabled || isRunning) return;
      onSubmit(message.trim());
      setMessage("");
      if (textAreaRef.current) {
        textAreaRef.current.style.height = "auto";
      }
    }, [message, onSubmit, disabled, isRunning]);

    const handleKeyDown = useCallback(
      (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
        if (e.key === "Enter" && !e.shiftKey) {
          e.preventDefault();
          handleSubmit();
        }
      },
      [handleSubmit]
    );

    const handleChange = useCallback(
      (e: React.ChangeEvent<HTMLTextAreaElement>) => {
        setMessage(e.target.value);

        // Auto-resize
        const textarea = e.target;
        textarea.style.height = "auto";
        textarea.style.height = `${Math.min(
          textarea.scrollHeight,
          MAX_INPUT_HEIGHT
        )}px`;
      },
      []
    );

    useEffect(() => {
      textAreaRef.current?.focus();
    }, []);

    const canSubmit = message.trim().length > 0 && !disabled && !isRunning;

    return (
      <div
        className={cn(
          "w-full rounded-16 border border-border-02 bg-background-neutral-00",
          "focus-within:border-border-03 transition-colors",
          "shadow-sm"
        )}
      >
        <div className="flex flex-col p-3">
          <textarea
            ref={textAreaRef}
            value={message}
            onChange={handleChange}
            onKeyDown={handleKeyDown}
            placeholder={placeholder}
            disabled={disabled || isRunning}
            rows={1}
            className={cn(
              "w-full bg-transparent resize-none outline-none",
              "text-text-05 placeholder:text-text-03",
              "min-h-[1.5rem] max-h-[200px]"
            )}
            style={{ fontFamily: "inherit" }}
          />
          <div className="flex flex-row items-center justify-between pt-2">
            <Text secondaryBody text03>
              Press Enter to send, Shift+Enter for new line
            </Text>
            <div className="flex flex-row items-center gap-2">
              {isRunning && onStop ? (
                <IconButton
                  icon={SvgStop}
                  onClick={onStop}
                  primary
                  tooltip="Stop"
                />
              ) : (
                <IconButton
                  icon={SvgArrowUp}
                  onClick={handleSubmit}
                  disabled={!canSubmit}
                  primary
                  tooltip="Send"
                />
              )}
            </div>
          </div>
        </div>
      </div>
    );
  }
);

BuildInputBar.displayName = "BuildInputBar";

export default BuildInputBar;
