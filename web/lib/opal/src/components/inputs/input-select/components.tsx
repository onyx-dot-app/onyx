"use client";

import "@opal/components/inputs/shared.css";
import "@opal/components/inputs/input-select/styles.css";
import React from "react";
import * as SelectPrimitive from "@radix-ui/react-select";
import { cn } from "@opal/utils";
import type {
  IconFunctionComponent,
  InputVariants,
  PaddingVariants,
  RichStr,
  WithoutStyles,
} from "@opal/types";
import { Divider, InputTypeIn, Text, Tooltip } from "@opal/components";
import { toPlainString } from "@opal/components/text/InlineMarkdown";
import { ContentAction } from "@opal/layouts";
import { SvgChevronDownSmall } from "@opal/icons";

// ---------------------------------------------------------------------------
// Context
// ---------------------------------------------------------------------------

interface SelectedItemDisplay {
  childrenRef: React.MutableRefObject<string | RichStr>;
  iconRef: React.MutableRefObject<IconFunctionComponent | undefined>;
}

interface InputSelectContextValue {
  variant: InputVariants;
  currentValue?: string;
  disabled?: boolean;
  selectedItemDisplay: SelectedItemDisplay | null;
  setSelectedItemDisplay: (display: SelectedItemDisplay | null) => void;
}

const InputSelectContext = React.createContext<InputSelectContextValue | null>(
  null
);

const useInputSelectContext = () => {
  const context = React.useContext(InputSelectContext);
  if (!context) {
    throw new Error(
      "InputSelect compound components must be used within InputSelect"
    );
  }
  return context;
};

// ---------------------------------------------------------------------------
// TruncatedDisplay
// ---------------------------------------------------------------------------

/**
 * Single-line trigger display that shows a hover tooltip only when the text
 * is actually truncated, measured against a hidden untruncated twin.
 */
function TruncatedDisplay({
  children,
  dimmed = false,
}: {
  children: string | RichStr;
  dimmed?: boolean;
}) {
  const [isTruncated, setIsTruncated] = React.useState(false);
  const visibleRef = React.useRef<HTMLDivElement>(null);
  const hiddenRef = React.useRef<HTMLDivElement>(null);

  React.useLayoutEffect(() => {
    function checkTruncation() {
      if (visibleRef.current && hiddenRef.current) {
        setIsTruncated(
          hiddenRef.current.offsetWidth > visibleRef.current.offsetWidth
        );
      }
    }

    // Defer a tick so initial layout settles before measuring.
    const timeoutId = setTimeout(checkTruncation, 0);
    window.addEventListener("resize", checkTruncation);
    return () => {
      clearTimeout(timeoutId);
      window.removeEventListener("resize", checkTruncation);
    };
  }, [children]);

  const text = (
    <Text color={dimmed ? "text-01" : "text-04"} nowrap>
      {children}
    </Text>
  );

  return (
    <Tooltip
      tooltip={isTruncated ? toPlainString(children) : undefined}
      side="top"
    >
      <div className="relative min-w-0 flex-1">
        <div ref={visibleRef} className="overflow-hidden truncate">
          {text}
        </div>
        <div
          ref={hiddenRef}
          aria-hidden
          className="pointer-events-none invisible absolute left-0 top-0 whitespace-nowrap"
        >
          {text}
        </div>
      </div>
    </Tooltip>
  );
}

// ---------------------------------------------------------------------------
// Root
// ---------------------------------------------------------------------------

interface InputSelectRootProps extends WithoutStyles<
  React.ComponentPropsWithoutRef<typeof SelectPrimitive.Root>
> {
  /** Error chrome on the trigger. */
  error?: boolean;
  disabled?: boolean;
  children: React.ReactNode;
  ref?: React.Ref<HTMLDivElement>;
}

