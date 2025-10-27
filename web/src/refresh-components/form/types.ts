import type React from "react";
export type FormFieldState = "idle" | "loading" | "success" | "error";

export interface FieldContextType {
  baseId: string;
  name?: string;
  required?: boolean;
  state: FormFieldState;
  describedByIds: string[];
}

export type FormFieldRootProps = React.HTMLAttributes<HTMLDivElement> & {
  name?: string;
  state: FormFieldState;
  required?: boolean;
  id?: string;
};

export type LabelProps = React.HTMLAttributes<HTMLLabelElement> & {
  leftIcon?: React.ReactNode;
  rightIcon?: React.ReactNode;
  optional?: boolean;
  rightAction?: React.ReactNode;
};

export type ControlProps = React.PropsWithChildren<{
  asChild?: boolean;
}>;

export type DescriptionProps = React.HTMLAttributes<HTMLParagraphElement>;
export type MessageByState = Partial<Record<FormFieldState, string>>;

export type MessageProps = React.HTMLAttributes<HTMLDivElement> & {
  messages?: MessageByState;
  render?: (state: FormFieldState) => React.ReactNode;
};
