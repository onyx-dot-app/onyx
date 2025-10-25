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
import Text from "../texts/Text";

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
    return [`${baseId}-desc`, `${baseId}-msg`];
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
        className={cn("flex flex-col gap-y-spacing-inline", className)}
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
        "ml-spacing-inline-mini text-text-04 font-main-ui-action flex flex-row",
        className
      )}
      {...props}
    >
      {children}
      {optional ? (
        <Text text03 mainUiMuted className="mx-spacing-inline-mini">
          {"(Optional)"}
        </Text>
      ) : null}
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
  const { baseId } = useFieldContext();
  const content = children;
  if (!content) return null;
  return (
    <Text
      id={`${baseId}-desc`}
      text03
      secondaryBody
      className={cn("ml-spacing-inline-mini", className)}
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
  children,
  ...props
}) => {
  const { baseId, state } = useFieldContext();
  const content = children;
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
