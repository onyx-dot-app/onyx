"use client";

import Text from "@/refresh-components/texts/Text";
import { SvgXOctagon, SvgAlertCircle } from "@opal/icons";
import { useField, useFormikContext } from "formik";
import { Section } from "@/layouts/general-layouts";
import { cn } from "@/lib/utils";

interface OrientationLayoutProps extends LabelLayoutProps {
  children?: React.ReactNode;
}

/**
 * VerticalInputLayout - A layout component for form fields with vertical label arrangement
 *
 * Use this layout when you want the label, input, and error message stacked vertically.
 * Common for most form inputs where the label appears above the input field.
 *
 * Exported as `Vertical` for convenient usage.
 *
 * @example
 * ```tsx
 * import { Vertical } from "@/layouts/input-layouts";
 *
 * <Vertical
 *   name="email"
 *   title="Email Address"
 *   description="We'll never share your email"
 *   optional
 * >
 *   <InputTypeIn name="email" type="email" />
 * </Vertical>
 * ```
 */
export interface VerticalLayoutProps extends OrientationLayoutProps {
  subDescription?: React.ReactNode;
}
function VerticalInputLayout({
  children,
  subDescription,
  name,
  ...fieldLabelProps
}: VerticalLayoutProps) {
  return (
    <Section gap={0.25} alignItems="start">
      <LabelLayout name={name} {...fieldLabelProps} />
      {children}
      {name && <ErrorLayout name={name} />}
      {subDescription && (
        <Text secondaryBody text03>
          {subDescription}
        </Text>
      )}
    </Section>
  );
}

/**
 * HorizontalInputLayout - A layout component for form fields with horizontal label arrangement
 *
 * Use this layout when you want the label on the left and the input control on the right.
 * Commonly used for toggles, switches, and checkboxes where the label and control
 * should be side-by-side.
 *
 * Exported as `Horizontal` for convenient usage.
 *
 * @example
 * ```tsx
 * import { Horizontal } from "@/layouts/input-layouts";
 *
 * // Default behavior (top-aligned)
 * <Horizontal
 *   name="notifications"
 *   title="Enable Notifications"
 *   description="Receive updates about your account"
 * >
 *   <Switch name="notifications" />
 * </Horizontal>
 *
 * // Force center alignment (vertically centers input with label)
 * <Horizontal
 *   name="notifications"
 *   title="Enable Notifications"
 *   description="Receive updates about your account"
 *   center
 * >
 *   <Switch name="notifications" />
 * </Horizontal>
 * ```
 */
export interface HorizontalLayoutProps extends OrientationLayoutProps {
  /* There are certain input-layouts which are "static" and should not have the pointer-cursor appear on them. */
  cursorPointer?: boolean;
  /** Align input to the center (middle) of the label/description */
  center?: boolean;
}
function HorizontalInputLayout({
  cursorPointer = true,
  center,

  children,
  name,
  ...fieldLabelProps
}: HorizontalLayoutProps) {
  return (
    <label
      htmlFor={name}
      className={cn(cursorPointer && "cursor-pointer", "w-full")}
    >
      <Section gap={0.25} alignItems="start">
        <Section
          flexDirection="row"
          justifyContent="between"
          alignItems={center ? "center" : "start"}
        >
          <LabelLayout {...fieldLabelProps} />
          <Section alignItems="end" width="fit">
            {children}
          </Section>
        </Section>
        {name && <ErrorLayout name={name} />}
      </Section>
    </label>
  );
}

/**
 * LabelLayout - A reusable label component for form fields
 *
 * Renders a semantic label element with optional description and "Optional" indicator.
 * If no `name` prop is provided, renders a `div` instead of a `label` element.
 *
 * Exported as `Label` for convenient usage.
 *
 * @param name - The field name to associate the label with (renders as `<label>` if provided)
 * @param title - The main label text
 * @param description - Additional helper text shown below the title
 * @param optional - Whether to show "(Optional)" indicator
 * @param center - If true, centers the title and description text. Default: false
 *
 * @example
 * ```tsx
 * import { Label } from "@/layouts/input-layouts";
 *
 * <Label
 *   name="username"
 *   title="Username"
 *   description="Choose a unique username"
 *   optional
 * />
 * ```
 */
export interface LabelLayoutProps {
  name?: string;
  title: string;
  description?: string;
  optional?: boolean;
  center?: boolean;
}
function LabelLayout({
  name,
  title,
  optional,
  description,
  center,
}: LabelLayoutProps) {
  const content = (
    <Section gap={0} height="fit">
      <Section
        flexDirection="row"
        justifyContent={center ? "center" : "start"}
        gap={0.25}
      >
        <Text mainContentEmphasis text04>
          {title}
        </Text>
        {optional && (
          <Text text03 mainContentMuted>
            (Optional)
          </Text>
        )}
      </Section>

      {description && (
        <Section alignItems={center ? "center" : "start"}>
          <Text secondaryBody text03>
            {description}
          </Text>
        </Section>
      )}
    </Section>
  );

  if (!name) return content;
  return (
    <label htmlFor={name} className="w-full">
      {content}
    </label>
  );
}

/**
 * ErrorLayout - Displays Formik field validation errors
 *
 * Automatically shows error messages from Formik's validation state.
 * Only displays when the field has been touched and has an error.
 *
 * Exported as `Error` for convenient usage.
 *
 * @param name - The Formik field name to display errors for
 *
 * @example
 * ```tsx
 * import { Error } from "@/layouts/input-layouts";
 *
 * <InputTypeIn name="email" />
 * <Error name="email" />
 * ```
 *
 * @remarks
 * This component uses Formik's `useField` hook internally and requires
 * the component to be rendered within a Formik context.
 */
interface FieldErrorLayoutProps {
  name: string;
}
function ErrorLayout({ name }: FieldErrorLayoutProps) {
  const [, meta] = useField(name);
  const { status } = useFormikContext();
  const warning = status?.warnings?.[name];
  if (warning && typeof warning !== "string")
    throw new Error("The warning that is set must ALWAYS be a string");

  const hasError = meta.touched && meta.error;
  const hasWarning = warning; // Don't require touched for warnings

  // If `hasError` and `hasWarning` are both true at the same time, the error is prioritized and returned first.
  if (hasError)
    return <ErrorTextLayout type="error">{meta.error}</ErrorTextLayout>;
  else if (hasWarning)
    return <ErrorTextLayout type="warning">{warning}</ErrorTextLayout>;
  else return null;
}

export type ErrorTextType = "error" | "warning";
interface ErrorTextLayoutProps {
  children?: string;
  type?: ErrorTextType;
}
function ErrorTextLayout({ children, type = "error" }: ErrorTextLayoutProps) {
  const Icon = type === "error" ? SvgXOctagon : SvgAlertCircle;
  const colorClass =
    type === "error" ? "text-status-error-05" : "text-status-warning-05";
  const strokeClass =
    type === "error" ? "stroke-status-error-05" : "stroke-status-warning-05";

  return (
    <div className="px-1">
      <Section flexDirection="row" justifyContent="start" gap={0.25}>
        <Icon size={12} className={strokeClass} />
        <Text secondaryBody className={colorClass} role="alert">
          {children}
        </Text>
      </Section>
    </div>
  );
}

export {
  VerticalInputLayout as Vertical,
  HorizontalInputLayout as Horizontal,
  LabelLayout as Label,
  ErrorLayout as Error,
  ErrorTextLayout,
};
