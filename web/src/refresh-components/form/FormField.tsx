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
import SvgCheckCircle from "@/icons/check-circle";

import SvgXOctagon from "@/icons/x-octagon";
import SvgLoader from "@/icons/loader";

const iconMap = {
  error: <SvgXOctagon className="h-3 w-3 stroke-status-error-05" />,
  success: <SvgCheckCircle className="h-3 w-3 stroke-status-success-05" />,
  idle: null,
  loading: <SvgLoader className="h-3 w-3 stroke-text-02 animate-spin" />,
};

const FieldMessageContent: React.FC<{
  baseId: string;
  state: "idle" | "error" | "success" | "loading";
  content: React.ReactNode;
  className?: string;
  idSuffix?: string;
}> = ({ baseId, state, content, className, idSuffix = "msg" }) => {
  return (
    <div className="flex flex-row items-center gap-x-0.5">
      {state !== "idle" && (
        <div className="w-4 h-4 flex items-center justify-center">
          {iconMap[state]}
        </div>
      )}
      <Text
        id={`${baseId}-${idSuffix}`}
        text03
        secondaryBody
        className={cn("ml-0.5", className)}
      >
        {content}
      </Text>
    </div>
  );
};

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
        "ml-0.5 text-text-04 font-main-ui-action flex flex-row",
        className
      )}
      {...props}
    >
      {children}
      {optional ? (
        <Text text03 mainUiMuted className="mx-0.5">
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
    <FieldMessageContent
      baseId={baseId}
      state={tempState}
      content={content}
      className={className}
    />
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
    <FieldMessageContent
      baseId={baseId}
      state={state}
      content={content}
      className={className}
      idSuffix="api-msg"
    />
  ) : null;
};

export const FormField = Object.assign(FormFieldRoot, {
  Label: FormFieldLabel,
  Control: FormFieldControl,
  Description: FormFieldDescription,
  Message: FormFieldMessage,
  APIMessage: FormAPIFieldMessage,
});
