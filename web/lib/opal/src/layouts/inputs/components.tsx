"use client";

import "@opal/layouts/inputs/styles.css";
import type { RichStr, WithoutStyles } from "@opal/types";
import type { TagProps } from "@opal/components/tag/components";
import { Text, Divider } from "@opal/components";
import { SvgXOctagon, SvgAlertCircle } from "@opal/icons";
import { useField, useFormikContext } from "formik";
import { Section } from "@/layouts/general-layouts";
import { Content } from "@opal/layouts";

// ---------------------------------------------------------------------------
// Label
// ---------------------------------------------------------------------------

interface LabelProps
  extends WithoutStyles<
    Omit<React.LabelHTMLAttributes<HTMLLabelElement>, "htmlFor">
  > {
  /** The name/id of the form element this label is associated with. */
  name?: string;
  /** Whether the associated input is disabled. */
  disabled?: boolean;
  ref?: React.Ref<HTMLLabelElement>;
}

function Label({ name, disabled, ref, ...props }: LabelProps) {
  return (
    <label
      ref={ref}
      className="opal-input-label"
      htmlFor={name}
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
  children?: React.ReactNode;
  title: string | RichStr;
  /** Tag rendered inline beside the title (passed through to Content). */
  tag?: TagProps;
  description?: string | RichStr;
  suffix?: "optional" | (string & {});
  sizePreset?: "main-content" | "main-ui";
}

// ---------------------------------------------------------------------------
// Vertical
// ---------------------------------------------------------------------------

export interface VerticalProps extends InputLayoutProps {
  subDescription?: string | RichStr;
}

function Vertical({
  withLabel: withLabelProp = false,
  disabled,
  children,
  subDescription,
  title,
  tag,
  description,
  suffix,
  sizePreset = "main-content",
}: VerticalProps) {
  const fieldName =
    typeof withLabelProp === "string" ? withLabelProp : undefined;

  const content = (
    <Section gap={0.25} alignItems="start">
      <Content
        title={title}
        description={description}
        suffix={suffix}
        tag={tag}
        sizePreset={sizePreset}
        variant="section"
      />
      {children}
      {fieldName && <InputError name={fieldName} />}
      {subDescription && (
        <Text font="secondary-body" color="text-03">
          {subDescription}
        </Text>
      )}
    </Section>
  );

  if (!withLabelProp) return content;
  return (
    <Label name={fieldName} disabled={disabled}>
      {content}
    </Label>
  );
}

// ---------------------------------------------------------------------------
// Horizontal
// ---------------------------------------------------------------------------

export interface HorizontalProps extends InputLayoutProps {
  /** Align input to the center (middle) of the label/description. */
  center?: boolean;
}

function Horizontal({
  withLabel: withLabelProp = false,
  disabled,
  children,
  center,
  title,
  tag,
  description,
  suffix,
  sizePreset = "main-content",
}: HorizontalProps) {
  const fieldName =
    typeof withLabelProp === "string" ? withLabelProp : undefined;

  const content = (
    <Section gap={0.25} alignItems="start">
      <Section
        flexDirection="row"
        justifyContent="between"
        alignItems={center ? "center" : "start"}
      >
        <div className="flex flex-col flex-1 min-w-0 self-stretch">
          <Content
            title={title}
            description={description}
            suffix={suffix}
            tag={tag}
            sizePreset={sizePreset}
            variant="section"
            widthVariant="full"
          />
        </div>
        <div className="flex flex-col items-end">{children}</div>
      </Section>
      {fieldName && <InputError name={fieldName} />}
    </Section>
  );

  if (!withLabelProp) return content;
  return (
    <Label name={fieldName} disabled={disabled}>
      {content}
    </Label>
  );
}

// ---------------------------------------------------------------------------
// InputError
// ---------------------------------------------------------------------------

interface InputErrorProps {
  name: string;
}

function InputError({ name }: InputErrorProps) {
  const [, meta] = useField(name);
  const { status } = useFormikContext();
  const warning = status?.warnings?.[name];
  if (warning && typeof warning !== "string")
    throw new Error("The warning that is set must ALWAYS be a string");

  const hasError = meta.touched && meta.error;
  const hasWarning = warning;

  if (hasError)
    return <InputErrorText type="error">{meta.error}</InputErrorText>;
  else if (hasWarning)
    return <InputErrorText type="warning">{warning}</InputErrorText>;
  else return null;
}

// ---------------------------------------------------------------------------
// InputErrorText
// ---------------------------------------------------------------------------

export type InputErrorType = "error" | "warning";

interface InputErrorTextProps {
  children?: React.ReactNode;
  type?: InputErrorType;
}

function InputErrorText({ children, type = "error" }: InputErrorTextProps) {
  const Icon = type === "error" ? SvgXOctagon : SvgAlertCircle;
  const colorClass =
    type === "error" ? "text-status-error-05" : "text-status-warning-05";
  const strokeClass =
    type === "error" ? "stroke-status-error-05" : "stroke-status-warning-05";

  return (
    <div className="px-1">
      {/* TODO(@raunakab): update this with `Content` when it supports custom colours */}
      <Section flexDirection="row" justifyContent="start" gap={0.25}>
        <Icon size={12} className={strokeClass} />
        <span className={colorClass} role="alert">
          {typeof children === "string" ? (
            <Text font="secondary-body" color="inherit">
              {children}
            </Text>
          ) : (
            children
          )}
        </span>
      </Section>
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

type InputPadderProps = WithoutStyles<React.HTMLAttributes<HTMLDivElement>>;

function InputPadder(props: InputPadderProps) {
  return <div {...props} className="p-2 w-full" />;
}

// ---------------------------------------------------------------------------
// Exports
// ---------------------------------------------------------------------------

export {
  Label,
  type LabelProps,
  Vertical,
  Horizontal,
  InputError,
  type InputErrorProps,
  InputErrorText,
  type InputErrorTextProps,
  InputDivider,
  InputPadder,
  type InputPadderProps,
};
