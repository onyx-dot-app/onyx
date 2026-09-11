"use client";

import "@opal/components/inputs/shared.css";
// The inner field reuses InputTypeIn's .opal-input-field styling.
import "@opal/components/inputs/input-type-in/styles.css";
import "@opal/components/inputs/selections/input-multi-select/styles.css";
import {
  useCallback,
  useEffect,
  useId,
  useMemo,
  useRef,
  useState,
} from "react";
import {
  useFloating,
  autoUpdate,
  flip,
  offset,
  shift,
  size,
} from "@floating-ui/react-dom";
import type { IconFunctionComponent } from "@opal/types";
import { Button, Tag, TAG_REMOVE_CLASS } from "@opal/components";
import { SvgX } from "@opal/icons";
import { useOpalStrings } from "@opal/strings";
import { useClickOutside } from "@opal/hooks/useClickOutside";
import {
  filterSections,
  flattenSections,
  normalizeSections,
  useSelectKeyboard,
} from "../shared";
import { SelectDropdown } from "../dropdown/SelectDropdown";
import { buildAriaAttributes } from "../dropdown/aria";
import type { SelectOption, SelectSection } from "../types";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

interface TagItem {
  id: string;
  label: string;

  /** Shows the warning indicator on the tag. */
  error?: boolean;
}

/**
 * Supplying `options` requires `onSelectOption`: without a handler a chosen
 * option would vanish (nothing writes it into `tags`), so the pairing is
 * enforced where it can't be forgotten — the types.
 */
type InputMultiSelectOptionsProps =
  | {
      options?: never;
      onSelectOption?: never;
      mode?: never;
      createPrefix?: never;
      dropdownMaxHeight?: never;
    }
  | {
      /**
       * The selectable set; enables the family dropdown. Flat or sectioned —
       * sections render with a Divider between them. Convention: a chosen
       * option becomes a tag whose `id` is the option's `value`, so the
       * dropdown can show it selected and toggle it off.
       */
      options: SelectOption[] | SelectSection[];

      /**
       * Called when a dropdown option is chosen. Choosing an already-selected
       * option calls `onRemoveTag(option.value)` instead — one removal path.
       */
      onSelectOption: (option: SelectOption) => void;

      /**
       * Set openness:
       * - "closed" (default): only options can be chosen; typing filters.
       * - "open": typing filters AND the raw text commits via the create row.
       */
      mode?: "closed" | "open";

      /** Prefix shown before the typed value in the create row (e.g. "Add"). */
      createPrefix?: string;

      /** Max height of the dropdown in CSS units. Defaults to "15rem". */
      dropdownMaxHeight?: string;
    };

interface InputMultiSelectBaseProps {
  /** Tags rendered before the text input. */
  tags: TagItem[];

  onRemoveTag: (id: string) => void;

  /** Called with the trimmed input text on Enter (no-op when empty). */
  onAdd: (value: string) => void;

  /** Controlled input text. */
  value: string;

  onChange: (value: string) => void;

  placeholder?: string;

  /**
   * Wrapper chrome variant. `"internal"` is the borderless Figma
   * `Style=Subtle` look.
   */
  variant?: "primary" | "internal" | "error";

  /** Dims the field, disables the input, hides the remove and clear buttons. */
  disabled?: boolean;

  /** Leading icon. */
  icon?: IconFunctionComponent;

  /** Renders the clear action button (Figma `Clear`). */
  onClear?: () => void;

  /** Tag rows the field is tall enough to show before it grows. */
  minRows?: number;

  /** Focuses the text input on mount. */
  focusOnMount?: boolean;
}

type InputMultiSelectProps = InputMultiSelectBaseProps &
  InputMultiSelectOptionsProps;

// ---------------------------------------------------------------------------
// InputMultiSelect
// ---------------------------------------------------------------------------

/**
 * The multi-arity member of the input-select family: chips-in-input (Figma
 * `Input/Tags`) over the family's unified dropdown. Typing filters the
 * option set; chosen options render as Tags. Backspace on an empty input
 * arms the last tag, and Backspace or Delete on an armed tag removes it.
 *
 * Without `options` it is the plain free-tagging input it always was.
 */
