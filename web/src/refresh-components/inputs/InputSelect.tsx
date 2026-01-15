"use client";

import * as React from "react";
import * as SelectPrimitive from "@radix-ui/react-select";
import { cn, noProp } from "@/lib/utils";
import LineItem, { LineItemProps } from "@/refresh-components/buttons/LineItem";
import Text from "@/refresh-components/texts/Text";
import type { IconProps } from "@opal/types";
import {
  iconClasses,
  textClasses,
  Variants,
  wrapperClasses,
} from "@/refresh-components/inputs/styles";
import Truncated from "@/refresh-components/texts/Truncated";
import { SvgChevronDownSmall } from "@opal/icons";
import Separator, { SeparatorProps } from "@/refresh-components/Separator";
import { WithoutStyles } from "@/types";

// ============================================================================
// Context
// ============================================================================

interface SelectedItemDisplay {
  childrenRef: React.MutableRefObject<React.ReactNode>;
  iconRef: React.MutableRefObject<
    React.FunctionComponent<IconProps> | undefined
  >;
}

interface InputSelectContextValue {
  variant: Variants;
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

// ============================================================================
// InputSelect Root
// ============================================================================

/**
 * InputSelect Root Component
 *
 * A styled select/dropdown component built on Radix UI Select primitives.
 * Provides full control over trigger and content rendering.
 *
 * @example
 * ```tsx
 * <InputSelect defaultValue="option1">
 *   <InputSelect.Trigger placeholder="Select an option" />
 *   <InputSelect.Content>
 *     <InputSelect.Item value="option1">Option 1</InputSelect.Item>
 *     <InputSelect.Item value="option2">Option 2</InputSelect.Item>
 *   </InputSelect.Content>
 * </InputSelect>
 *
 * // Controlled
 * <InputSelect value={value} onValueChange={setValue}>
 *   <InputSelect.Trigger placeholder="Select..." />
 *   <InputSelect.Content>
 *     <InputSelect.Item value="a">A</InputSelect.Item>
 *   </InputSelect.Content>
 * </InputSelect>
 *
 * // With error state
 * <InputSelect error>
 *   <InputSelect.Trigger placeholder="Required field" />
 *   <InputSelect.Content>
 *     <InputSelect.Item value="x">X</InputSelect.Item>
 *   </InputSelect.Content>
 * </InputSelect>
 * ```
 */
interface InputSelectRootProps
  extends React.ComponentPropsWithoutRef<typeof SelectPrimitive.Root> {
  /** Whether to show error styling */
  error?: boolean;
  /** Whether the select is disabled */
  disabled?: boolean;
  /** Additional CSS classes for the wrapper element */
  className?: string;
  children: React.ReactNode;
}
const InputSelectRoot = React.forwardRef<HTMLDivElement, InputSelectRootProps>(
  (
    {
      disabled,
      error,
      value,
      defaultValue,
      onValueChange,
      className,
      children,
      ...props
    },
    ref
  ) => {
    const variant: Variants = disabled ? "disabled" : error ? "error" : "main";

    // Support both controlled and uncontrolled modes
    const isControlled = value !== undefined;
    const [internalValue, setInternalValue] = React.useState<
      string | undefined
    >(defaultValue);
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

    // Store the selected item's display data (children/icon refs)
    // Only the currently selected item registers itself
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
      <div className="w-full relative">
        <InputSelectContext.Provider value={contextValue}>
          <SelectPrimitive.Root
            {...(isControlled ? { value: currentValue } : { defaultValue })}
            onValueChange={handleValueChange}
            disabled={disabled}
            {...props}
          >
            <div ref={ref} className={className}>
              {children}
            </div>
          </SelectPrimitive.Root>
        </InputSelectContext.Provider>
      </div>
    );
  }
);
InputSelectRoot.displayName = "InputSelect";

// ============================================================================
// InputSelect Trigger
// ============================================================================

/**
 * InputSelect Trigger Component
 *
 * The clickable trigger that opens the dropdown.
 *
 * @example
 * ```tsx
 * // With placeholder
 * <InputSelect.Trigger placeholder="Select..." />
 *
 * // With right section
 * <InputSelect.Trigger placeholder="Select..." rightSection={<Badge>New</Badge>} />
 * ```
 */
interface InputSelectTriggerProps
  extends React.ComponentPropsWithoutRef<typeof SelectPrimitive.Trigger> {
  /** Placeholder when no value selected */
  placeholder?: React.ReactNode;
  /** Content to render on the right side of the trigger */
  rightSection?: React.ReactNode;
}
const InputSelectTrigger = React.forwardRef<
  React.ComponentRef<typeof SelectPrimitive.Trigger>,
  InputSelectTriggerProps
