"use client";
import {
  ArrayHelpers,
  ErrorMessage,
  Field,
  FieldArray,
  useField,
  useFormikContext,
} from "formik";
import * as Yup from "yup";
import { FormBodyBuilder } from "./types";
import { StringOrNumberOption } from "@/components/Dropdown";
import {
  Select,
  SelectItem,
  SelectContent,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { FiInfo, FiPlus, FiX } from "react-icons/fi";
import {
  TooltipProvider,
  Tooltip,
  TooltipContent,
  TooltipTrigger,
} from "@/components/ui/tooltip";
import ReactMarkdown from "react-markdown";
import { FaMarkdown } from "react-icons/fa";
import { useState, useCallback, useEffect } from "react";
import remarkGfm from "remark-gfm";
import { Button } from "@/components/ui/button";
import Link from "next/link";
import { CheckboxField } from "@/components/ui/checkbox";
import { CheckedState } from "@radix-ui/react-checkbox";

import { transformLinkUri } from "@/lib/utils";
import FileInput from "@/app/admin/connectors/[connector]/pages/ConnectorInput/FileInput";

export function SectionHeader({
  children,
}: {
  children: string | JSX.Element;
}) {
  return <div className="mb-4 font-bold text-lg">{children}</div>;
}

export function Label({
  children,
  small,
  className,
}: {
  children: string | JSX.Element;
  small?: boolean;
  className?: string;
}) {
  return (
    <label
      className={`block font-medium text-text-700 dark:text-neutral-100 ${className} ${
        small ? "text-sm" : "text-base"
      }`}
    >
      {children}
    </label>
  );
}

export function LabelWithTooltip({
  children,
  tooltip,
}: {
  children: string | JSX.Element;
  tooltip: string;
}) {
  return (
    <div className="flex items-center gap-x-2">
      <Label>{children}</Label>
      <ToolTipDetails>{tooltip}</ToolTipDetails>
    </div>
  );
}

export function SubLabel({ children }: { children: string | JSX.Element }) {
  return (
    <div className="text-sm text-neutral-600 dark:text-neutral-300 mb-2">
      {children}
    </div>
  );
}

export function ManualErrorMessage({ children }: { children: string }) {
  return <div className="text-error text-sm">{children}</div>;
}

export function ExplanationText({
  text,
  link,
}: {
  text: string;
  link?: string;
}) {
  return link ? (
    <a
      className="underline text-text-500 cursor-pointer text-xs font-medium"
      target="_blank"
      href={link}
    >
      {text}
    </a>
  ) : (
    <div className="text-sm font-semibold">{text}</div>
  );
}

export function ToolTipDetails({
  children,
}: {
  children: string | JSX.Element;
}) {
  return (
    <TooltipProvider>
      <Tooltip>
        <TooltipTrigger type="button">
          <FiInfo size={12} />
        </TooltipTrigger>
        <TooltipContent side="top" align="center">
          {children}
        </TooltipContent>
      </Tooltip>
    </TooltipProvider>
  );
}

const FieldLabel = ({
  subtext,
  error,
  name,
  tooltip,
  optional,
  hideError,
  label,
  removeLabel,
  vertical,
}: {
  subtext?: string | JSX.Element;
  error?: string;
  name: string;
  tooltip?: string;
  optional?: boolean;
  hideError?: boolean;
  label: string;
  removeLabel?: boolean;
  vertical?: boolean;
}) => (
  <>
    <div
      className={`flex ${
        vertical ? "flex-col" : "flex-row"
      } gap-x-2 items-start`}
    >
      <div className="flex gap-x-2 items-center">
        {!removeLabel && <Label small={false}>{label}</Label>}
        {optional ? <span>(optional) </span> : ""}
        {tooltip && <ToolTipDetails>{tooltip}</ToolTipDetails>}
      </div>
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
    {subtext && <SubLabel>{subtext}</SubLabel>}
  </>
);

export function TextFormField({
  name,
  label,
  subtext,
  placeholder,
  type = "text",
  optional,
  includeRevert,
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
  maxWidth,
  removeLabel,
  min,
  onChange,
  width,
  vertical,
  className,
}: {
  name: string;
  removeLabel?: boolean;
  label: string;
  subtext?: string | JSX.Element;
  placeholder?: string;
  includeRevert?: boolean;
  optional?: boolean;
  type?: string;
  isTextArea?: boolean;
  disabled?: boolean;
  autoCompleteDisabled?: boolean;
  error?: string;
  defaultHeight?: string;
  isCode?: boolean;
  fontSize?: "sm" | "md" | "lg";
  maxWidth?: string;
  hideError?: boolean;
  tooltip?: string;
  explanationText?: string;
  explanationLink?: string;
  small?: boolean;
  min?: number;
  onChange?: (e: React.ChangeEvent<HTMLInputElement>) => void;
  width?: string;
  vertical?: boolean;
  className?: string;
}) {
  let heightString = defaultHeight || "";
  if (isTextArea && !heightString) {
    heightString = "h-28";
  }

  const [, , { setValue }] = useField(name);

  const handleChange = (
    e: React.ChangeEvent<HTMLInputElement | HTMLTextAreaElement>
  ) => {
    setValue(e.target.value);
    if (onChange) {
      onChange(e as React.ChangeEvent<HTMLInputElement>);
    }
  };
  const textSizeClasses = {
    sm: {
      label: "text-sm",
      input: "text-sm",
      placeholder: "text-sm",
    },
    md: {
      label: "text-base",
      input: "text-base",
      placeholder: "text-base",
    },
    lg: {
      label: "text-lg",
      input: "text-lg",
      placeholder: "text-lg",
    },
  };

  const sizeClass = textSizeClasses[fontSize || "sm"];

  return (
    <div className={`w-full ${maxWidth} ${width}`}>
      <FieldLabel
        key={name}
        subtext={subtext}
        error={error}
        name={name}
        tooltip={tooltip}
        optional={optional}
        hideError={hideError}
        label={label}
        removeLabel={removeLabel}
        vertical={vertical}
      />
      <div className={`w-full flex ${includeRevert && "gap-x-2"} relative`}>
        <Field
          onChange={handleChange}
          min={min}
          as={isTextArea ? "textarea" : "input"}
          type={type}
          data-testid={name}
          name={name}
          id={name}
          className={`
            ${small && sizeClass.input}
            flex
            h-10
            w-full
            rounded-md
            border
            border-neutral-200
            bg-white
            px-3
            py-2
            mt-1
            text-base

            file:border-0
            file:bg-transparent
            file:text-sm
            file:font-medium
            file:text-neutral-950
            placeholder:text-neutral-500
            placeholder:font-description
            placeholder:${sizeClass.placeholder}
            caret-accent
            focus-visible:outline-none
            focus-visible:ring-1
            focus-visible:ring-lighter-agent
            focus-visible:ring-offset-1
            disabled:cursor-not-allowed
            disabled:opacity-50
            md:text-sm
            dark:border-neutral-700
            dark:bg-transparent
            dark:ring-offset-neutral-950
            dark:file:text-neutral-50
            dark:placeholder:text-neutral-400

            ${heightString}
            ${sizeClass.input}
            ${disabled ? "bg-neutral-100 dark:bg-neutral-800" : ""}
            ${isCode ? "font-mono" : ""}
            ${className}
          `}
          disabled={disabled}
          placeholder={placeholder}
          autoComplete={autoCompleteDisabled ? "off" : undefined}
        />
      </div>

      {explanationText && (
        <ExplanationText link={explanationLink} text={explanationText} />
      )}
    </div>
  );
}

export function FileUploadFormField({
  name,
  label,
  subtext,
}: {
  name: string;
  label: string;
  subtext?: string | JSX.Element;
}) {
  // We create a *temporary* field inside of `Formik` to throw the `File` object into.
  // The actual *contents* of the file will be thrown into the field called `name`.
  const fileName = `temporary.filename-${name}`;
  const [fileField] = useField<File>(fileName);
  const [, , contentsHelper] = useField<string>(name);

  useEffect(() => {
    const reader = new FileReader();
    reader.onload = (e) => {
      contentsHelper.setValue(e.target?.result as string);
    };
    if (fileField.value instanceof File) {
      reader.readAsText(fileField.value);
    }
  }, [contentsHelper, fileField.value]);

  return (
    <div className="w-full">
      <FieldLabel name={name} label={label} subtext={subtext} />
      <FileInput name={fileName} multiple={false} hideError />
    </div>
  );
}

export function MultiSelectField({
  name,
  label,
  subtext,
  options,
  onChange,
  error,
  hideError,
  small,
  selectedInitially,
}: {
  selectedInitially: string[];
  name: string;
  label: string;
  subtext?: string | JSX.Element;
  options: { value: string; label: string }[];
  onChange?: (selected: string[]) => void;
  error?: string;
  hideError?: boolean;
  small?: boolean;
}) {
  const [selectedOptions, setSelectedOptions] =
    useState<string[]>(selectedInitially);

  const handleCheckboxChange = (value: string) => {
    const newSelectedOptions = selectedOptions.includes(value)
      ? selectedOptions.filter((option) => option !== value)
      : [...selectedOptions, value];

    setSelectedOptions(newSelectedOptions);
    if (onChange) {
      onChange(newSelectedOptions);
    }
  };

  return (
    <div className="mb-6">
      <div className="flex gap-x-2 items-center">
        <Label small={small}>{label}</Label>
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

      {subtext && <SubLabel>{subtext}</SubLabel>}
      <div className="mt-2">
        {options.map((option) => (
          <label key={option.value} className="flex items-center mb-2">
            <input
              type="checkbox"
              name={name}
              value={option.value}
              checked={selectedOptions.includes(option.value)}
              onChange={() => handleCheckboxChange(option.value)}
              className="mr-2"
            />
            {option.label}
          </label>
        ))}
      </div>
    </div>
  );
}
interface MarkdownPreviewProps {
  name: string;
  label: string;
  placeholder?: string;
  error?: string;
}

export const MarkdownFormField = ({
  name,
  label,
  error,
  placeholder = "Enter your markdown here...",
}: MarkdownPreviewProps) => {
  const [field] = useField(name);
  const [isPreviewOpen, setIsPreviewOpen] = useState(false);

  const togglePreview = () => {
    setIsPreviewOpen(!isPreviewOpen);
  };

  return (
    <div className="flex flex-col space-y-4 mb-4">
      <Label>{label}</Label>
      <div className="border border-background-300 rounded-md">
        <div className="flex items-center justify-between px-4 py-2 bg-background-100 rounded-t-md">
          <div className="flex items-center space-x-2">
            <FaMarkdown className="text-text-500" />
            <span className="text-sm font-semibold text-text-600">
              Markdown
            </span>
          </div>
          <button
            type="button"
            onClick={togglePreview}
            className="text-sm font-semibold text-text-600 hover:text-text-800 focus:outline-none"
          >
            {isPreviewOpen ? "Write" : "Preview"}
          </button>
        </div>
        {isPreviewOpen ? (
          <div className="p-4 border-t border-background-300">
            <ReactMarkdown
              className="prose dark:prose-invert"
              remarkPlugins={[remarkGfm]}
              urlTransform={transformLinkUri}
            >
              {field.value}
            </ReactMarkdown>
          </div>
        ) : (
          <div className="pt-2 px-2">
            <textarea
              {...field}
              rows={2}
              placeholder={placeholder}
              className={`w-full p-2 border border-border rounded-md border-background-300`}
            />
          </div>
        )}
      </div>
      {error ? (
        <ManualErrorMessage>{error}</ManualErrorMessage>
      ) : (
        <ErrorMessage
          name={name}
          component="div"
          className="text-red-500 text-sm mt-1"
        />
      )}
    </div>
  );
};

interface BooleanFormFieldProps {
  name: string;
  label: string;
  subtext?: string | JSX.Element;
  removeIndent?: boolean;
  small?: boolean;
  noLabel?: boolean;
  disabled?: boolean;
  optional?: boolean;
  tooltip?: string;
  disabledTooltip?: string;
  onChange?: (checked: boolean) => void;
}

export const BooleanFormField = ({
  name,
  label,
  subtext,
  removeIndent,
  noLabel,
  optional,
  small,
  disabled,
  tooltip,
  disabledTooltip,
  onChange,
}: BooleanFormFieldProps) => {
  const { setFieldValue } = useFormikContext<any>();

  const handleChange = useCallback(
    (checked: CheckedState) => {
      if (!disabled) {
        setFieldValue(name, checked);
      }
      if (onChange) {
        onChange(checked === true);
      }
    },
    [disabled, name, setFieldValue, onChange]
  );

  return (
    <div>
      <label className="flex items-center text-sm cursor-pointer">
        <TooltipProvider>
          <Tooltip>
            <TooltipTrigger>
              <CheckboxField
                name={name}
                size="sm"
                className={`
                  ${disabled ? "opacity-50" : ""}
                  ${removeIndent ? "mr-2" : "mx-3"}`}
                onCheckedChange={handleChange}
              />
            </TooltipTrigger>
            {disabled && disabledTooltip && (
              <TooltipContent side="top" align="center">
                <p className="bg-background-900 max-w-[200px] mb-1 text-sm rounded-lg p-1.5 text-white">
                  {disabledTooltip}
                </p>
              </TooltipContent>
            )}
          </Tooltip>
        </TooltipProvider>
        {!noLabel && (
          <div>
            <div className="flex items-center gap-x-2">
              <Label small={small}>{`${label}${
                optional ? " (Optional)" : ""
              }`}</Label>
              {tooltip && <ToolTipDetails>{tooltip}</ToolTipDetails>}
            </div>

            {subtext && <SubLabel>{subtext}</SubLabel>}
          </div>
        )}
      </label>

      <ErrorMessage
        name={name}
        component="div"
        className="text-error text-sm mt-1"
      />
    </div>
  );
};

interface TextArrayFieldProps<T extends Yup.AnyObject> {
  name: string;
  label: string | JSX.Element;
  values: T;
  subtext?: string | JSX.Element;
  type?: string;
  tooltip?: string;
  minFields?: number;
  placeholder?: string;
}

export function TextArrayField<T extends Yup.AnyObject>({
  name,
  label,
  values,
  subtext,
  type,
  tooltip,
  minFields = 0,
  placeholder = "",
}: TextArrayFieldProps<T>) {
  return (
    <div className="mb-4">
      <div className="flex gap-x-2 items-center">
        <Label>{label}</Label>
        {tooltip && <ToolTipDetails>{tooltip}</ToolTipDetails>}
      </div>
      {subtext && <SubLabel>{subtext}</SubLabel>}

      <FieldArray
        name={name}
        render={(arrayHelpers: ArrayHelpers) => (
          <div>
            {values[name] &&
              values[name].length > 0 &&
              (values[name] as string[]).map((_, index) => (
                <div key={index} className="mt-2">
                  <div className="flex">
                    <Field
                      type={type}
                      name={`${name}.${index}`}
                      id={name}
                      className={`
                      border
                      border-border
                      bg-background
                      rounded
                      w-full
                      py-2
                      px-3
                      mr-4
                      `}
                      // Disable autocomplete since the browser doesn't know how to handle an array of text fields
                      autoComplete="off"
                      placeholder={placeholder}
                    />
                    <div className="my-auto">
                      {index >= minFields ? (
                        <FiX
                          className="my-auto w-10 h-10 cursor-pointer hover:bg-accent-background-hovered rounded p-2"
                          onClick={() => arrayHelpers.remove(index)}
                        />
                      ) : (
                        <div className="w-10 h-10" />
                      )}
                    </div>
                  </div>
                  <ErrorMessage
                    name={`${name}.${index}`}
                    component="div"
                    className="text-error text-sm mt-1"
                  />
                </div>
              ))}

            <Button
              onClick={() => {
                arrayHelpers.push("");
              }}
              className="mt-3"
              variant="update"
              size="sm"
              type="button"
              icon={FiPlus}
            >
              Add New
            </Button>
          </div>
        )}
      />
    </div>
  );
}

interface TextArrayFieldBuilderProps<T extends Yup.AnyObject> {
  name: string;
  label: string;
  subtext?: string | JSX.Element;
  type?: string;
  tooltip?: string;
}

export function TextArrayFieldBuilder<T extends Yup.AnyObject>(
  props: TextArrayFieldBuilderProps<T>
): FormBodyBuilder<T> {
  const _TextArrayField: FormBodyBuilder<T> = (values) => (
    <TextArrayField {...props} values={values} />
  );
  return _TextArrayField;
}

interface SelectorFormFieldProps {
  name: string;
  label?: string;
  options: StringOrNumberOption[];
  subtext?: string | JSX.Element;
  includeDefault?: boolean;
  side?: "top" | "right" | "bottom" | "left";
  maxHeight?: string;
  onSelect?: (selected: string | number | null) => void;
  defaultValue?: string;
  tooltip?: string;
  includeReset?: boolean;
  fontSize?: "sm" | "md" | "lg";
  small?: boolean;
  disabled?: boolean;
}

export function SelectorFormField({
  name,
  label,
  options,
  subtext,
  side = "bottom",
  maxHeight,
  onSelect,
  defaultValue,
  tooltip,
  includeReset = false,
  fontSize = "md",
  small = false,
  disabled = false,
}: SelectorFormFieldProps) {
  const [field] = useField<string>(name);
  const { setFieldValue } = useFormikContext();
  const [container, setContainer] = useState<HTMLDivElement | null>(null);

  const currentlySelected = options.find(
    (option) => option.value?.toString() === field.value?.toString()
  );

  const textSizeClasses = {
    sm: {
      label: "text-sm",
      input: "text-sm",
      placeholder: "text-sm",
    },
    md: {
      label: "text-base",
      input: "text-base",
      placeholder: "text-base",
    },
    lg: {
      label: "text-lg",
      input: "text-lg",
      placeholder: "text-lg",
    },
  };

  const sizeClass = textSizeClasses[fontSize];

  return (
    <div>
      {label && (
        <div className="flex gap-x-2 items-center">
          <Label className={sizeClass.label} small={small}>
            {label}
          </Label>
          {tooltip && <ToolTipDetails>{tooltip}</ToolTipDetails>}
        </div>
      )}
      {subtext && <SubLabel>{subtext}</SubLabel>}
      <div className="mt-2" ref={setContainer}>
        <Select
          value={field.value || defaultValue}
          onValueChange={
            onSelect ||
            ((selected) =>
              selected == "__none__"
                ? setFieldValue(name, null)
                : setFieldValue(name, selected))
          }
          defaultValue={defaultValue}
          disabled={disabled}
        >
          <SelectTrigger className={sizeClass.input} disabled={disabled}>
            <SelectValue placeholder="Select...">
              {currentlySelected?.name || defaultValue || ""}
            </SelectValue>
          </SelectTrigger>

          {container && (
            <SelectContent
              side={side}
              className={`
               ${maxHeight ? `${maxHeight}` : "max-h-72"}
               overflow-y-scroll
               ${sizeClass.input}
              `}
              container={container}
            >
              {options.length === 0 ? (
                <SelectItem value="default">Select...</SelectItem>
              ) : (
                options.map((option) => (
                  <SelectItem
                    hideCheck
                    icon={option.icon}
                    key={option.value}
                    value={String(option.value)}
                    selected={field.value === option.value}
                  >
                    {option.name}
                  </SelectItem>
                ))
              )}
              {includeReset && (
                <SelectItem
                  value={"__none__"}
                  onSelect={() => setFieldValue(name, null)}
                >
                  None
                </SelectItem>
              )}
            </SelectContent>
          )}
        </Select>
      </div>

      <ErrorMessage
        name={name}
        component="div"
        className="text-error text-sm mt-1"
      />
    </div>
  );
}
