"use client";

import * as React from "react";
import * as SelectPrimitive from "@radix-ui/react-select";
import { cn, noProp } from "@/lib/utils";
import SvgChevronDownSmall from "@/icons/chevron-down-small";
import LineItem, { LineItemProps } from "@/refresh-components/buttons/LineItem";
import Text from "@/refresh-components/texts/Text";
import { SvgProps } from "@/icons";

// ============================================================================
// Style Variants
// ============================================================================

const triggerClasses = {
  main: [
    "bg-background-neutral-00",
    "border",
    "hover:border-border-02",
    "active:!border-border-05",
  ],
  error: ["bg-background-neutral-00", "border", "border-status-error-05"],
  disabled: ["bg-background-neutral-03", "border", "cursor-not-allowed"],
} as const;

const iconClasses = {
  main: ["stroke-text-03"],
  error: ["stroke-text-03"],
  disabled: ["stroke-text-01"],
} as const;

const textClasses = {
  main: ["text-text-04"],
  error: ["text-text-04"],
  disabled: ["text-text-01"],
} as const;

type SelectVariant = keyof typeof triggerClasses;

// ============================================================================
// Context
// ============================================================================

interface ItemRegistration {
  value: string;
  children: React.ReactNode;
  icon?: React.FunctionComponent<SvgProps>;
}

interface InputSelectContextValue {
  variant: SelectVariant;
  currentValue?: string;
  disabled?: boolean;
  registerItem: (item: ItemRegistration) => void;
  unregisterItem: (value: string) => void;
  getItem: (value: string) => ItemRegistration | undefined;
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
    const variant: SelectVariant = disabled
      ? "disabled"
      : error
        ? "error"
        : "main";

    // Support both controlled and uncontrolled modes
    const isControlled = value !== undefined;
    const [internalValue, setInternalValue] = React.useState<
      string | undefined
    >(defaultValue);
    const currentValue = isControlled ? value : internalValue;

    React.useEffect(() => {
      if (!isControlled) {
        setInternalValue(defaultValue);
      }
    }, [defaultValue, isControlled]);

    const handleValueChange = React.useCallback(
      (nextValue: string) => {
        if (!isControlled) {
          setInternalValue(nextValue);
        }
        onValueChange?.(nextValue);
      },
      [isControlled, onValueChange]
    );

    // Item registry for displaying selected item with icon in trigger
    // Using useState instead of useRef so registration triggers re-renders
    const [items, setItems] = React.useState<Map<string, ItemRegistration>>(
      () => new Map()
    );

    const registerItem = React.useCallback((item: ItemRegistration) => {
      setItems((prev) => {
        const next = new Map(prev);
        next.set(item.value, item);
        return next;
      });
    }, []);

    const unregisterItem = React.useCallback((value: string) => {
      setItems((prev) => {
        const next = new Map(prev);
        next.delete(value);
        return next;
      });
    }, []);

    const getItem = React.useCallback(
      (value: string) => {
        return items.get(value);
      },
      [items]
    );

    const contextValue = React.useMemo<InputSelectContextValue>(
      () => ({
        variant,
        currentValue,
        disabled,
        registerItem,
        unregisterItem,
        getItem,
      }),
      [variant, currentValue, disabled, registerItem, unregisterItem, getItem]
    );

    return (
      <InputSelectContext.Provider value={contextValue}>
        <SelectPrimitive.Root
          value={currentValue}
          defaultValue={defaultValue}
          onValueChange={handleValueChange}
          disabled={disabled}
          {...props}
        >
          <div ref={ref} className={className}>
            {children}
          </div>
        </SelectPrimitive.Root>
      </InputSelectContext.Provider>
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
  const { variant, currentValue, getItem } = useInputSelectContext();

  const selectedItem = currentValue ? getItem(currentValue) : undefined;

  const displayContent = React.useMemo(() => {
    if (!selectedItem) {
      if (!placeholder) {
        return <Text text03>Select an option</Text>;
      }
      return typeof placeholder === "string" ? (
        <Text text03>{placeholder}</Text>
      ) : (
        placeholder
      );
    }

    const Icon = selectedItem.icon;
    return (
      <div className="flex flex-row items-center gap-2 flex-1">
        {Icon && <Icon className={cn("h-4 w-4", iconClasses[variant])} />}
        <Text className={cn(textClasses[variant])}>
          {selectedItem.children}
        </Text>
      </div>
    );
  }, [selectedItem, placeholder, variant]);

  return (
    <SelectPrimitive.Trigger
      ref={ref}
      className={cn(
        "group/InputSelect flex w-full items-center justify-between p-1.5 rounded-08",
        triggerClasses[variant],
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
      <SelectPrimitive.Viewport>{children}</SelectPrimitive.Viewport>
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
  const { currentValue, registerItem, unregisterItem } =
    useInputSelectContext();
  const isSelected = value === currentValue;

  // Use refs to capture latest children/icon without triggering effect re-runs
  const childrenRef = React.useRef(children);
  const iconRef = React.useRef(icon);
  childrenRef.current = children;
  iconRef.current = icon;

  // Register this item so the trigger can display it when selected
  // Only re-register when value changes to avoid infinite loops with unstable children references
  React.useEffect(() => {
    registerItem({
      value,
      children: childrenRef.current,
      icon: iconRef.current,
    });
    return () => unregisterItem(value);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [value, registerItem, unregisterItem]);

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
        heavyForced={isSelected}
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
 * ```
 */
export default Object.assign(InputSelectRoot, {
  Trigger: InputSelectTrigger,
  Content: InputSelectContent,
  Item: InputSelectItem,
});

export {
  type InputSelectRootProps,
  type InputSelectTriggerProps,
  type InputSelectContentProps,
  type InputSelectItemProps,
};