>(({ placeholder, rightSection, className, children, ...props }, ref) => {
  const { variant, selectedItemDisplay } = useInputSelectContext();

  // Don't memoize - we need to read the latest ref values on every render
  let displayContent: React.ReactNode;

  if (!selectedItemDisplay) {
    displayContent = placeholder ? (
      typeof placeholder === "string" ? (
        <Text as="p" text03>
          {placeholder}
        </Text>
      ) : (
        placeholder
      )
    ) : (
      <Text as="p" text03>
        Select an option
      </Text>
    );
  } else {
    const Icon = selectedItemDisplay.iconRef.current;
    displayContent = (
      <div className="flex flex-row items-center gap-2 flex-1 w-full">
        {Icon && <Icon className={cn("h-4 w-4", iconClasses[variant])} />}
        <Truncated className={cn(textClasses[variant])}>
          {selectedItemDisplay.childrenRef.current}
        </Truncated>
      </div>
    );
  }

  return (
    <SelectPrimitive.Trigger
      ref={ref}
      className={cn(
        "group/InputSelect flex w-full items-center justify-between p-1.5 rounded-08 focus:outline-none",
        wrapperClasses[variant],
        variant === "main" && "data-[state=open]:border-border-05",
        className
      )}
      {...props}
    >
      <div className="flex flex-row items-center justify-between w-full p-0.5 gap-1">
        {children ?? displayContent}

        <div className="flex flex-row items-center gap-1">
          {rightSection}

          <SelectPrimitive.Icon asChild>
            <SvgChevronDownSmall
              className={cn(
                "h-4 w-4 transition-transform",
                iconClasses[variant],
                "group-data-[state=open]/InputSelect:-rotate-180"
              )}
            />
          </SelectPrimitive.Icon>
        </div>
      </div>
    </SelectPrimitive.Trigger>
  );
});
InputSelectTrigger.displayName = "InputSelectTrigger";

// ============================================================================
// InputSelect Content
// ============================================================================

/**
 * InputSelect Content Component
 *
 * The dropdown content container with animations and styling.
 *
 * @example
 * ```tsx
 * <InputSelect.Content>
 *   <InputSelect.Item value="1">Item 1</InputSelect.Item>
 *   <InputSelect.Item value="2">Item 2</InputSelect.Item>
 * </InputSelect.Content>
 * ```
 */
interface InputSelectContentProps
  extends React.ComponentPropsWithoutRef<typeof SelectPrimitive.Content> {}
const InputSelectContent = React.forwardRef<
  React.ComponentRef<typeof SelectPrimitive.Content>,
  InputSelectContentProps
>(({ className, children, ...props }, ref) => (
  <SelectPrimitive.Portal>
    <SelectPrimitive.Content
      ref={ref}
      className={cn(
        "z-[4000] w-[var(--radix-select-trigger-width)] max-h-72 overflow-auto rounded-12 border bg-background-neutral-00 p-1",
        "data-[state=open]:animate-in data-[state=closed]:animate-out",
        "data-[state=open]:fade-in-0 data-[state=closed]:fade-out-0",
        "data-[state=open]:zoom-in-95 data-[state=closed]:zoom-out-95",
        className
      )}
      sideOffset={4}
      position="popper"
      onMouseDown={noProp()}
      {...props}
    >
      <SelectPrimitive.Viewport className="flex flex-col gap-1">
        {children}
      </SelectPrimitive.Viewport>
    </SelectPrimitive.Content>
  </SelectPrimitive.Portal>
));
InputSelectContent.displayName = "InputSelectContent";

// ============================================================================
// InputSelect Item
// ============================================================================

/**
 * InputSelect Item Component
 *
 * Individual selectable option within the dropdown.
 *
 * @example
 * ```tsx
 * <InputSelect.Item value="option1" icon={SvgIcon}>
 *   Option 1
 * </InputSelect.Item>
 *
 * <InputSelect.Item value="option2" description="Additional info">
 *   Option 2
 * </InputSelect.Item>
 * ```
 */
interface InputSelectItemProps extends Omit<LineItemProps, "heavyForced"> {
  /** Unique value for this option */
  value: string;
  /** Optional callback when item is selected */
  onClick?: (event: React.SyntheticEvent) => void;
}
const InputSelectItem = React.forwardRef<
  React.ComponentRef<typeof SelectPrimitive.Item>,
  InputSelectItemProps
>(({ value, children, description, onClick, icon, ...props }, ref) => {
  const { currentValue, setSelectedItemDisplay } = useInputSelectContext();
  const isSelected = value === currentValue;

  // Use refs to hold latest children/icon - these are passed to the context
  // so the trigger always reads current values without needing re-registration
  const childrenRef = React.useRef(children);
  const iconRef = React.useRef(icon);
  childrenRef.current = children;
  iconRef.current = icon;

  // Only the selected item registers its display data
  React.useEffect(() => {
    if (!isSelected) return;
    setSelectedItemDisplay({ childrenRef, iconRef });

    // Clean up functions only need to return for items which are selected.
    return () => setSelectedItemDisplay(null);
  }, [isSelected]);

  return (
    <SelectPrimitive.Item
      ref={ref}
      value={value}
      className="outline-none focus:outline-none"
      onSelect={onClick}
    >
      {/* Hidden ItemText for Radix to track selection */}
      <span className="hidden">
        <SelectPrimitive.ItemText>{children}</SelectPrimitive.ItemText>
      </span>

      <LineItem
        {...props}
        icon={icon}
        selected={isSelected}
        emphasized
        description={description}
        onClick={noProp((event) => event.preventDefault())}
        className={cn("w-full", props.className)}
      >
        {children}
      </LineItem>
    </SelectPrimitive.Item>
  );
});
InputSelectItem.displayName = "InputSelectItem";

