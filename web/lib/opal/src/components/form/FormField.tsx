"use client";

import React, { useId, useMemo } from "react";
import { Slot } from "@radix-ui/react-slot";
import { cn } from "@opal/utils";
import { Text } from "@opal/components";
import { FieldContext, useFieldContext } from "./FieldContext";
import { FieldMessage } from "./FieldMessage";
import {
  ControlProps,
  DescriptionProps,
  FieldContextType,
  FormFieldRootProps,
  LabelProps,
  MessageProps,
  APIMessageProps,
} from "./types";

export function FormFieldRoot({
  id,
  name,
  state = "idle",
  required,
  className,
  children,
  ...props
}: FormFieldRootProps) {
  const reactId = useId();
  const baseId = id ?? `field_${reactId}`;

  const describedByIds = useMemo(
    () => [`${baseId}-desc`, `${baseId}-msg`, `${baseId}-api-msg`],
    [baseId]
  );

  const contextValue: FieldContextType = {
    baseId,
    name,
    required,
    state,
    describedByIds,
  };

  return (
    <FieldContext.Provider value={contextValue}>
      <div
        id={baseId}
        className={cn("flex flex-col gap-y-1", className)}
        {...props}
      >
        {children}
      </div>
    </FieldContext.Provider>
  );
}

export function FormFieldLabel({
  leftIcon,
  rightIcon,
  optional,
  required,
  rightAction,
  className,
  children,
  ...props
}: LabelProps) {
  const { baseId } = useFieldContext();
  return (
    <label
      id={`${baseId}-label`}
      htmlFor={`${baseId}-control`}
      className={cn(
        "ml-0.5 text-text-04 font-main-ui-action flex flex-row items-center gap-1",
        className
      )}
      {...props}
    >
      {leftIcon && <span className="flex items-center">{leftIcon}</span>}
      {children}
      {required ? (
        <Text as="p" color="text-03" font="main-ui-muted">
          {"(Required)"}
        </Text>
      ) : optional ? (
        <Text as="p" color="text-03" font="main-ui-muted">
          {"(Optional)"}
        </Text>
      ) : null}
      {rightIcon && <span className="flex items-center">{rightIcon}</span>}
      {rightAction && (
        <span className="ml-auto flex items-center">{rightAction}</span>
      )}
    </label>
  );
}

export function FormFieldControl({ asChild, children }: ControlProps) {
  const { baseId, state, describedByIds, required } = useFieldContext();

  const ariaAttributes = {
    id: `${baseId}-control`,
    "aria-invalid": state === "error",
    "aria-describedby": describedByIds?.join(" "),
    "aria-required": required,
  };

  if (asChild) {
    return <Slot {...ariaAttributes}>{children}</Slot>;
  }

  if (React.isValidElement(children)) {
    // Child props win, matching the asChild Slot branch: a child's own id
    // takes precedence over the injected control id.
    return React.cloneElement(children, {
      ...ariaAttributes,
      ...(children.props as any),
    });
  }

  return <>{children}</>;
}

export function FormFieldDescription({ id, children }: DescriptionProps) {
  const { baseId } = useFieldContext();
  if (!children) return null;
  return (
    <Text
      as="p"
      id={id ?? `${baseId}-desc`}
      color="text-03"
      font="secondary-body"
    >
      {children}
    </Text>
  );
}

export function FormFieldMessage({ className, messages }: MessageProps) {
  const { baseId, state } = useFieldContext();
  // Success with no explicit message falls back to the idle message.
  const effectiveState =
    state === "success" && !messages?.[state] ? "idle" : state;
  const content = messages?.[effectiveState];
  return content ? (
    <FieldMessage variant={effectiveState} className={className}>
      <FieldMessage.Content id={`${baseId}-msg`}>
        {content}
      </FieldMessage.Content>
    </FieldMessage>
  ) : null;
}

export function FormAPIFieldMessage({
  className,
  messages,
  state = "loading",
}: APIMessageProps) {
  const { baseId } = useFieldContext();
  const content = messages?.[state];
  return content ? (
    <FieldMessage variant={state} className={className}>
      <FieldMessage.Content id={`${baseId}-api-msg`}>
        {content}
      </FieldMessage.Content>
    </FieldMessage>
  ) : null;
}

export const FormField = Object.assign(FormFieldRoot, {
  Label: FormFieldLabel,
  Control: FormFieldControl,
  Description: FormFieldDescription,
  Message: FormFieldMessage,
  APIMessage: FormAPIFieldMessage,
});
