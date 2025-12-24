import { cn } from "@/lib/utils";
import Text from "@/refresh-components/texts/Text";
import { SvgXOctagon } from "@opal/icons";
import { useField } from "formik";

export interface LabelWrapperProps extends FieldLabelProps {
  name: string;
  children?: React.ReactNode;
}

export function VerticalLabelWrapper({
  children,

  name,
  ...fieldLabelProps
}: LabelWrapperProps) {
  return (
    <div className="flex flex-col w-full h-full gap-1">
      <FieldLabel name={name} {...fieldLabelProps} />
      {children}
      <FieldError name={name} />
    </div>
  );
}

export function HorizontalLabelWrapper({
  children,

  name,
  className,
  ...fieldLabelProps
}: LabelWrapperProps) {
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
          <FieldLabel
            className={cn("cursor-pointer", className)}
            {...fieldLabelProps}
          />
        </div>
        {children}
      </label>
      <FieldError name={name} />
    </div>
  );
}

export interface FieldLabelProps {
  name?: string;
  label?: string;
  optional?: boolean;
  description?: string;
  className?: string;
}

// If you do not pass anything to the `name` prop, this renders a NON-`label` tag (i.e., a simple `div`).
// Use it if you want the UI rendering without the HTML labelling features.
export function FieldLabel({
  name,
  label,
  optional,
  description,
  className,
}: FieldLabelProps) {
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

interface FieldErrorProps {
  name: string;
}

function FieldError({ name }: FieldErrorProps) {
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
