"use client";

import { useImperativeHandle, type KeyboardEvent, type Ref } from "react";
import { useTranslations } from "next-intl";
import { InputTypeIn } from "@opal/components";
import { useSearchField } from "@opal/hooks";

export interface SearchFieldHandle {
  /**
   * Moves focus to the field, with the caret at the end. A value passed in
   * replaces the current text first.
   */
  focus: (nextValue?: string) => void;
}

export interface SearchFieldProps {
  value: string;
  onChange: (value: string) => void;
  /**
   * A full translated sentence, such as "Search plugins or press "/" to
   * focus...". Defaults to the generic one.
   */
  placeholder?: string;
  "aria-label"?: string;
  /** Focus the field when it mounts. @default true */
  focusOnMount?: boolean;
  /** The hotkey that returns focus to the field; `null` binds none. @default "/" */
  hotkey?: string | null;
  /**
   * Keys from anywhere in the field, its × button included. Runs after the
   * field's own Escape handling, unless that handled the key.
   */
  onKeyDown?: (event: KeyboardEvent<HTMLElement>) => void;
  ref?: Ref<SearchFieldHandle>;
}

/**
 * A page's main search field: focused on arrival, cleared and then left with
 * Escape, focused again with "/", and cleared with its × button.
 */
export default function SearchField({
  value,
  onChange,
  placeholder,
  "aria-label": ariaLabel,
  focusOnMount,
  hotkey,
  onKeyDown,
  ref,
}: SearchFieldProps) {
  const t = useTranslations("common.searchField");
  const search = useSearchField({ value, onChange, focusOnMount, hotkey });

  useImperativeHandle(ref, () => ({ focus: search.focus }), [search.focus]);

  return (
    // `InputTypeIn`'s own `onKeyDown` sees only the text field; this wrapper
    // also hears the × button.
    <div
      role="presentation"
      className="contents"
      onKeyDown={(event) => {
        if (event.defaultPrevented) return;
        onKeyDown?.(event);
      }}
    >
      <InputTypeIn
        ref={search.ref}
        type="text"
        searchIcon
        clearButton
        value={value}
        onChange={(event) => onChange(event.target.value)}
        onKeyDown={search.onKeyDown}
        placeholder={placeholder ?? t("placeholder")}
        aria-label={ariaLabel}
      />
    </div>
  );
}
