"use client";

import {
  ArrayHelpers,
  ErrorMessage,
  Field,
  FieldArray,
  FastField,
  useField,
  useFormikContext,
} from "formik";
import { FileUpload } from "@/components/admin/connectors/FileUpload";
import * as Yup from "yup";
import { FormBodyBuilder } from "./admin/connectors/types";
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
import { useState, useCallback, useEffect, memo, useRef } from "react";
import remarkGfm from "remark-gfm";
import Button from "@/refresh-components/buttons/Button";
import { Checkbox } from "@/components/ui/checkbox";

import { transformLinkUri } from "@/lib/utils";
import FileInput from "@/app/admin/connectors/[connector]/pages/ConnectorInput/FileInput";
import { DatePicker } from "./ui/datePicker";
import { Textarea, TextareaProps } from "./ui/textarea";
import { RichTextSubtext } from "./RichTextSubtext";
import {
  TypedFile,
  createTypedFile,
  getFileTypeDefinitionForField,
  FILE_TYPE_DEFINITIONS,
} from "@/lib/connectors/fileTypes";
import Text from "@/refresh-components/texts/Text";
import SvgPlusCircle from "@/icons/plus-circle";
import CreateButton from "@/refresh-components/buttons/CreateButton";

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
  htmlFor,
}: {
  children: string | JSX.Element;
  small?: boolean;
  className?: string;
  htmlFor?: string;
}) {
  return (
    <label
      {...(htmlFor ? { htmlFor } : {})}
      className={`block font-medium ${className} ${
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
  // Add whitespace-pre-wrap for multiline descriptions (when children is a string with newlines)
  const hasNewlines = typeof children === "string" && children.includes("\n");

  // If children is a string, use RichTextSubtext to parse and render links
  if (typeof children === "string") {
    return (
      <span className="block text-sm text-text-03 mb-2">
        <RichTextSubtext
          text={children}
          className={hasNewlines ? "whitespace-pre-wrap" : ""}
        />
      </span>
    );
  }

  return (
    <span
      className={`block text-sm text-text-03 mb-2 ${
        hasNewlines ? "whitespace-pre-wrap" : ""
      }`}
    >
      {children}
    </span>
  );
}

export function ManualErrorMessage({ children }: { children: string }) {
  return <div className="text-action-danger-05 text-sm">{children}</div>;
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
          <Text inverted>{children}</Text>
        </TooltipContent>
      </Tooltip>
    </TooltipProvider>
  );
}

export const FieldLabel = ({
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
            className="text-action-danger-05 my-auto text-sm"
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
    if (onChange) {
      onChange(e as React.ChangeEvent<HTMLInputElement>);
    } else {
      setValue(e.target.value);
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
            px-3
            py-2
            mt-1
            file:border-0
            file:bg-transparent
            file:text-sm
            file:font-medium
            file:text-text-05
            placeholder:text-text-02
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
            border-border-03
            ring-offset-background-neutral-00
            file:text-text-inverted-05
            text-text-04

            ${heightString}
            ${sizeClass.input}
            ${disabled ? "bg-background-neutral-02" : ""}
            ${isCode ? "font-mono" : ""}
            ${className}
            bg-background-neutral-00
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

export function TypedFileUploadFormField({
  name,
  label,
  subtext,
}: {
  name: string;
  label: string;
  subtext?: string | JSX.Element;
}) {
  const [field, , helpers] = useField<TypedFile | null>(name);
  const [customError, setCustomError] = useState<string>("");
  const [isValidating, setIsValidating] = useState(false);
  const [description, setDescription] = useState<string>("");

  useEffect(() => {
    const typeDefinitionKey = getFileTypeDefinitionForField(name);
    if (typeDefinitionKey) {
      setDescription(
        FILE_TYPE_DEFINITIONS[typeDefinitionKey].description || ""
      );
    }
  }, [name]);

  useEffect(() => {
    const validateFile = async () => {
      if (!field.value) {
        setIsValidating(false);
        return;
      }

      setIsValidating(true);

      try {
        const validation = await field.value.validate();
        if (validation?.isValid) {
          setCustomError("");
        } else {
          setCustomError(validation?.errors.join(", ") || "Unknown error");
          helpers.setValue(null);
        }
      } catch (error) {
        setCustomError(
          error instanceof Error ? error.message : "Validation error"
        );
        helpers.setValue(null);
      } finally {
        setIsValidating(false);
      }
    };

    validateFile();
  }, [field.value, helpers]);

  const handleFileSelection = async (files: File[]) => {
    if (files.length === 0) {
      helpers.setValue(null);
      setCustomError("");
      return;
    }

    const file = files[0];
    if (!file) {
      setCustomError("File selection error");
      return;
    }

    const typeDefinitionKey = getFileTypeDefinitionForField(name);

    if (!typeDefinitionKey) {
      setCustomError(`No file type definition found for field: ${name}`);
      return;
    }

    try {
      const typedFile = createTypedFile(file, name, typeDefinitionKey);
      helpers.setValue(typedFile);
      setCustomError("");
    } catch (error) {
      setCustomError(error instanceof Error ? error.message : "Unknown error");
      helpers.setValue(null);
    } finally {
      setIsValidating(false);
    }
  };

  return (
    <div className="w-full">
      <FieldLabel name={name} label={label} subtext={subtext} />
      {description && (
        <div className="text-sm text-text-03 mb-2">{description}</div>
      )}
      <FileUpload
        selectedFiles={field.value ? [field.value.file] : []}
        setSelectedFiles={handleFileSelection}
        multiple={false}
      />
      {/* Validation feedback */}
      {isValidating && (
        <div className="text-status-info-05 text-sm mt-1">
          Validating file...
        </div>
      )}

      {customError ? (
        <div className="text-action-danger-05 text-sm mt-1">{customError}</div>
      ) : (
        <ErrorMessage
          name={name}
          component="div"
          className="text-action-danger-05 text-sm mt-1"
        />
      )}
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
              className="text-action-danger-05 my-auto text-sm"
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
      <div className="border border-border-02 rounded-md">
        <div className="flex items-center justify-between px-4 py-2 bg-background-neutral-02 rounded-t-md">
          <div className="flex items-center space-x-2">
            <FaMarkdown className="text-text-03" />
            <span className="text-sm font-semibold text-text-04">Markdown</span>
          </div>
          <button
            type="button"
            onClick={togglePreview}
            className="text-sm font-semibold text-text-04 hover:text-text-05 focus:outline-none"
          >
            {isPreviewOpen ? "Write" : "Preview"}
          </button>
        </div>
        {isPreviewOpen ? (
          <div className="p-4 border-t border-border-02">
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
              className={`w-full p-2 border border-border-02 rounded-md`}
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
          className="text-action-danger-05 text-sm mt-1"
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

export const BooleanFormField = memo(function BooleanFormField({
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
}: BooleanFormFieldProps) {
  // Generate a stable, valid id from the field name for label association
  const checkboxId = `checkbox-${name.replace(/[^a-zA-Z0-9_-]/g, "_")}`;

  return (
    <div>
      <div className="flex items-center text-sm">
        <TooltipProvider>
          <Tooltip>
            <FastField name={name} type="checkbox">
              {({ field, form }: any) => (
                <TooltipTrigger asChild>
                  <Checkbox
                    id={checkboxId}
                    className={`
                      ${disabled ? "opacity-50" : ""}
                      ${removeIndent ? "mr-2" : "mx-3"}`}
                    checked={Boolean(field.value)}
                    onCheckedChange={(checked) => {
                      if (!disabled) form.setFieldValue(name, checked === true);
                      if (onChange) onChange(checked === true);
                    }}
                  />
                </TooltipTrigger>
              )}
            </FastField>
            {disabled && disabledTooltip && (
              <TooltipContent side="top" align="center">
                <Text inverted>{disabledTooltip}</Text>
              </TooltipContent>
            )}
          </Tooltip>
        </TooltipProvider>
        {!noLabel && (
          <div>
            <div className="flex items-center gap-x-2">
              <Label
                htmlFor={checkboxId}
                small={small}
                className="cursor-pointer"
              >{`${label}${optional ? " (Optional)" : ""}`}</Label>
              {tooltip && <ToolTipDetails>{tooltip}</ToolTipDetails>}
            </div>
            {subtext && (
              <label htmlFor={checkboxId} className="cursor-pointer">
                <SubLabel>{subtext}</SubLabel>
              </label>
            )}
          </div>
        )}
      </div>

      <ErrorMessage
        name={name}
        component="div"
        className="text-action-danger-05 text-sm mt-1"
      />
    </div>
  );
});

interface TextArrayFieldProps<T extends Yup.AnyObject> {
  name: string;
  label: string | JSX.Element;
  values: T;
  subtext?: string | JSX.Element;
  type?: string;
  tooltip?: string;
  minFields?: number;
  placeholder?: string;
  disabled?: boolean;
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
  disabled = false,
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
                      disabled:cursor-not-allowed
                      `}
                      // Disable autocomplete since the browser doesn't know how to handle an array of text fields
                      autoComplete="off"
                      placeholder={placeholder}
                      disabled={disabled}
                    />
                    <div className="my-auto">
                      {index >= minFields ? (
                        <FiX
                          className="my-auto w-10 h-10 cursor-pointer hover:bg-background-neutral-02 rounded p-2"
                          onClick={() => {
                            if (!disabled) {
                              arrayHelpers.remove(index);
                            }
                          }}
                        />
                      ) : (
                        <div className="w-10 h-10" />
                      )}
                    </div>
                  </div>
                  <ErrorMessage
                    name={`${name}.${index}`}
                    component="div"
                    className="text-action-danger-05 text-sm mt-1"
                  />
                </div>
              ))}

            <CreateButton
              onClick={() => {
                if (!disabled) {
                  arrayHelpers.push("");
                }
              }}
              type="button"
              disabled={disabled}
            >
              Add New
            </CreateButton>
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
        className="text-action-danger-05 text-sm mt-1"
      />
    </div>
  );
}

export interface DatePickerFieldProps {
  label: string;
  name: string;
  subtext?: string;
  startYear?: number;
  disabled?: boolean;
}

export function DatePickerField({
  label,
  name,
  subtext,
  startYear = 1970,
  disabled = false,
}: DatePickerFieldProps) {
  const [field, _, helper] = useField<Date | null>(name);

  return (
    <div>
      <FieldLabel label={label} name={name} subtext={subtext} />
      <DatePicker
        selectedDate={field.value}
        setSelectedDate={helper.setValue}
        startYear={startYear}
        disabled={disabled}
      />
    </div>
  );
}

export interface TextAreaFieldProps extends TextareaProps {
  name: string;
}

export function TextAreaField(props: TextAreaFieldProps) {
  const [field, _, helper] = useField<string>(props.name);

  return (
    <Textarea
      value={field.value}
      onChange={(e) => {
        helper.setValue(e.target.value);
      }}
      {...props}
    />
  );
}
