import { ErrorMessage, Field, useField } from "formik";

import {
  ExplanationText,
  Label,
  ManualErrorMessage,
  SubLabel,
  ToolTipDetails,
} from "@/components/Field";

// Specifically for text
export function AdminTextField({
  name,
  label,
  subtext,
  placeholder,
  onChange,
  description,
  type = "text",
  isTextArea = false,
  disabled = false,
  autoCompleteDisabled = true,
  error,
  defaultHeight,
  isCode = false,
  fontSize,
  hideError,
  tooltip,
  explanationText,
  explanationLink,
  small,
  noPadding,
  removeLabel,
  optional,
}: {
  description?: string;
  name: string;
  removeLabel?: boolean;
  label: string;
  subtext?: string | JSX.Element;
  placeholder?: string;
  onChange?: (e: React.ChangeEvent<HTMLInputElement>) => void;
  type?: string;
  isTextArea?: boolean;
  disabled?: boolean;
  noPadding?: boolean;
  autoCompleteDisabled?: boolean;
  error?: string;
  defaultHeight?: string;
  isCode?: boolean;
  fontSize?: "text-sm" | "text-base" | "text-lg";
  hideError?: boolean;
  tooltip?: string;
  explanationText?: string;
  explanationLink?: string;
  small?: boolean;
  optional?: boolean;
}) {
  let heightString = defaultHeight || "";
  if (isTextArea && !heightString) {
    heightString = "h-28";
  }

  return (
    <div className={`${!noPadding && "mb-6"}`}>
      <div className="flex gap-x-2 items-center">
        {!removeLabel && (
          <label
            htmlFor={name}
            className="block text-sm font-medium text-text-700"
          >
            {label}
            {optional && <span className="text-text-500 ml-1">(optional)</span>}
          </label>
        )}
        {tooltip && <ToolTipDetails>{tooltip}</ToolTipDetails>}
        {error ? (
          <ManualErrorMessage>{error}</ManualErrorMessage>
        ) : (
          !hideError && (
            <ErrorMessage
              name={name}
              component="div"
              className="text-error my-auto text-sm"
            />
          )
        )}
      </div>
      {description && <CredentialSubText>{description}</CredentialSubText>}

      {subtext && <SubLabel>{subtext}</SubLabel>}

      <Field
        as={type != "number" && isTextArea ? "textarea" : "input"}
        type={type}
        name={name}
        id={name}
        className={`
          ${small && "text-sm"}
          border 
          border-border 
          rounded 
          w-full 
          bg-input
          py-2 
          px-3 
          mt-1
          ${heightString}
          ${fontSize}
          ${isCode ? " font-mono" : ""}
          `}
        disabled={disabled}
        placeholder={placeholder}
        autoComplete={autoCompleteDisabled ? "off" : undefined}
        {...(onChange ? { onChange } : {})}
      />

      {explanationText && (
        <ExplanationText link={explanationLink} text={explanationText} />
      )}
    </div>
  );
}

interface BooleanFormFieldProps {
  name: string;
  label: string;
  checked: boolean;
  subtext?: string | JSX.Element;
  small?: boolean;
  alignTop?: boolean;
  noLabel?: boolean;
  disabled?: boolean;
  onChange?: (e: React.ChangeEvent<HTMLInputElement>) => void;
}

export const AdminBooleanFormField = ({
  name,
  label,
  subtext,
  noLabel,
  small,
  checked,
  alignTop,
  disabled = false,
  onChange,
}: BooleanFormFieldProps) => {
  const [field, meta, helpers] = useField(name);

  return (
    <div>
      <label className={`flex text-sm`}>
        <input
          type="checkbox"
          {...field}
          checked={Boolean(field.value)}
          disabled={disabled}
          onChange={(e) => {
            helpers.setValue(e.target.checked);
          }}
          className={`mr-3 bg-white px-5 w-3.5 h-3.5 ${
            alignTop ? "mt-1" : "my-auto"
          }`}
        />
        {!noLabel && (
          <div>
            <span
              className={`block font-medium text-text-700 dark:text-neutral-100 ${
                small ? "text-sm" : "text-base"
              } cursor-pointer`}
            >
              {label}
            </span>
            {subtext && <SubLabel>{subtext}</SubLabel>}
          </div>
        )}
      </label>
    </div>
  );
};

export default function CredentialSubText({
  children,
}: {
  children: JSX.Element | string;
}) {
  return (
    <p className="text-sm mb-2 whitespace-break-spaces text-text-500">
      {children}
    </p>
  );
}