function InputSelectRoot({
  disabled,
  error,
  value,
  defaultValue,
  onValueChange,
  children,
  ref,
  ...props
}: InputSelectRootProps) {
  const variant: InputVariants = disabled
    ? "disabled"
    : error
      ? "error"
      : "primary";

  // Mirrors the value in both modes so Item selection state and the trigger
  // display work without Radix internals.
  const isControlled = value !== undefined;
  const [internalValue, setInternalValue] = React.useState<string | undefined>(
    defaultValue
  );
  const currentValue = isControlled ? value : internalValue;

  React.useEffect(() => {
    if (isControlled) return;
    setInternalValue(defaultValue);
  }, [defaultValue, isControlled]);

  const handleValueChange = React.useCallback(
    (nextValue: string) => {
      onValueChange?.(nextValue);

      if (isControlled) return;
      setInternalValue(nextValue);
    },
    [isControlled, onValueChange]
  );

  // Only the selected Item registers its display, read by the Trigger through refs.
  const [selectedItemDisplay, setSelectedItemDisplay] =
    React.useState<SelectedItemDisplay | null>(null);

  React.useEffect(() => {
    if (!currentValue) setSelectedItemDisplay(null);
  }, [currentValue]);

  const contextValue = React.useMemo<InputSelectContextValue>(
    () => ({
      variant,
      currentValue,
      disabled,
      selectedItemDisplay,
      setSelectedItemDisplay,
    }),
    [variant, currentValue, disabled, selectedItemDisplay]
  );

  return (
    <div className="opal-input-select-root">
      <InputSelectContext.Provider value={contextValue}>
        <SelectPrimitive.Root
          {...(isControlled ? { value: currentValue } : { defaultValue })}
          onValueChange={handleValueChange}
          disabled={disabled}
          {...props}
        >
          <div ref={ref} className="w-full">
            {children}
          </div>
        </SelectPrimitive.Root>
      </InputSelectContext.Provider>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Trigger
// ---------------------------------------------------------------------------

interface InputSelectTriggerProps extends WithoutStyles<
  React.ComponentProps<typeof SelectPrimitive.Trigger>
> {
  /** Shown when no value is selected. Falsy values fall back to "Select an option". */
  placeholder?: React.ReactNode;

  /** Slot before the chevron. */
  rightSection?: React.ReactNode;
}

function InputSelectTrigger({
  placeholder,
  rightSection,
  children,
  ref,
  ...props
}: InputSelectTriggerProps) {
  const { variant, currentValue, selectedItemDisplay } =
    useInputSelectContext();

  // Read every render, the refs already hold the latest children/icon.
  let displayContent: React.ReactNode;

  if (selectedItemDisplay) {
    const Icon = selectedItemDisplay.iconRef.current;
    displayContent = (
      <div className="flex w-full flex-1 flex-row items-center gap-2">
        {Icon && <Icon className="opal-input-select-icon" />}
        <TruncatedDisplay dimmed={variant === "disabled"}>
          {selectedItemDisplay.childrenRef.current}
        </TruncatedDisplay>
      </div>
    );
  } else if (currentValue) {
    // Radix mirrors the selected ItemText here, so a preselected value never
    // shows the placeholder even before the Item's registration effect runs.
    displayContent = (
      <SelectPrimitive.Value
        className={cn(
          "truncate font-main-ui-body",
          variant === "disabled" ? "text-text-01" : "text-text-04"
        )}
      />
    );
  } else {
    const effectivePlaceholder = placeholder || "Select an option";
    displayContent =
      typeof effectivePlaceholder === "string" ? (
        <Text as="p" color="text-03">
          {effectivePlaceholder}
        </Text>
      ) : (
        effectivePlaceholder
      );
  }

  return (
    <SelectPrimitive.Trigger
      ref={ref}
      className="opal-input opal-input-select-trigger"
      data-variant={variant}
      {...props}
    >
      {/* text-left counters the button element's centered default. */}
      <div className="flex w-full flex-row items-center justify-between gap-1 p-0.5 text-left">
        {children ?? displayContent}

        <div className="flex flex-row items-center gap-1">
          {rightSection}

          <SelectPrimitive.Icon asChild>
            <SvgChevronDownSmall className="opal-input-select-icon opal-input-select-chevron" />
          </SelectPrimitive.Icon>
        </div>
      </div>
    </SelectPrimitive.Trigger>
  );
}

// ---------------------------------------------------------------------------
// Content
// ---------------------------------------------------------------------------

function InputSelectContent({
  children,
  ref,
  ...props
}: WithoutStyles<React.ComponentProps<typeof SelectPrimitive.Content>>) {
  return (
    <SelectPrimitive.Portal>
      <SelectPrimitive.Content
        ref={ref}
        className={cn(
          "opal-input-select-content",
          "data-[state=open]:animate-in data-[state=closed]:animate-out",
          "data-[state=open]:fade-in-0 data-[state=closed]:fade-out-0",
          "data-[state=open]:zoom-in-95 data-[state=closed]:zoom-out-95"
        )}
        sideOffset={4}
        position="popper"
        onMouseDown={(e) => {
          e.stopPropagation();
          e.preventDefault();
        }}
        {...props}
      >
        <SelectPrimitive.Viewport className="flex flex-col gap-1">
          {children}
        </SelectPrimitive.Viewport>
      </SelectPrimitive.Content>
    </SelectPrimitive.Portal>
  );
}

// ---------------------------------------------------------------------------
// Item
// ---------------------------------------------------------------------------

interface InputSelectItemProps {
  /** Unique option value. */
  value: string;

  /** Option label. */
  children: string | RichStr;

  icon?: IconFunctionComponent;
  description?: string | RichStr;

  /** Let the description wrap instead of truncating to one line. */
  wrapDescription?: boolean;

  ref?: React.Ref<React.ComponentRef<typeof SelectPrimitive.Item>>;
}

function InputSelectItem({
  value,
  children,
  description,
  wrapDescription,
  icon,
  ref,
}: InputSelectItemProps) {
  const { currentValue, setSelectedItemDisplay } = useInputSelectContext();
  const isSelected = value === currentValue;

  // Refs keep the trigger reading the latest children/icon between
  // registrations.
  const childrenRef = React.useRef<string | RichStr>(children);
  const iconRef = React.useRef(icon);
  childrenRef.current = children;
  iconRef.current = icon;

  // Layout effect so the trigger never paints the placeholder on first
  // render when a value is already selected. Radix mounts closed Content
  // into a detached fragment, so this runs even while the menu is closed.
  // Keyed on the rendered content (plain-text key, since RichStr identity
  // churns per render) so the trigger mirror re-renders when the selected
  // option's label or icon changes without a value change.
  const childrenKey = toPlainString(children);
  React.useLayoutEffect(() => {
    if (!isSelected) return;
    setSelectedItemDisplay({ childrenRef, iconRef });

    return () => setSelectedItemDisplay(null);
  }, [isSelected, childrenKey, icon]);

  return (
    <SelectPrimitive.Item
      ref={ref}
      value={value}
      className="opal-input-select-item"
    >
      {/* Hidden ItemText feeds Radix's typeahead and the native select fallback. */}
      <span className="hidden">
        <SelectPrimitive.ItemText>
          {toPlainString(children)}
        </SelectPrimitive.ItemText>
      </span>

      {/* Pure layout row: Radix owns highlight and selection state, styled
          via the item's data attributes. */}
      <div className="w-full p-2">
        <ContentAction
          sizePreset="main-ui"
          variant="section"
          color="interactive"
          icon={icon}
          title={children}
          titleMaxLines={1}
          description={description}
          descriptionMaxLines={wrapDescription ? undefined : 1}
          padding="fit"
          width="full"
        />
      </div>
    </SelectPrimitive.Item>
  );
}

// ---------------------------------------------------------------------------
// Group + Label + Separator
// ---------------------------------------------------------------------------

function InputSelectGroup({
  ref,
  ...props
}: WithoutStyles<React.ComponentProps<typeof SelectPrimitive.Group>>) {
  return <SelectPrimitive.Group ref={ref} {...props} />;
}

function InputSelectLabel({
  children,
  ref,
  ...props
}: WithoutStyles<React.ComponentProps<typeof SelectPrimitive.Label>>) {
  return (
    <SelectPrimitive.Label
      ref={ref}
      className="opal-input-select-label"
      {...props}
    >
      {children}
    </SelectPrimitive.Label>
  );
}

interface InputSelectSeparatorProps {
  paddingParallel?: PaddingVariants;
  paddingPerpendicular?: PaddingVariants;
}

function InputSelectSeparator({
  paddingParallel,
  paddingPerpendicular,
}: InputSelectSeparatorProps) {
  return (
    <Divider
      paddingParallel={paddingParallel}
      paddingPerpendicular={paddingPerpendicular}
    />
  );
}

// ---------------------------------------------------------------------------
// Search
// ---------------------------------------------------------------------------

interface InputSelectSearchProps {
  /** Controlled query. The consumer filters its own Items from it. */
  value: string;
  onChange: (e: React.ChangeEvent<HTMLInputElement>) => void;
  placeholder?: string;
}

/**
 * Sticky search row at the top of Content for filterable selects. The
 * consumer owns the query and renders only the Items that match. The row
 * owns focus and keyboard isolation: printable keys stay in the input so
 * Radix's item typeahead never fires, and ArrowDown hands focus to the
 * option list where Radix drives highlight and Enter natively.
 */
function InputSelectSearch({
  value,
  onChange,
  placeholder = "Search...",
}: InputSelectSearchProps) {
  const rowRef = React.useRef<HTMLDivElement>(null);
  const inputRef = React.useRef<HTMLInputElement>(null);

  // Focus a frame after mount, past Radix's own open autofocus in the
  // normal path, so typing searches immediately instead of jumping the
  // highlight via typeahead.
  React.useEffect(() => {
    const id = requestAnimationFrame(() => inputRef.current?.focus());
    return () => cancelAnimationFrame(id);
  }, []);

  function focusFirstOption() {
    const listbox = rowRef.current?.closest('[role="listbox"]');
    listbox
      ?.querySelector<HTMLElement>('[role="option"]:not([data-disabled])')
      ?.focus();
  }

  return (
    <div
      ref={rowRef}
      className="opal-input-select-search"
      // Mousedown must not reach Content, whose preventDefault would kill
      // caret placement and text selection in the input.
      onMouseDown={(e) => {
        e.stopPropagation();
        // Keep focus in the input when the clear (×) button is clicked, so
        // typing resumes immediately. Its action fires on click, which
        // preventDefault on mousedown does not suppress.
        if ((e.target as HTMLElement).closest("button")) {
          e.preventDefault();
          inputRef.current?.focus();
        }
      }}
      onKeyDown={(e) => {
        if (e.key === "ArrowDown") {
          e.preventDefault();
          e.stopPropagation();
          focusFirstOption();
          return;
        }
        // Keep keys out of Radix's item typeahead. Escape still closes the
        // menu: Radix listens at document capture, ahead of this handler.
        e.stopPropagation();
      }}
    >
      <InputTypeIn
        ref={inputRef}
        variant="internal"
        searchIcon
        clearButton
        value={value}
        onChange={onChange}
        placeholder={placeholder}
      />
    </div>
  );
}

// ---------------------------------------------------------------------------
// Exports
// ---------------------------------------------------------------------------

/**
 * InputSelect (Figma Input/Select): styled dropdown on Radix Select.
 * Compound: Trigger opens the popper Content, Items are Radix options
 * rendered as ContentAction rows, Group/Label/Separator organize them, and
 * Search makes the list filterable.
 */
const InputSelect = Object.assign(InputSelectRoot, {
  Trigger: InputSelectTrigger,
  Content: InputSelectContent,
  Item: InputSelectItem,
  Group: InputSelectGroup,
  Label: InputSelectLabel,
  Separator: InputSelectSeparator,
  Search: InputSelectSearch,
});

export {
  InputSelect,
  type InputSelectRootProps,
  type InputSelectTriggerProps,
  type InputSelectItemProps,
  type InputSelectSearchProps,
};
