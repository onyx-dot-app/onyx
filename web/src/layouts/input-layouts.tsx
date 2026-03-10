"use client";

import Text from "@/refresh-components/texts/Text";
import { SvgXOctagon, SvgAlertCircle } from "@opal/icons";
import { useField, useFormikContext } from "formik";
import { Section } from "@/layouts/general-layouts";
import { Content } from "@opal/layouts";
import Label from "@/refresh-components/form/Label";

interface OrientationLayoutProps {
  name?: string;
  disabled?: boolean;
  nonInteractive?: boolean;
  children?: React.ReactNode;
  title: string;
  description?: string;
  optional?: boolean;
  sizePreset?: "main-content" | "main-ui";
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
  name,
  disabled,
  nonInteractive,
  children,
  subDescription,
  title,
  description,
  optional,
  sizePreset = "main-content",
}: VerticalLayoutProps) {
  const content = (
    <Section gap={0.25} alignItems="start">
      <Content
        title={title}
        description={description}
        optional={optional}
        sizePreset={sizePreset}
        variant="section"
      />
      {children}
      {name && <ErrorLayout name={name} />}
      {subDescription && (
        <Text secondaryBody text03>
          {subDescription}
        </Text>
      )}
    </Section>
  );

  if (nonInteractive) return content;
  return (
    <Label name={name} disabled={disabled}>
      {content}
    </Label>
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
  /** Align input to the center (middle) of the label/description */
  center?: boolean;
}
function HorizontalInputLayout({
  name,
  disabled,
  nonInteractive,
  children,
  center,
  title,
  description,
  optional,
  sizePreset = "main-content",
}: HorizontalLayoutProps) {
  const content = (
    <Section gap={0.25} alignItems="start">
      <Section
        flexDirection="row"
        justifyContent="between"
        alignItems={center ? "center" : "start"}
      >
        <div className="flex flex-col flex-1 self-stretch">
          <Content
            title={title}
            description={description}
            optional={optional}
            sizePreset={sizePreset}
            variant="section"
          />
        </div>
        <div className="flex flex-col items-end">{children}</div>
      </Section>
      {name && <ErrorLayout name={name} />}
    </Section>
  );

  if (nonInteractive) return content;
  return (
    <Label name={name} disabled={disabled}>
      {content}
    </Label>
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
interface ErrorLayoutProps {
  name: string;
}
function ErrorLayout({ name }: ErrorLayoutProps) {
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
  children?: React.ReactNode;
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
  ErrorLayout as Error,
  ErrorTextLayout,
};
