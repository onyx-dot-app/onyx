import { Button } from "@tremor/react";
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
import { DefaultDropdown, StringOrNumberOption } from "@/components/Dropdown";
import { FiInfo, FiPlus, FiX } from "react-icons/fi";
import {
  TooltipProvider,
  Tooltip,
  TooltipContent,
  TooltipTrigger,
} from "@radix-ui/react-tooltip";
import ReactMarkdown from "react-markdown";
import { FaMarkdown } from "react-icons/fa";
import { useState } from "react";
import remarkGfm from "remark-gfm";

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
}: {
  children: string | JSX.Element;
  small?: boolean;
}) {
  return (
    <div
      className={`block font-medium base ${small ? "text-sm" : "text-base"}`}
    >
      {children}
    </div>
  );
}

export function SubLabel({ children }: { children: string | JSX.Element }) {
  return <div className="text-sm text-subtle mb-2">{children}</div>;
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
      className="underline cursor-pointer text-sm font-medium"
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
    <TooltipProvider delayDuration={50}>
      <Tooltip>
        <TooltipTrigger>
          <FiInfo size={12} />
        </TooltipTrigger>
        <TooltipContent side="top" align="center">
          <p className="bg-background-900 max-w-[200px] mb-1 text-sm rounded-lg p-1.5 text-inverted">
            {children}
          </p>
        </TooltipContent>
      </Tooltip>
    </TooltipProvider>
  );
}

export function TextFormField({
  name,
  label,
  subtext,
  placeholder,
  onChange,
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
}: {
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
}) {
  let heightString = defaultHeight || "";
  if (isTextArea && !heightString) {
    heightString = "h-28";
  }

  return (
    <div className={`${!noPadding && "mb-6"}`}>
      <div className="flex gap-x-2 items-center">
        {!removeLabel && <Label small={small}>{label}</Label>}
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

      {subtext && <SubLabel>{subtext}</SubLabel>}

      <Field
        as={isTextArea ? "textarea" : "input"}
        type={type}
        name={name}
        id={name}
        className={`
          ${small && "text-sm"}
          border 
          border-border 
          rounded 
          w-full 
          py-2 
          px-3 
          mt-1
          ${heightString}
          ${fontSize}
          ${disabled ? " bg-background-strong" : " bg-background-emphasis"}
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
  const [field, _] = useField(name);
  const [isPreviewOpen, setIsPreviewOpen] = useState(false);

  const togglePreview = () => {
    setIsPreviewOpen(!isPreviewOpen);
  };

  return (
    <div className="flex flex-col space-y-4 mb-4">
      <Label>{label}</Label>
      <div className="border border-gray-300 rounded-md">
        <div className="flex items-center justify-between px-4 py-2 bg-gray-100 rounded-t-md">
          <div className="flex items-center space-x-2">
            <FaMarkdown className="text-gray-500" />
            <span className="text-sm font-semibold text-gray-600">
              Markdown
            </span>
          </div>
          <button
            type="button"
            onClick={togglePreview}
            className="text-sm font-semibold text-gray-600 hover:text-gray-800 focus:outline-none"
          >
            {isPreviewOpen ? "Write" : "Preview"}
          </button>
        </div>
        {isPreviewOpen ? (
          <div className="p-4 border-t border-gray-300">
            <ReactMarkdown className="prose" remarkPlugins={[remarkGfm]}>
              {field.value}
            </ReactMarkdown>
          </div>
        ) : (
          <div className="pt-2 px-2">
            <textarea
              {...field}
              rows={2}
              placeholder={placeholder}
              className={`w-full p-2 border border-border rounded-md border-gray-300`}
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
  onChange?: (e: React.ChangeEvent<HTMLInputElement>) => void;
  noPadding?: boolean;
  small?: boolean;
  alignTop?: boolean;
  noLabel?: boolean;
  disabled?: boolean;
}

export const BooleanFormField = ({
  name,
  label,
  subtext,
  onChange,
  noPadding,
  noLabel,
  small,
  disabled,
  alignTop,
}: BooleanFormFieldProps) => {
  return (
    <div className="mb-4">
      <label className="flex text-sm">
        <Field
          disabled={disabled}
          name={name}
          type="checkbox"
          className={`${noPadding ? "mr-3" : "mx-3"} px-5 w-3.5 h-3.5 ${
            alignTop ? "mt-1" : "my-auto"
          }`}
          {...(onChange ? { onChange } : {})}
        />
        {!noLabel && (
          <div>
            <Label small={small}>{label}</Label>
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
}

export function TextArrayField<T extends Yup.AnyObject>({
  name,
  label,
  values,
  subtext,
  type,
}: TextArrayFieldProps<T>) {
  return (
    <div className="mb-4">
      <Label>{label}</Label>
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
                    />
                    <div className="my-auto">
                      <FiX
                        className="my-auto w-10 h-10 cursor-pointer hover:bg-hover rounded p-2"
                        onClick={() => arrayHelpers.remove(index)}
                      />
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
              color="green"
              size="xs"
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
}

export function SelectorFormField({
  name,
  label,
  options,
  subtext,
  includeDefault = false,
  side = "bottom",
  maxHeight,
  onSelect,
  defaultValue,
}: SelectorFormFieldProps) {
  const [field] = useField<string>(name);
  const { setFieldValue } = useFormikContext();

  return (
    <div className="mb-4">
      {label && <Label>{label}</Label>}
      {subtext && <SubLabel>{subtext}</SubLabel>}

      <div className="mt-2">
        <DefaultDropdown
          options={options}
          selected={field.value}
          onSelect={onSelect || ((selected) => setFieldValue(name, selected))}
          includeDefault={includeDefault}
          side={side}
          maxHeight={maxHeight}
          defaultValue={defaultValue}
        />
      </div>

      <ErrorMessage
        name={name}
        component="div"
        className="text-error text-sm mt-1"
      />
    </div>
  );
}
