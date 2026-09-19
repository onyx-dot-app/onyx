import type React from "react";
export type { FieldContextType, FormFieldState } from "@opal/form";
import type { FormFieldState } from "@opal/form";
export type APIFormFieldState = FormFieldState | "loading";

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

export type DescriptionProps = React.HTMLAttributes<HTMLParagraphElement>;
export type MessageByState = Partial<
  Record<FormFieldState, string | React.ReactNode>
>;
export type APIMessageByState = Partial<
  Record<FormFieldState | "loading", string>
>;

export type MessageProps = React.HTMLAttributes<HTMLDivElement> & {
  messages?: MessageByState;
  render?: (state: FormFieldState) => React.ReactNode;
};

export type APIMessageProps = React.HTMLAttributes<HTMLDivElement> & {
  state?: APIFormFieldState;
  messages?: APIMessageByState;
};
