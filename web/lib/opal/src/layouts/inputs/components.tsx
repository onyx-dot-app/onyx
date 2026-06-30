"use client";

import "@opal/layouts/inputs/styles.css";
import { useContext } from "react";
import { useField, FormikContext } from "formik";
import type {
  ColorTypes,
  IconFunctionComponent,
  RichStr,
  WithoutStyles,
} from "@opal/types";
import { Text, Divider, type TagProps } from "@opal/components";
import { SvgXOctagon, SvgAlertCircle } from "@opal/icons";
import { Content, ContentAction, Section } from "@opal/layouts";

// ---------------------------------------------------------------------------
// Label
// ---------------------------------------------------------------------------

interface LabelProps extends WithoutStyles<
  Omit<React.LabelHTMLAttributes<HTMLLabelElement>, "htmlFor">
> {
  /** Sets `htmlFor` on the `<label>` to associate it with a form element by id. */
  label?: string;
  /** Switches cursor from `pointer` to `not-allowed`. */
  disabled?: boolean;
  ref?: React.Ref<HTMLLabelElement>;
}

function Label({ label, disabled, ref, ...props }: LabelProps) {
  return (
    <label
      ref={ref}
      className="opal-input-label"
      htmlFor={label}
      data-disabled={disabled || undefined}
      {...props}
    />
  );
}

// ---------------------------------------------------------------------------
// Shared types
// ---------------------------------------------------------------------------

interface InputLayoutProps {
  /**
   * Controls the `<label>` wrapper and Formik error display.
   *
   * - `false` (default) — no `<label>`, no error display.
   * - `true` — implicit `<label>` (no `htmlFor`), no error display.
   *   The browser forwards clicks to the first labelable descendant.
   * - `string` — `<label htmlFor={string}>`, plus Formik error display
   *   for the named field.
   */
  withLabel?: boolean | string;

  disabled?: boolean;
  /** Ref forwarded to the inner content `Section`. */
  ref?: React.Ref<HTMLDivElement>;
  children?: React.ReactNode;
  title: string | RichStr;
  /** Tag rendered inline beside the title (passed through to Content). */
  tag?: TagProps;
  description?: string | RichStr;
  suffix?: "optional" | (string & {});
}

// ---------------------------------------------------------------------------
// Vertical
// ---------------------------------------------------------------------------

interface VerticalProps extends InputLayoutProps {
  subDescription?: string | RichStr;
}

function Vertical({
  withLabel: withLabelProp = false,
  disabled,
  ref,
  children,
  subDescription,
  title,
  tag,
  description,
  suffix,
}: VerticalProps) {
  const fieldName =
    typeof withLabelProp === "string" ? withLabelProp : undefined;

  const content = (
    <Section ref={ref} gap={0.25} alignItems="start">
      <Content
        title={title}
        description={description}
        suffix={suffix}
        tag={tag}
        sizePreset="main-ui"
        variant="section"
      />
      {children}
      {fieldName && <FormikInputError name={fieldName} />}
      {subDescription && (
        <Text font="secondary-body" color="text-03">
          {subDescription}
        </Text>
      )}
    </Section>
  );

  if (!withLabelProp) return content;
  return (
    <Label label={fieldName} disabled={disabled}>
      {content}
    </Label>
  );
}

// ---------------------------------------------------------------------------
// Horizontal
// ---------------------------------------------------------------------------

interface HorizontalProps extends InputLayoutProps {
  /** Align input to the center (middle) of the label/description. */
  center?: boolean;
  /** Optional icon rendered beside the title. */
  icon?: IconFunctionComponent;
  /**
   * When true, the control stacks between the title and the description on
   * narrow viewports (and floats back to the right at the `sm` breakpoint),
   * instead of always sitting to the right. Best for text inputs; avoid for
   * compact controls like toggles/switches.
   */
  responsive?: boolean;
}

function Horizontal({
  withLabel: withLabelProp = false,
  disabled,
  ref,
  children,
  center,
  icon,
  title,
  tag,
  description,
  suffix,
  responsive,
}: HorizontalProps) {
  const fieldName =
    typeof withLabelProp === "string" ? withLabelProp : undefined;

  const content = (
    <Section ref={ref} gap={0.25} alignItems="start">
      <ContentAction
        icon={icon}
        title={title}
        description={description}
        suffix={suffix}
        tag={tag}
        sizePreset="main-ui"
        variant="section"
        width="full"
        padding="fit"
        center={center}
        responsive={responsive}
        rightChildren={children}
      />
      {fieldName && <FormikInputError name={fieldName} />}
    </Section>
  );

  if (!withLabelProp) return content;
  return (
    <Label label={fieldName} disabled={disabled}>
      {content}
    </Label>
  );
}

// ---------------------------------------------------------------------------
// FormikInputError
// ---------------------------------------------------------------------------

interface FormikInputErrorProps {
  name: string;
}

/**
 * Displays Formik field validation errors and warnings.
 * Safely returns `null` when rendered outside a Formik context.
 */
function FormikInputError({ name }: FormikInputErrorProps) {
  const formik = useContext(FormikContext);
  if (!formik) return null;
  return <FormikInputErrorInner name={name} />;
}

/** Inner component that calls Formik hooks (only rendered inside a Formik context). */
function FormikInputErrorInner({ name }: FormikInputErrorProps) {
  const [, meta] = useField(name);
  const { status } = useContext(FormikContext)!;
  const warning = status?.warnings?.[name];
  if (warning && typeof warning !== "string")
    throw new Error("The warning that is set must ALWAYS be a string");

  const hasError = meta.touched && meta.error;
  const hasWarning = warning;

  if (hasError)
    return <InputErrorText type="error">{meta.error!}</InputErrorText>;
  else if (hasWarning)
    return <InputErrorText type="warning">{warning}</InputErrorText>;
  else return null;
}

// ---------------------------------------------------------------------------
// InputErrorText
// ---------------------------------------------------------------------------

type InputErrorType = "error" | "warning";

interface InputErrorTextProps {
  children: string | RichStr;
  type?: InputErrorType;
  ref?: React.Ref<HTMLDivElement>;
}

function InputErrorText({
  children,
  type = "error",
  ref,
}: InputErrorTextProps) {
  const Icon = type === "error" ? SvgXOctagon : SvgAlertCircle;
  const color: ColorTypes = type === "error" ? "danger" : "warning";

  return (
    <div ref={ref} className="px-1">
      <Content
        sizePreset="secondary"
        variant="body"
        icon={Icon}
        title={children}
        color={color}
        role="alert"
      />
    </div>
  );
}

// ---------------------------------------------------------------------------
// InputDivider
// ---------------------------------------------------------------------------

function InputDivider() {
  return <Divider paddingParallel="sm" paddingPerpendicular="sm" />;
}

// ---------------------------------------------------------------------------
// InputPadder
// ---------------------------------------------------------------------------

type InputPadderProps = WithoutStyles<React.HTMLAttributes<HTMLDivElement>> & {
  ref?: React.Ref<HTMLDivElement>;
};

function InputPadder({ ref, ...props }: InputPadderProps) {
  return <div ref={ref} {...props} className="p-2 w-full" />;
}

// ---------------------------------------------------------------------------
// Exports
// ---------------------------------------------------------------------------

export {
  Label,
  type LabelProps,
  type VerticalProps,
  Vertical,
  type HorizontalProps,
  Horizontal,
  FormikInputError,
  type FormikInputErrorProps,
  type InputErrorType,
  type InputErrorTextProps,
  InputErrorText,
  InputDivider,
  InputPadder,
  type InputPadderProps,
};
