"use client";

/**
 * SingleDropdown — the single-arity implementation behind the family's two
 * public components. Internal to Opal; app code uses `InputSingleSelect`
 * (button trigger) or `InputSingleComboBox` (type-in trigger).
 *
 * An input-shaped trigger on `@opal/Dropdown`: the list, its keyboard,
 * search, groups and folding are the dropdown's; this file owns the field,
 * the value and what a pick means.
 *
 * - `trigger="type-in"` (ComboBox): typing filters the option set.
 *   `mode="closed"` permits only option values; `mode="open"` also commits
 *   the raw text via the create row.
 * - `trigger="button"` (Select): nothing to type; a second click closes it.
 *
 * Either opens on click, Enter or ArrowDown, and a ComboBox on typing too.
 * Focus alone never opens the list, so tabbing through a form passes by.
 *
 * Re-picking the selected option unselects it. A Select may carry a
 * `defaultOption`, and then never reads as empty: an empty value resolves to
 * it and re-picking any option is a no-op, like a native `<select>`. A
 * ComboBox takes none: its text is the filter, and a default would pre-fill
 * it with a label the user never chose. Either way `placeholder` names the
 * field for assistive technology.
 *
 * With no options a ComboBox degrades to a plain input.
 */

import "@opal/components/inputs/dropdowns/single/styles.css";
import React, {
  useCallback,
  useContext,
  useMemo,
  useState,
  useId,
  useEffect,
} from "react";
import { useOpalStrings } from "@opal/strings";
import { InputTypeIn } from "@opal/components";
import { FieldContext } from "@opal/form";
import { FieldMessage } from "@opal/form";
import { Dropdown } from "@opal/components/dropdown/components";
import { useDropdownContext } from "@opal/components/dropdown/context";
import type {
  DropdownItem,
  DropdownOption,
} from "@opal/components/dropdown/types";
import { SelectChevron } from "@opal/components/inputs/dropdowns/SelectChevron";
import {
  flattenOptions,
  toDropdownItems,
} from "@opal/components/inputs/dropdowns/utils";
import { useValidation } from "./validation";
import type { SingleDropdownProps } from "../types";
import type { WithoutStyles } from "@opal/types";

function SingleDropdown(props: WithoutStyles<SingleDropdownProps>) {
  const fieldContext = useContext(FieldContext);
  const autoId = useId();
  const fieldId = fieldContext?.baseId || props.name || `combo-box-${autoId}`;
  return (
    <Dropdown id={fieldId} disabled={props.disabled ?? false}>
      <SingleDropdownField {...props} fieldId={fieldId} />
    </Dropdown>
  );
}

