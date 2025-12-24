"use client";

import { cn } from "@/lib/utils";
import Text from "@/refresh-components/texts/Text";
import { SvgXOctagon } from "@opal/icons";
import { useField } from "formik";

export interface VerticalLayoutProps extends FieldLabelLayoutProps {
  name: string;
  children?: React.ReactNode;
}

/**
 * VerticalLayout - A layout component for form fields with vertical label arrangement
 *
 * Use this layout when you want the label, input, and error message stacked vertically.
 * Common for most form inputs where the label appears above the input field.
 *
 * @example
 * ```tsx
 * <VerticalLayout
 *   name="email"
 *   label="Email Address"
 *   description="We'll never share your email"
 *   optional
 * >
 *   <InputTypeIn name="email" type="email" />
 * </VerticalLayout>
 * ```
 */
function VerticalInputLayout({
  children,

  name,
  ...fieldLabelProps
}: VerticalLayoutProps) {
  return (
    <div className="flex flex-col w-full h-full gap-1">
      <LabelLayout name={name} {...fieldLabelProps} />
      {children}
      <ErrorLayout name={name} />
    </div>
  );
}

export interface HorizontalLayoutProps extends FieldLabelLayoutProps {
  name: string;
  children?: React.ReactNode;
  className?: string;
}

/**
 * HorizontalLayout - A layout component for form fields with horizontal label arrangement
 *
 * Use this layout when you want the label on the left and the input control on the right.
 * Commonly used for toggles, switches, and checkboxes where the label and control
 * should be side-by-side.
 *
 * @example
 * ```tsx
 * <HorizontalLayout
 *   name="notifications"
 *   label="Enable Notifications"
 *   description="Receive updates about your account"
 * >
 *   <Switch name="notifications" />
 * </HorizontalLayout>
 * ```
 */
function HorizontalInputLayout({
  children,

  name,
  className,
  ...fieldLabelProps
}: HorizontalLayoutProps) {
  return (
    <div className="flex flex-col gap-1 h-full w-full">
      <label
        htmlFor={name}
        className={cn(
          "flex flex-row justify-between gap-4 cursor-pointer",
          fieldLabelProps.description ? "items-start" : "items-center"
        )}
      >
        <div className="min-w-[70%]">
          <LabelLayout
            className={cn("cursor-pointer", className)}
            {...fieldLabelProps}
          />
        </div>
        {children}
      </label>
      <ErrorLayout name={name} />
    </div>
  );
}

export interface FieldLabelLayoutProps {
  name?: string;
  label?: string;
  optional?: boolean;
  description?: string;
  className?: string;
}

/**
 * FieldLabelLayout - A reusable label component for form fields
 *
 * Renders a semantic label element with optional description and "Optional" indicator.
 * If no `name` prop is provided, renders a `div` instead of a `label` element.
 *
 * @param name - The field name to associate the label with (renders as `<label>` if provided)
 * @param label - The main label text
 * @param optional - Whether to show "(Optional)" indicator
 * @param description - Additional helper text shown below the label
 * @param className - Additional CSS classes
 *
 * @example
 * ```tsx
 * <FieldLabelLayout
 *   name="username"
 *   label="Username"
 *   description="Choose a unique username"
 *   optional
 * />
 * ```
 */
function LabelLayout({
  name,
  label,
  optional,
  description,
  className,
}: FieldLabelLayoutProps) {
  const finalClassName = cn("flex flex-col w-full", className);
  const content = label ? (
    <>
      <div className="flex flex-row gap-1.5">
        <Text mainContentEmphasis text04>
          {label}
        </Text>
        {optional && (
          <Text text03 mainContentMuted as="span">
            {" (Optional)"}
          </Text>
        )}
      </div>
      {description && (
        <Text secondaryBody text03>
          {description}
        </Text>
      )}
    </>
  ) : null;

  return name ? (
    <label htmlFor={name} className={finalClassName}>
      {content}
    </label>
  ) : (
    <div className={finalClassName}>{content}</div>
  );
}

interface FieldErrorLayoutProps {
  name: string;
}

/**
 * FieldErrorLayout - Displays Formik field validation errors
 *
 * Automatically shows error messages from Formik's validation state.
 * Only displays when the field has been touched and has an error.
 *
 * @param name - The Formik field name to display errors for
 *
 * @example
 * ```tsx
 * <InputTypeIn name="email" />
 * <FieldErrorLayout name="email" />
 * ```
 *
 * @remarks
 * This component uses Formik's `useField` hook internally and requires
 * the component to be rendered within a Formik context.
 */
function ErrorLayout({ name }: FieldErrorLayoutProps) {
  const [, meta] = useField(name);
  const hasError = meta.touched && meta.error;

  if (!hasError) return null;

  return (
    <div className="flex flex-row items-center gap-1 px-1">
      <SvgXOctagon className="w-[0.75rem] h-[0.75rem] stroke-status-error-05" />
      <Text secondaryBody className="text-status-error-05" role="alert">
        {meta.error}
      </Text>
    </div>
  );
}

export {
  VerticalInputLayout as Vertical,
  HorizontalInputLayout as Horizontal,
  LabelLayout as Label,
  ErrorLayout as Error,
};