function InputMultiSelect({
  tags,
  onRemoveTag,
  onAdd,
  value,
  onChange,
  options: optionsProp,
  mode = "closed",
  onSelectOption,
  placeholder,
  variant = "primary",
  disabled = false,
  icon: Icon,
  onClear,
  minRows = 1,
  focusOnMount = false,
  createPrefix,
  dropdownMaxHeight,
}: InputMultiSelectProps) {
  const rootRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLInputElement>(null);
  const dropdownRef = useRef<HTMLDivElement>(null);
  const strings = useOpalStrings();

  const sections = useMemo(
    () => normalizeSections(optionsProp ?? []),
    [optionsProp]
  );
  const flatOptions = useMemo(() => flattenSections(sections), [sections]);
  const hasOptions = flatOptions.length > 0;
  // The prop's PRESENCE is the contract: an empty or still-loading closed
  // set must not fall open. Only an absent prop means legacy free tagging.
  const hasOptionSet = optionsProp !== undefined;
  const freeEntry = mode === "open" || !hasOptionSet;

  const selectedValues = useMemo(
    () => new Set(tags.map((tag) => tag.id)),
    [tags]
  );

  // Dropdown state (local: the input text itself is caller-controlled).
  const [isOpen, setIsOpen] = useState(false);
  const [highlightedIndex, setHighlightedIndex] = useState(-1);
  const [isKeyboardNav, setIsKeyboardNav] = useState(false);
  useEffect(() => {
    if (!isOpen) {
      setHighlightedIndex(-1);
      setIsKeyboardNav(false);
    }
  }, [isOpen]);

  const hasSearchTerm = value.trim() !== "";
  const visibleSections = useMemo(
    () => filterSections(sections, value),
    [sections, value]
  );
  const trimmedValue = value.trim().toLowerCase();
  // An exact match means Enter should pick the option, not fork a free-form
  // duplicate of it.
  const exactOptionMatch = flatOptions.some(
    (option) =>
      option.value.toLowerCase() === trimmedValue ||
      option.label.toLowerCase() === trimmedValue
  );
  const showCreateOption =
    mode === "open" && hasOptions && hasSearchTerm && !exactOptionMatch;

  const allVisibleOptions = useMemo(() => {
    const baseOptions = flattenSections(visibleSections);
    if (showCreateOption) {
      return [{ value, label: value }, ...baseOptions];
    }
    return baseOptions;
  }, [visibleSections, showCreateOption, value]);

  const { refs, floatingStyles } = useFloating({
    open: isOpen,
    placement: "bottom-start",
    middleware: [
      offset(4),
      flip(),
      shift({ padding: 8 }),
      size({
        apply({ rects, elements }) {
          Object.assign(elements.floating.style, {
            width: `${rects.reference.width}px`,
          });
        },
      }),
    ],
    whileElementsMounted: autoUpdate,
  });

  const handleOptionSelect = useCallback(
    (option: SelectOption) => {
      if (option.disabled) return;
      const real = flatOptions.find((o) => o.value === option.value);
      if (real) {
        if (selectedValues.has(real.value)) {
          onRemoveTag(real.value);
        } else {
          onSelectOption?.(real);
        }
      } else {
        // The create row: commit the raw text as a free-form tag.
        const trimmed = option.value.trim();
        if (trimmed) onAdd(trimmed);
      }
      // Stay open for further picks; reset the filter.
      onChange("");
      inputRef.current?.focus();
    },
    [flatOptions, selectedValues, onRemoveTag, onSelectOption, onAdd, onChange]
  );

  const { handleKeyDown: handleDropdownKeyDown } = useSelectKeyboard({
    isOpen,
    setIsOpen,
    highlightedIndex,
    setHighlightedIndex,
    setIsKeyboardNav,
    allVisibleOptions,
    onSelect: handleOptionSelect,
    hasOptions,
  });

  useClickOutside<HTMLElement>(
    [
      rootRef as React.RefObject<HTMLElement>,
      dropdownRef as React.RefObject<HTMLElement>,
    ],
    useCallback(() => {
      setIsOpen(false);
      setIsKeyboardNav(false);
    }, []),
    isOpen
  );

  useEffect(() => {
    if (focusOnMount) inputRef.current?.focus();
    // Mount only: later prop changes must not steal focus back.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  function handleInputKeyDown(event: React.KeyboardEvent<HTMLInputElement>) {
    // During IME composition, Enter confirms the candidate and Backspace
    // edits the composition. Neither may add or arm tags.
    if (event.nativeEvent.isComposing) return;

    if (hasOptions) {
      handleDropdownKeyDown(event);
      if (event.defaultPrevented) return;
    }

    if (event.key === "Enter") {
      event.preventDefault();
      event.stopPropagation();
      // With an option set, Enter belongs to the dropdown (the create row
      // covers free-form commits); the plain add only serves the optionless
      // input.
      if (hasOptionSet) return;
      if (!freeEntry) return;
      const trimmed = value.trim();
      if (trimmed) onAdd(trimmed);
      return;
    }
    if (event.key === "Backspace" && value === "" && tags.length > 0) {
      event.preventDefault();
      const removes = rootRef.current?.querySelectorAll<HTMLButtonElement>(
        `.${TAG_REMOVE_CLASS}`
      );
      removes?.[removes.length - 1]?.focus();
    }
  }

  // Backspace/Delete on an armed remove button deletes its tag. Enter and
  // Space already work as native button activation.
  function handleRootKeyDown(event: React.KeyboardEvent<HTMLDivElement>) {
    if (event.key !== "Backspace" && event.key !== "Delete") return;
    const target = event.target as HTMLElement;
    if (!target.classList.contains(TAG_REMOVE_CLASS)) return;
    event.preventDefault();
    target.click();
  }

  const autoId = useId();
  const fieldId = `multi-select-${autoId}`;
  const ariaProps = buildAriaAttributes({
    hasOptions,
    isOpen,
    isValid: true,
    highlightedIndex,
    fieldId,
    allVisibleOptions,
    placeholder: placeholder ?? "",
  });

  return (
    <div
      ref={(node) => {
        rootRef.current = node;
        refs.setReference(node);
      }}
      role="presentation"
      className="opal-input opal-input-multi-select"
      data-variant={disabled ? "disabled" : variant}
      onKeyDown={handleRootKeyDown}
      onClick={() => inputRef.current?.focus()}
    >
      {Icon && (
        <div className="opal-input-multi-select-icon-container">
          <Icon className="opal-input-multi-select-icon" />
        </div>
      )}
      <div
        className="opal-input-multi-select-tags"
        data-multi-row={minRows > 1 || undefined}
        style={
          minRows > 1
            ? ({
                "--opal-input-multi-select-rows": minRows,
              } as React.CSSProperties)
            : undefined
        }
      >
        {tags.map((tag) => (
          <Tag
            key={tag.id}
            size="md"
            title={tag.label}
            error={tag.error}
            disabled={disabled}
            onRemove={() => {
              onRemoveTag(tag.id);
              inputRef.current?.focus();
            }}
          />
        ))}
        {/* raw-ok: nesting InputTypeIn double-pads the composite chrome, so the inner field reuses InputTypeIn's .opal-input-field styling directly */}
        <input
          ref={inputRef}
          type="text"
          className="opal-input-field opal-input-multi-select-field"
          disabled={disabled}
          value={value}
          onChange={(event) => {
            onChange(event.target.value);
            if (hasOptions && !isOpen) setIsOpen(true);
            setHighlightedIndex(0);
            setIsKeyboardNav(false);
          }}
          onFocus={() => {
            if (hasOptions) setIsOpen(true);
          }}
          onKeyDown={handleInputKeyDown}
          placeholder={placeholder}
          {...ariaProps}
        />
      </div>
      {onClear !== undefined && !disabled && (
        <Button
          prominence="internal"
          icon={SvgX}
          size="xs"
          tooltip={strings.clear}
          onClick={(event) => {
            event.stopPropagation();
            onClear();
          }}
        />
      )}

      <SelectDropdown
        ref={dropdownRef}
        isOpen={isOpen && hasOptions}
        disabled={disabled}
        floatingStyles={floatingStyles}
        setFloatingRef={refs.setFloating}
        fieldId={fieldId}
        placeholder={placeholder ?? ""}
        sections={visibleSections}
        value=""
        selectedValues={selectedValues}
        highlightedIndex={highlightedIndex}
        onSelect={handleOptionSelect}
        onMouseEnter={(index) => {
          setIsKeyboardNav(false);
          setHighlightedIndex(index);
        }}
        onMouseMove={() => {
          if (isKeyboardNav) setIsKeyboardNav(false);
        }}
        onMouseLeave={() => {
          if (!isKeyboardNav) setHighlightedIndex(-1);
        }}
        isExactMatch={(option) => selectedValues.has(option.value)}
        markAllMatches
        inputValue={value}
        allowCreate={freeEntry}
        showCreateOption={showCreateOption}
        createPrefix={createPrefix}
        dropdownMaxHeight={dropdownMaxHeight}
      />
    </div>
  );
}

export { InputMultiSelect, type InputMultiSelectProps, type TagItem };
