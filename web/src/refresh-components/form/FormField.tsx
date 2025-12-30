"use client";

import { cn } from "@/lib/utils";
import { FieldContext } from "./FieldContext";
import {
  ControlProps,
  DescriptionProps,
  FieldContextType,
  FormFieldRootProps,
  LabelProps,
  MessageProps,
  APIMessageProps,
} from "./types";
import React, { useId, useMemo } from "react";
import { useFieldContext } from "./FieldContext";
import { Slot } from "@radix-ui/react-slot";
import Text from "../texts/Text";
import { FieldMessage } from "../messages/FieldMessage";

export const FormFieldRoot: React.FC<FormFieldRootProps> = ({
  id,
  name,
  state = "idle",
  required,
  className,
  children,
  ...props
}) => {
  const reactId = useId();
  const baseId = id ?? `field_${reactId}`;

  const describedByIds = useMemo(() => {
    return [`${baseId}-desc`, `${baseId}-msg`, `${baseId}-api-msg`];
  }, [baseId]);

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
};

export const FormFieldLabel: React.FC<LabelProps> = ({
  leftIcon,
  rightIcon,
  optional,
  required,
  rightAction,
  className,
  children,
  ...props
}) => {
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
        <Text as="p" text03 mainUiMuted className="mx-0.5">
          {"(Required)"}
        </Text>
      ) : optional ? (
        <Text as="p" text03 mainUiMuted className="mx-0.5">
          {"(Optional)"}
        </Text>
      ) : null}
      {rightIcon && <span className="flex items-center">{rightIcon}</span>}
      {rightAction && (
        <span className="ml-auto flex items-center">{rightAction}</span>
      )}
    </label>
  );
};

export const FormFieldControl: React.FC<ControlProps> = ({
  asChild,
  children,
}) => {
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
    return React.cloneElement(children, {
      ...ariaAttributes,
      ...(children.props as any),
    });
  }

  return <>{children}</>;
};

export const FormFieldDescription: React.FC<DescriptionProps> = ({
  className,
  children,
  ...props
}) => {
  const { baseId } = useFieldContext();
  const content = children;
  if (!content) return null;
  return (
    <Text
      as="p"
      id={`${baseId}-desc`}
      text03
      secondaryBody
      className={cn("ml-0.5", className)}
      {...props}
    >
      {content}
    </Text>
  );
};

export const FormFieldMessage: React.FC<MessageProps> = ({
  className,
  messages,
  render,
}) => {
  const { baseId, state } = useFieldContext();
  let tempState = state;
  let content = messages?.[tempState];
  // If the state is success and there is no content, set the state to idle and use the idle message
  if (tempState === "success" && !content) {
    tempState = "idle";
    content = messages?.idle;
  }
  return content ? (
    <FieldMessage variant={tempState} className={className}>
      <FieldMessage.Content id={`${baseId}-msg`}>
        {content}
      </FieldMessage.Content>
    </FieldMessage>
  ) : null;
};

export const FormAPIFieldMessage: React.FC<APIMessageProps> = ({
  className,
  messages,
  state = "loading",
}) => {
  const { baseId } = useFieldContext();
  const content = messages?.[state];
  return content ? (
    <FieldMessage variant={state} className={className}>
      <FieldMessage.Content id={`${baseId}-api-msg`}>
        {content}
      </FieldMessage.Content>
    </FieldMessage>
  ) : null;
};

export const FormField = Object.assign(FormFieldRoot, {
  Label: FormFieldLabel,
  Control: FormFieldControl,
  Description: FormFieldDescription,
  Message: FormFieldMessage,
  APIMessage: FormAPIFieldMessage,
});
