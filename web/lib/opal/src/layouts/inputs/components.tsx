"use client";

import "@opal/layouts/inputs/styles.css";
import { useContext, useState } from "react";
import { useField, FormikContext } from "formik";
import type {
  IconFunctionComponent,
  RichStr,
  WithoutStyles,
} from "@opal/types";
import type { ContentColor } from "@opal/layouts/content/components";
import { Text, Divider, type BadgeProps } from "@opal/components";
import { isRichStr } from "@opal/components/text/InlineMarkdown";
import { SvgXOctagon, SvgAlertCircle } from "@opal/icons";
import { Content, ContentAction, Section } from "@opal/layouts";
import { InputRowProvider } from "@opal/components/inputs/disabled";

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
// InputRow
// ---------------------------------------------------------------------------

interface InputRowProps {
  withLabel: boolean;
  fieldName?: string;
  disabled: boolean;
  disabledTooltip?: string | RichStr;
  hovered: boolean;
  /** The layout's content `Section`. */
  children: React.ReactElement;
}

/**
 * A layout's outer frame: the row context for the input inside, and the
 * `<label>` when `withLabel`.
 */
function InputRow({
  withLabel,
  fieldName,
  disabled,
  disabledTooltip,
  hovered,
  children,
}: InputRowProps) {
  return (
    <InputRowProvider
      disabled={disabled}
      disabledTooltip={disabledTooltip}
      hovered={hovered}
    >
      {withLabel ? (
        <Label label={fieldName} disabled={disabled}>
          {children}
        </Label>
      ) : (
        children
      )}
    </InputRowProvider>
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

  /**
   * Disables the row: the input inside it is disabled too, and the row's text
   * dims.
   */
  disabled?: boolean;
  /**
   * Why the row is disabled. While `disabled`, the input inside shows it as
   * its tooltip, in place of its own `tooltip`.
   */
  disabledTooltip?: string | RichStr;
  /** Ref forwarded to the inner content `Section`. */
  ref?: React.Ref<HTMLDivElement>;
  children?: React.ReactNode;
  title: string | RichStr;
  /** Badge rendered inline beside the title (passed through to Content). */
  tag?: BadgeProps;
  description?: string | RichStr;
  suffix?: "optional" | (string & {});
  /**
   * A message under the input, for inputs outside Formik: an `error` (red)
   * or a `warning` (amber). An `error` wins over a `warning`, and either
   * replaces the Formik message for `withLabel`'s field.
   */
  error?: string | RichStr;
  warning?: string | RichStr;
}

interface InputMessageProps {
  error?: string | RichStr;
  warning?: string | RichStr;
  fieldName?: string;
}

/** The message under an input: an explicit error or warning, else Formik's. */
function InputMessage({ error, warning, fieldName }: InputMessageProps) {
  if (error) return <InputErrorText type="error">{error}</InputErrorText>;
  if (warning) return <InputErrorText type="warning">{warning}</InputErrorText>;
  return fieldName ? <FormikInputError name={fieldName} /> : null;
}

// ---------------------------------------------------------------------------
// Vertical
// ---------------------------------------------------------------------------

interface VerticalProps extends InputLayoutProps {
  subDescription?: string | RichStr;
  /**
   * Content at the right of the title row. Text or markdown renders as
   * secondary text; any other node renders as given, e.g. a button.
   */
  rightChildren?: string | RichStr | React.ReactNode;
}

function Vertical({
  withLabel: withLabelProp = false,
  disabled = false,
  disabledTooltip,
  ref,
  children,
  subDescription,
  rightChildren,
  title,
  tag,
  description,
  suffix,
  error,
  warning,
}: VerticalProps) {
  const [hovered, setHovered] = useState(false);
  const fieldName =
    typeof withLabelProp === "string" ? withLabelProp : undefined;

  const titleRow = rightChildren ? (
    <ContentAction
      font="main-ui-action"
      title={title}
      description={description}
      suffix={suffix}
      badge={tag}
      width="full"
      padding={0}
      rightChildren={
        typeof rightChildren === "string" || isRichStr(rightChildren) ? (
          <Text font="secondary-body" color="text-03" as="p">
            {rightChildren}
          </Text>
        ) : (
          rightChildren
        )
      }
      center
    />
  ) : (
    <Content
      font="main-ui-action"
      title={title}
      description={description}
      suffix={suffix}
      badge={tag}
    />
  );

  const content = (
    <Section
      ref={ref}
      gap={1}
      alignItems="start"
      className="opal-input-layout"
      data-disabled={disabled || undefined}
      // The row's hover opens the input's tooltip (`disabledTooltip`).
      onPointerEnter={() => setHovered(true)}
      onPointerLeave={() => setHovered(false)}
    >
      {titleRow}
      {children}
      <InputMessage error={error} warning={warning} fieldName={fieldName} />
      {subDescription && (
        <div className="opal-input-sub-description">
          <Text font="secondary-body" color="text-03">
            {subDescription}
          </Text>
        </div>
      )}
    </Section>
  );

  return (
    <InputRow
      withLabel={Boolean(withLabelProp)}
      fieldName={fieldName}
      disabled={disabled}
      disabledTooltip={disabledTooltip}
      hovered={hovered}
    >
      {content}
    </InputRow>
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
  /**
   * When true, the control grows to fill the row (capped at the form input
   * column max) instead of hugging its content. Use for full-width inputs like
   * selects/text fields; avoid for compact controls like toggles/switches.
   */
  fillInput?: boolean;
}

function Horizontal({
  withLabel: withLabelProp = false,
  disabled = false,
  disabledTooltip,
  ref,
  children,
  center,
  icon,
  title,
  tag,
  description,
  suffix,
  responsive,
  fillInput,
  error,
  warning,
}: HorizontalProps) {
  const [hovered, setHovered] = useState(false);
  const fieldName =
    typeof withLabelProp === "string" ? withLabelProp : undefined;

  const content = (
    <Section
      ref={ref}
      gap={1}
      alignItems="start"
      className="opal-input-layout"
      data-disabled={disabled || undefined}
      // The row's hover opens the input's tooltip (`disabledTooltip`).
      onPointerEnter={() => setHovered(true)}
      onPointerLeave={() => setHovered(false)}
    >
      <ContentAction
        font="main-ui-action"
        icon={icon}
        title={title}
        description={description}
        suffix={suffix}
        badge={tag}
        width="full"
        padding={0}
        center={center}
        responsive={responsive}
        fillRight={fillInput}
        rightChildren={children}
      />
      <InputMessage error={error} warning={warning} fieldName={fieldName} />
    </Section>
  );

  return (
    <InputRow
      withLabel={Boolean(withLabelProp)}
      fieldName={fieldName}
      disabled={disabled}
      disabledTooltip={disabledTooltip}
      hovered={hovered}
    >
      {content}
    </InputRow>
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
  const color: ContentColor = type === "error" ? "error" : "warning";

  return (
    <div ref={ref} className="px-1">
      <Content
        font="secondary-body"
        icon={Icon}
        title={children}
        color={color}
        titleColor="text-03"
        role="alert"
      />
    </div>
  );
}

// ---------------------------------------------------------------------------
// InputDivider
// ---------------------------------------------------------------------------

function InputDivider() {
  return <Divider paddingParallel={2} paddingPerpendicular={2} />;
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
