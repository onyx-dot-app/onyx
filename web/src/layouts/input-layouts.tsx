"use client";

import { cn } from "@/lib/utils";
import Text from "@/refresh-components/texts/Text";
import { SvgXOctagon, SvgAlertCircle } from "@opal/icons";
import { useField, useFormikContext } from "formik";
import { Section } from "@/layouts/general-layouts";

interface OrientationLayoutProps extends LabelLayoutProps {
  name?: string;
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
 *   label="Email Address"
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
 * // Default behavior (center-aligned when no description, start-aligned when description exists)
 * <Horizontal
 *   name="notifications"
 *   label="Enable Notifications"
 *   description="Receive updates about your account"
 * >
 *   <Switch name="notifications" />
 * </Horizontal>
 *
 * // Force top alignment
 * <Horizontal
 *   name="notifications"
 *   label="Enable Notifications"
 *   start
 * >
 *   <Switch name="notifications" />
 * </Horizontal>
 *
 * // Force center alignment (even with description)
 * <Horizontal
 *   name="notifications"
 *   label="Enable Notifications"
 *   description="Receive updates about your account"
 *   center
 * >
 *   <Switch name="notifications" />
 * </Horizontal>
 * ```
 */
export interface HorizontalLayoutProps extends OrientationLayoutProps {
  /** Align input to the start (top) of the label/description */
  start?: boolean;
  /** Align input to the center (middle) of the label/description */
  center?: boolean;
}
function HorizontalInputLayout({
  children,

  start,
  center,

  name,
  ...fieldLabelProps
}: HorizontalLayoutProps) {
  // Determine alignment:
  // - If `center` is explicitly true, use center alignment
  // - If `start` is explicitly true, use start alignment
  // - Otherwise, use default behavior: start if description exists, center if not
  const alignment = center
    ? "items-center"
    : start
      ? "items-start"
      : fieldLabelProps.description
        ? "items-start"
        : "items-center";

  return (
    <Section gap={0.25} alignItems="stretch">
      <label
        htmlFor={name}
        className={cn(
          "flex flex-row justify-between gap-4 cursor-pointer",
          alignment
        )}
      >
        <div className="flex-[2]">
          <LabelLayout {...fieldLabelProps} />
        </div>
        <div className="flex-1">
          <Section alignItems="end">{children}</Section>
        </div>
      </label>
      {name && <ErrorLayout name={name} />}
    </Section>
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
 * @param label - The main label text
 * @param optional - Whether to show "(Optional)" indicator
 * @param description - Additional helper text shown below the label
 * @param className - Additional CSS classes
 *
 * @example
 * ```tsx
 * import { Label } from "@/layouts/input-layouts";
 *
 * <Label
 *   name="username"
 *   label="Username"
 *   description="Choose a unique username"
 *   optional
 * />
 * ```
 */
export interface LabelLayoutProps {
  name?: string;
  label?: string;
  optional?: boolean;
  description?: string;
  start?: boolean;
  center?: boolean;
}
function LabelLayout({
  name,
  label,
  optional,
  description,
  start,
  center,
}: LabelLayoutProps) {
  const alignment = start
    ? "items-start"
    : center
      ? "items-center"
      : "items-start";
  const className = cn("flex flex-col w-full", alignment);
  const content = label ? (
    <>
      <Section flexDirection="row" justifyContent="start" gap={0}>
        <Text as="p" mainContentEmphasis text04>
          {label}
        </Text>
        {optional && (
          <Text text03 mainContentMuted as="span">
            {" (Optional)"}
          </Text>
        )}
      </Section>
      {description && (
        <Text as="p" secondaryBody text03>
          {description}
        </Text>
      )}
    </>
  ) : null;

  return name ? (
    <label htmlFor={name} className={className}>
      {content}
    </label>
  ) : (
    <div className={className}>{content}</div>
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

/**
 * ErrorTextLayout - A styled text component for displaying error or warning messages
 *
 * Renders a message with an appropriate icon and color based on the type.
 * Use this for standalone error/warning messages outside of Formik context.
 *
 * Exported as `ErrorTextLayout` for direct usage.
 *
 * @param children - The error or warning message text
 * @param type - The message type: "error" (red) or "warning" (yellow). Defaults to "error"
 *
 * @example
 * ```tsx
 * import { ErrorTextLayout } from "@/layouts/input-layouts";
 *
 * // Error message
 * <ErrorTextLayout type="error">
 *   This field is required
 * </ErrorTextLayout>
 *
 * // Warning message
 * <ErrorTextLayout type="warning">
 *   This action cannot be undone
 * </ErrorTextLayout>
 * ```
 */
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
