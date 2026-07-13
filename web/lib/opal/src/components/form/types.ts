import type React from "react";
import type { RichStr } from "@opal/types";

export type FormFieldState = "idle" | "success" | "error";
export type APIFormFieldState = FormFieldState | "loading";

export interface FieldContextType {
  baseId: string;
  name?: string;
  required?: boolean;
  state: FormFieldState;
  describedByIds: string[];
}

export type FormFieldRootProps = React.HTMLAttributes<HTMLDivElement> & {
  name?: string;
  state?: FormFieldState;
  required?: boolean;
  id?: string;
};

export type LabelProps = React.HTMLAttributes<HTMLLabelElement> & {
  leftIcon?: React.ReactNode;
  rightIcon?: React.ReactNode;
  optional?: boolean;
  required?: boolean;
  rightAction?: React.ReactNode;
};

export type ControlProps = React.PropsWithChildren<{
  asChild?: boolean;
}>;

export type DescriptionProps = {
  id?: string;
  children?: string | RichStr;
};

export type MessageByState = Partial<Record<FormFieldState, string | RichStr>>;
export type APIMessageByState = Partial<
  Record<FormFieldState | "loading", string | RichStr>
>;

export type MessageProps = {
  className?: string;
  messages?: MessageByState;
  render?: (state: FormFieldState) => React.ReactNode;
};

export type APIMessageProps = {
  className?: string;
  state?: APIFormFieldState;
  messages?: APIMessageByState;
};