function SingleDropdownField({
  fieldId,
  value,
  onChange,
  onValueChange,
  options: optionsProp,
  trigger,
  mode = "closed",
  defaultOption,
  disabled = false,
  placeholder,
  isError: externalIsError,
  onValidationError,
  name,
  searchIcon = false,
  rightChildren,
  separatorLabel,
  showOtherOptions = false,
  dropdownMaxHeight,
  search = false,
  onSearchChange,
  onReachEnd,
  ...rest
}: WithoutStyles<SingleDropdownProps> & { fieldId: string }) {
  const typeIn = trigger === "type-in";
  // A button trigger has no text to commit, so its set is always closed.
  const strict = !typeIn || mode !== "open";
  const options = useMemo(() => flattenOptions(optionsProp), [optionsProp]);
  // The value the trigger shows and the dropdown marks: `defaultOption`
  // stands in for an empty value, so the select never reads as empty.
  const effectiveValue = value || defaultOption || "";
  const strings = useOpalStrings();
  const {
    isOpen,
    setIsOpen,
    highlightedIndex,
    setHighlightedIndex,
    setIsKeyboardNav,
    focusTrigger,
    floatingRef,
  } = useDropdownContext();

  // The selection's visible text — the ONLY value-to-text crossing point.
  // A strict set shows nothing for a value outside it (the placeholder, with
  // the validation error); only an open set displays a free-form value.
  const selectedOption = useMemo(
    () => options.find((opt) => opt.value === effectiveValue),
    [options, effectiveValue]
  );
  const selectedLabel = useMemo(() => {
    if (!effectiveValue) return "";
    return selectedOption?.title ?? (strict ? "" : effectiveValue);
  }, [selectedOption, effectiveValue, strict]);

  useEffect(() => {
    if (
      process.env.NODE_ENV !== "production" &&
      defaultOption !== undefined &&
      options.length > 0 &&
      !options.some((opt) => opt.value === defaultOption)
    ) {
      console.warn(
        `InputSingleSelect: defaultOption "${defaultOption}" is not in the option set.`
      );
    }
  }, [defaultOption, options]);

  // Trigger text is ALWAYS display text (a label or the user's filter);
  // `value` is the only value-typed state. Closed, the text mirrors the
  // selection's label; open, only a value-prop change may overwrite it.
  const [inputValue, setInputValue] = useState(selectedLabel);
  useEffect(() => {
    if (!isOpen) setInputValue(selectedLabel);
  }, [selectedLabel, isOpen]);
  useEffect(() => {
    if (isOpen && options.some((opt) => opt.value === effectiveValue)) {
      setInputValue(selectedLabel);
    }
    // Only react to value prop changes while open, not inputValue changes
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [value]);

  // A committed free-form value (open mode, outside the set) appears in the
  // dropdown as a real, selected row — not as a create-row impostor — and
  // re-picking it routes through the toggle-off. It is its own group, so a
  // line separates it from the set.
  const items = useMemo<DropdownItem[]>(() => {
    const set = toDropdownItems(optionsProp);
    if (strict || !effectiveValue) return set;
    if (options.some((opt) => opt.value === effectiveValue)) return set;
    return [
      {
        kind: "group",
        items: [
          { kind: "option", value: effectiveValue, title: effectiveValue },
        ],
      },
      ...set,
    ];
  }, [optionsProp, strict, effectiveValue, options]);

  // What filters the list: a ComboBox's typed text. A Select's search
  // field is the dropdown's own, and a button trigger's text is only ever
  // the selection's label.
  const filterText = typeIn ? inputValue : "";
  const hasSearchTerm = filterText.trim() !== "";

  // The create row offers what ISN'T already offerable: it hides when the
  // text exactly matches an option or the committed free-form value.
  const trimmedInput = filterText.trim().toLowerCase();
  const exactVisibleMatch = useMemo(() => {
    if (!strict && effectiveValue.toLowerCase() === trimmedInput) return true;
    return options.some(
      (opt) =>
        opt.value.toLowerCase() === trimmedInput ||
        opt.title.toLowerCase() === trimmedInput
    );
  }, [strict, effectiveValue, options, trimmedInput]);
  const showCreateOption = !strict && hasSearchTerm && !exactVisibleMatch;

  // Validation Logic
  const { isValid, errorMessage } = useValidation({
    value: effectiveValue,
    options,
    strict,
    externalIsError,
    onValidationError,
  });

  // Event Handlers
  const handleInputChange = useCallback(
    (e: React.ChangeEvent<HTMLInputElement>) => {
      const newValue = e.target.value;
      setInputValue(newValue);
      setInvalidCommit(false);

      // Only call onChange while typing (for controlled input behavior)
      // onValueChange is only called when selecting from dropdown
      onChange?.(e);

      // Open dropdown when user starts typing
      if (!isOpen) {
        setIsOpen(true);
      }

      // Auto-highlight first match when typing
      setHighlightedIndex(0);
      setIsKeyboardNav(false); // Reset keyboard navigation mode when typing
    },
    [onChange, isOpen, setIsOpen, setHighlightedIndex, setIsKeyboardNav]
  );

  // Support both onChange (event) and onValueChange (value) patterns
  const emitValue = useCallback(
    (next: string) => {
      if (onChange) {
        const syntheticEvent = {
          target: { value: next },
          currentTarget: { value: next },
          type: "change",
          bubbles: true,
          cancelable: true,
        } as React.ChangeEvent<HTMLInputElement>;
        onChange(syntheticEvent);
      }
      onValueChange?.(next);
    },
    [onChange, onValueChange]
  );

  const commit = useCallback(
    (nextValue: string, nextLabel: string) => {
      setInputValue(nextLabel);
      emitValue(nextValue);
      setIsOpen(false);
      focusTrigger();
    },
    [emitValue, setIsOpen, focusTrigger]
  );

  const handleOptionSelect = useCallback(
    (option: DropdownOption) => {
      if (option.disabled) return;

      // Re-picking is judged against the committed value, not the displayed
      // one: picking a default that only stands in for an empty value must
      // commit it. Re-picking the committed option then has the multi's
      // symmetry: it unselects, and the dropdown stays open with the filter
      // cleared, ready for a different pick. With a default there is nothing
      // to unselect into, so a re-pick just closes the list, like a native
      // <select>. Both triggers behave the same.
      if (option.value === value && value !== "") {
        if (defaultOption !== undefined) {
          setIsOpen(false);
          focusTrigger();
          return;
        }
        setInputValue("");
        emitValue("");
        setHighlightedIndex(-1);
        focusTrigger();
        return;
      }

      commit(option.value, option.title);
    },
    [
      value,
      defaultOption,
      emitValue,
      setIsOpen,
      setHighlightedIndex,
      focusTrigger,
      commit,
    ]
  );

  // EXPERIMENT(commit-attempt errors): Enter on text matching no option in
  // closed mode flags the error variant and keeps the dropdown open; any
  // typing, selection, or close (blur/outside/Tab already close) clears it,
  // and the close-sync effect drops the invalid text back to the selection.
  const [invalidCommit, setInvalidCommit] = useState(false);
  useEffect(() => {
    if (!isOpen) setInvalidCommit(false);
  }, [isOpen]);

  const toggleDropdown = useCallback(() => {
    if (disabled) return;
    setIsOpen((prev) => {
      const newOpen = !prev;
      if (newOpen) {
        // Type-in clears the filter to show the whole set; a button trigger has
        // no filter and keeps the selection's label.
        if (typeIn) setInputValue("");
        setHighlightedIndex(-1);
      }
      return newOpen;
    });
    focusTrigger();
  }, [disabled, typeIn, setIsOpen, setHighlightedIndex, focusTrigger]);

  return (
    <Dropdown.Anchor asChild>
      <div
        role="presentation"
        className="opal-input-single-select"
        data-trigger={trigger}
        // A button trigger is the whole field, padding included, so the
        // toggle lives on the root; the input inside carries the keyboard,
        // and the chevron and rightChildren stop propagation. The list is
        // portalled, so its clicks bubble here through React's tree too: a
        // foldable title, the search field or the padding must not toggle
        // the list. Only a pick closes it, and the rows do that themselves.
        //
        // A wrapping <label> forwards a click on anything but the input to
        // the input, which would reach here and toggle a second time: a click
        // on the field's padding would open and close at once. Cancelling the
        // click's default action drops the forwarded click; nothing else in
        // here relies on it, since focus moves on mousedown.
        onClick={
          typeIn
            ? undefined
            : (event) => {
                if (
                  event.target instanceof Node &&
                  floatingRef.current?.contains(event.target)
                ) {
                  return;
                }
                event.preventDefault();
                toggleDropdown();
              }
        }
      >
        <Dropdown.Trigger asChild typeIn={typeIn}>
          <InputTypeIn
            name={name}
            placeholder={placeholder}
            aria-label={placeholder}
            aria-invalid={!isValid}
            aria-describedby={!isValid ? `${fieldId}-error` : undefined}
            readOnly={!typeIn}
            // A Select shows the chosen option's icon; a ComboBox's text is
            // typed, so it shows none.
            icon={typeIn ? undefined : selectedOption?.icon}
            value={inputValue}
            onChange={handleInputChange}
            // A button trigger opens on click or ArrowDown and a second click
            // closes it, like a native <select>. A type-in opens on click or
            // typing, with the text kept for editing. Focus alone never opens.
            onClick={() => {
              if (!typeIn) return;
              if (!isOpen) {
                setInputValue(selectedLabel);
                setIsOpen(true);
                setHighlightedIndex(-1);
              }
            }}
            // Runs before the dropdown's own handler, which leaves a
            // cancelled key alone.
            onKeyDown={(event) => {
              if (
                typeIn &&
                event.key === "Enter" &&
                strict &&
                isOpen &&
                highlightedIndex < 0 &&
                inputValue.trim() !== ""
              ) {
                // Commit attempt with nothing selectable: reject visibly.
                event.preventDefault();
                event.stopPropagation();
                setInvalidCommit(true);
              }
            }}
            variant={
              disabled
                ? "disabled"
                : !isValid || invalidCommit
                  ? "error"
                  : undefined
            }
            searchIcon={searchIcon}
            rightChildren={
              <>
                {rightChildren && (
                  // Propagation guard only — the children keep their own
                  // semantics.
                  <div
                    role="presentation"
                    className="flex items-center"
                    onPointerDown={(e) => {
                      e.stopPropagation();
                    }}
                    onClick={(e) => {
                      e.stopPropagation();
                    }}
                  >
                    {rightChildren}
                  </div>
                )}
                <SelectChevron
                  isOpen={isOpen}
                  disabled={disabled}
                  onToggle={toggleDropdown}
                />
              </>
            }
            {...rest}
          />
        </Dropdown.Trigger>

        <Dropdown.Data
          items={items}
          label={placeholder ?? ""}
          query={typeIn ? inputValue : undefined}
          highlightExactQuery={typeIn}
          search={
            search
              ? {
                  placeholder: strings.selectSearchPlaceholder,
                  onChange: onSearchChange,
                }
              : undefined
          }
          value={effectiveValue}
          exactText={typeIn ? inputValue || effectiveValue : effectiveValue}
          onSelect={handleOptionSelect}
          create={
            showCreateOption
              ? {
                  text: filterText.trim(),
                  onCreate: (text) => commit(text, text),
                }
              : undefined
          }
          otherOptionsTitle={
            showOtherOptions
              ? (separatorLabel ?? strings.comboBoxOtherOptions)
              : undefined
          }
          maxHeight={dropdownMaxHeight}
          onReachEnd={onReachEnd}
        />

        {/* Error message - only show internal error messages when not using external isError */}
        {!isValid && errorMessage && externalIsError === undefined && (
          <FieldMessage variant="error" className="ms-0.5 mt-1">
            <FieldMessage.Content
              id={`${fieldId}-error`}
              role="alert"
              className="ms-0.5"
            >
              {errorMessage}
            </FieldMessage.Content>
          </FieldMessage>
        )}
      </div>
    </Dropdown.Anchor>
  );
}

export { SingleDropdown };
