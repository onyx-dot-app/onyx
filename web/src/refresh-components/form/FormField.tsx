import { cn } from "@/lib/utils";
import { FieldContext } from "./FieldContext";
import {
  ControlProps,
  DescriptionProps,
  FieldContextType,
  FormFieldRootProps,
  LabelProps,
  MessageProps,
} from "./types";
import React, { useId, useMemo } from "react";
import { useFieldContext } from "./FieldContext";
import { Slot } from "@radix-ui/react-slot";

export const FormFieldRoot: React.FC<FormFieldRootProps> = ({
  id,
  name,
  state = "idle",
  message = null,
  description = null,
  required,
  className,
  children,
  ...props
}) => {
  const reactId = useId();
  const baseId = id ?? `field_${reactId}`;

  const describedByIds = useMemo(() => {
    const ids: string[] = [];
    if (description) ids.push(`${baseId}-desc`);
    if (message) ids.push(`${baseId}-msg`);
    return ids;
  }, [description, message, baseId]);

  const contextValue: FieldContextType = {
    baseId,
    name,
    required,
    state,
    message,
    description,
    describedByIds,
  };

  return (
    <FieldContext.Provider value={contextValue}>
      <div
        id={baseId}
        className={cn("flex flex-col gap-y-2", className)}
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
  isOptional,
  className,
  children,
  ...props
}) => {
  const { baseId } = useFieldContext();
  return (
    <label
      id={`${baseId}-label`}
      htmlFor={`${baseId}-control`}
      className={cn("block text-sm font-medium leading-6", className)}
      {...props}
    >
      <span className="inline-flex items-center gap-2">
        {leftIcon}
        <span>
          {children}
          {isOptional ? (
            <span className="ml-2 text-xs text-muted-foreground">
              ({isOptional ? "Optional" : ""})
            </span>
          ) : null}
        </span>
        {rightIcon}
      </span>
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
      ...children.props,
    });
  }

  return <>{children}</>;
};

export const FormFieldDescription: React.FC<DescriptionProps> = ({
  className,
  children,
  ...props
}) => {
  const { baseId, description } = useFieldContext();
  const content = description ?? children;
  if (!content) return null;
  return (
    <p
      id={`${baseId}-desc`}
      className={cn("text-sm text-muted-foreground", className)}
      {...props}
    >
      {content}
    </p>
  );
};

export const FormFieldMessage: React.FC<MessageProps> = ({
  className,
  messages,
  render,
  children,
  ...props
}) => {
  const { baseId, state, message } = useFieldContext();
  const content =
    (messages && messages[state]) ??
    (render && render(state)) ??
    message ??
    children;

  if (!content) return null;

  const stateClass =
    state === "error"
      ? "text-destructive"
      : state === "success"
        ? "text-emerald-600"
        : state === "loading"
          ? "text-muted-foreground"
          : "text-muted-foreground";

  return (
    <div
      id={`${baseId}-msg`}
      role={state === "error" ? "alert" : undefined}
      aria-live={state === "error" ? "assertive" : "polite"}
      className={cn("text-sm", stateClass, className)}
      {...props}
    >
      {content}
    </div>
  );
};

export const FormField = Object.assign(FormFieldRoot, {
  Label: FormFieldLabel,
  Control: FormFieldControl,
  Description: FormFieldDescription,
  Message: FormFieldMessage,
});