// ============================================================================
// InputSelect Group
// ============================================================================

/**
 * InputSelect Group Component
 *
 * Groups related items together with an optional label.
 *
 * @example
 * ```tsx
 * <InputSelect.Group>
 *   <InputSelect.Label>Fruits</InputSelect.Label>
 *   <InputSelect.Item value="apple">Apple</InputSelect.Item>
 *   <InputSelect.Item value="banana">Banana</InputSelect.Item>
 * </InputSelect.Group>
 * ```
 */
interface InputSelectGroupProps
  extends React.ComponentPropsWithoutRef<typeof SelectPrimitive.Group> {}
const InputSelectGroup = React.forwardRef<
  React.ComponentRef<typeof SelectPrimitive.Group>,
  InputSelectGroupProps
>(({ className, children, ...props }, ref) => (
  <SelectPrimitive.Group ref={ref} className={cn("", className)} {...props}>
    {children}
  </SelectPrimitive.Group>
));
InputSelectGroup.displayName = "InputSelectGroup";

// ============================================================================
// InputSelect Label
// ============================================================================

/**
 * InputSelect Label Component
 *
 * A label for a group of items.
 *
 * @example
 * ```tsx
 * <InputSelect.Label>Category Name</InputSelect.Label>
 * ```
 */
interface InputSelectLabelProps
  extends React.ComponentPropsWithoutRef<typeof SelectPrimitive.Label> {}
const InputSelectLabel = React.forwardRef<
  React.ComponentRef<typeof SelectPrimitive.Label>,
  InputSelectLabelProps
>(({ className, children, ...props }, ref) => (
  <SelectPrimitive.Label
    ref={ref}
    className={cn(
      "px-2 py-1.5 text-xs font-medium text-text-03 uppercase tracking-wide",
      className
    )}
    {...props}
  >
    {children}
  </SelectPrimitive.Label>
));
InputSelectLabel.displayName = "InputSelectLabel";

// ============================================================================
// InputSelect Separator
// ============================================================================

/**
 * InputSelect Separator Component
 *
 * A visual divider between items in the dropdown.
 * Uses the app's standard Separator component with appropriate defaults for dropdown menus.
 *
 * @example
 * ```tsx
 * <InputSelect.Content>
 *   <InputSelect.Item value="1">Option 1</InputSelect.Item>
 *   <InputSelect.Separator />
 *   <InputSelect.Item value="2">Option 2</InputSelect.Item>
 * </InputSelect.Content>
 * ```
 */
type InputSelectSeparatorProps = WithoutStyles<SeparatorProps>;
const InputSelectSeparator = React.forwardRef<
  React.ComponentRef<typeof Separator>,
  InputSelectSeparatorProps
>(({ noPadding = true, ...props }, ref) => (
  <Separator ref={ref} noPadding={noPadding} className="px-2 py-1" {...props} />
));
InputSelectSeparator.displayName = "InputSelectSeparator";

// ============================================================================
// Exports
// ============================================================================

/**
 * InputSelect - A styled select/dropdown component
 *
 * @example
 * ```tsx
 * import InputSelect from "@/refresh-components/inputs/InputSelect";
 *
 * <InputSelect defaultValue="1">
 *   <InputSelect.Trigger placeholder="Choose..." />
 *   <InputSelect.Content>
 *     <InputSelect.Item value="1">Option 1</InputSelect.Item>
 *     <InputSelect.Item value="2">Option 2</InputSelect.Item>
 *   </InputSelect.Content>
 * </InputSelect>
 *
 * // With groups
 * <InputSelect defaultValue="1">
 *   <InputSelect.Trigger placeholder="Choose a model..." />
 *   <InputSelect.Content>
 *     <InputSelect.Group>
 *       <InputSelect.Label>OpenAI</InputSelect.Label>
 *       <InputSelect.Item value="1">GPT-4o Mini</InputSelect.Item>
 *       <InputSelect.Item value="2">GPT-4o</InputSelect.Item>
 *     </InputSelect.Group>
 *     <InputSelect.Group>
 *       <InputSelect.Label>Anthropic</InputSelect.Label>
 *       <InputSelect.Item value="3">Claude Opus 4.5</InputSelect.Item>
 *       <InputSelect.Item value="4">Claude Sonnet 4.5</InputSelect.Item>
 *     </InputSelect.Group>
 *   </InputSelect.Content>
 * </InputSelect>
 * ```
 */
export default Object.assign(InputSelectRoot, {
  Trigger: InputSelectTrigger,
  Content: InputSelectContent,
  Item: InputSelectItem,
  Group: InputSelectGroup,
  Label: InputSelectLabel,
  Separator: InputSelectSeparator,
});

export {
  type InputSelectRootProps,
  type InputSelectTriggerProps,
  type InputSelectContentProps,
  type InputSelectItemProps,
  type InputSelectGroupProps,
  type InputSelectLabelProps,
  type InputSelectSeparatorProps,
};
