"use client";

import { cn } from "@/lib/utils";
import Text from "@/refresh-components/texts/Text";
import { SvgXOctagon, SvgAlertCircle } from "@opal/icons";
import { useField, useFormikContext } from "formik";

export interface VandHLayoutProps extends LabelLayoutProps {
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
function VerticalInputLayout({
  children,

  name,
  ...fieldLabelProps
}: VandHLayoutProps) {
  return (
    <div className="flex flex-col w-full h-full gap-1">
      <LabelLayout name={name} {...fieldLabelProps} />
      {children}
      {name && <ErrorLayout name={name} />}
    </div>
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
 * <Horizontal
 *   name="notifications"
 *   label="Enable Notifications"
 *   description="Receive updates about your account"
 * >
 *   <Switch name="notifications" />
 * </Horizontal>
 * ```
 */
function HorizontalInputLayout({
  children,

  name,
  ...fieldLabelProps
}: VandHLayoutProps) {
  return (
    <div className="flex flex-col gap-1 h-full w-full">
      <label
        htmlFor={name}
        className={cn(
          "flex flex-row justify-between gap-4 cursor-pointer",
          fieldLabelProps.description ? "items-start" : "items-center"
        )}
      >
        <div className="w-[70%]">
          <LabelLayout {...fieldLabelProps} />
        </div>
        <div className="flex flex-col items-end min-w-[14rem]">{children}</div>
      </label>
      {name && <ErrorLayout name={name} />}
    </div>
  );
}

export interface LabelLayoutProps {
  name?: string;
  label?: string;
  optional?: boolean;
  description?: string;
  className?: string;
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
function LabelLayout({ name, label, optional, description }: LabelLayoutProps) {
  const className = "flex flex-col w-full";
  const content = label ? (
    <>
      <div className="flex flex-row gap-1.5">
        <Text as="p" mainContentEmphasis text04>
          {label}
        </Text>
        {optional && (
          <Text text03 mainContentMuted as="span">
            {" (Optional)"}
          </Text>
        )}
      </div>
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

interface FieldErrorLayoutProps {
  name: string;
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
function ErrorLayout({ name }: FieldErrorLayoutProps) {
  const [, meta] = useField(name);
  const { status } = useFormikContext();
  const warning = status?.warnings?.[name];
  if (warning && typeof warning !== "string")
    throw new Error("The warning that is set must ALWAYS be a string");

  const hasError = meta.touched && meta.error;
  const hasWarning = warning; // Don't require touched for warnings

  if (!hasError && !hasWarning) return null;

  return (
    <div className="flex flex-row items-center gap-1 px-1">
      {hasError && (
        <>
          <SvgXOctagon size={12} className="stroke-status-error-05" />
          <Text
            as="p"
            secondaryBody
            className="text-status-error-05"
            role="alert"
          >
            {meta.error}
          </Text>
        </>
      )}

      {hasWarning && (
        <>
          <SvgAlertCircle size={12} className="stroke-status-warning-05" />
          <Text
            as="p"
            secondaryBody
            className="text-status-warning-05"
            role="alert"
          >
            {warning}
          </Text>
        </>
      )}
    </div>
  );
}

export {
  VerticalInputLayout as Vertical,
  HorizontalInputLayout as Horizontal,
  LabelLayout as Label,
  ErrorLayout as Error,
};
