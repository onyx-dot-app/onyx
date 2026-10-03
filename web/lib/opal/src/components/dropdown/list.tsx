"use client";

import React, { forwardRef, useEffect, useRef } from "react";
import { createPortal } from "react-dom";
import { cn } from "@opal/utils";
import { useOpalStrings } from "@opal/strings";
import usePresence from "@opal/hooks/usePresence";
import { ShadowDiv } from "@opal/components/shadow-div/components";
import InputTypeIn from "@opal/components/inputs/texts/input-type-in/components";
import { Divider } from "@opal/components/divider/components";
import { Text } from "@opal/components/text/components";
import { LineItemButton } from "@opal/components/buttons/line-item-button/components";
import { SvgPlus } from "@opal/icons";
import {
  groupElementId,
  rowElementId,
  rowKey,
} from "@opal/components/dropdown/model";
import { Row } from "@opal/components/dropdown/rows";
import type { DropdownWidth } from "@opal/components/dropdown/hooks";
import type {
  DropdownMode,
  DropdownRow,
  RowGroup,
} from "@opal/components/dropdown/types";

interface DropdownListProps {
  listId: string;
  mode: DropdownMode;
  width: DropdownWidth;
  container: HTMLElement | null | undefined;
  isOpen: boolean;
  disabled: boolean;
  /** The list's accessible name. */
  label: string;
  floatingStyles: React.CSSProperties;
  /**
   * floating-ui has placed and sized the box. Until then the rows lay out
   * at the wrong width, so anything measured against them is off.
   */
  isPositioned: boolean;
  setFloatingRef: (node: HTMLDivElement | null) => void;
  /** Post-filter, post-fold groups in render order. */
  groups: RowGroup[];
  /** The supplied set itself is empty, not merely filtered out. */
  emptySet: boolean;
  isSelected: (row: DropdownRow) => boolean;
  /** One more row that reads as selected: the trigger text's exact match. */
  exactValue: string | undefined;
  highlightedIndex: number;
  /**
   * The keyboard drives the highlight. Only then does the list scroll to
   * keep the highlighted row in view; a pointer moving over rows must never
   * scroll the list under itself.
   */
  keyboardNav: boolean;
  onActivate: (row: DropdownRow) => void;
  onToggleGroup: (group: RowGroup) => void;
  /** The pointer moved inside the list: the keyboard highlight yields. */
  onMouseMove: () => void;
  create?: { text: string; onCreate: (text: string) => void };
  maxHeight?: string;
  /** The rows scrolled to within SCROLL_END_THRESHOLD_PX of their end. */
  onReachEnd?: () => void;
  /**
   * A search field pinned above the rows. It takes focus when the list
   * opens; the key handler is the trigger's, so arrows, Enter, Escape and
   * Tab behave the same from either.
   */
  searchField?: {
    value: string;
    placeholder: string;
    onChange: (value: string) => void;
    onKeyDown: (event: React.KeyboardEvent<HTMLElement>) => void;
  };
}

const SCROLL_END_THRESHOLD_PX = 48;

const WIDTH_CLASSES: Record<DropdownWidth, string | undefined> = {
  anchor: undefined,
  sm: "w-40",
  md: "w-48",
  lg: "w-60",
  xl: "w-72",
};

/**
 * The list in a portal: the box, the search field, the groups with their
 * dividers, the create row and the rows. Scrolls the keyboard stop into
 * view and opens around the selection.
 */
export const DropdownList = forwardRef<HTMLDivElement, DropdownListProps>(
  (
    {
      listId,
      mode,
      width,
      container,
      isOpen,
      disabled,
      label,
      floatingStyles,
      isPositioned,
      setFloatingRef,
      groups,
      emptySet,
      isSelected,
      exactValue,
      highlightedIndex,
      keyboardNav,
      onActivate,
      onToggleGroup,
      onMouseMove,
      create,
      maxHeight,
      onReachEnd,
      searchField,
    },
    ref
  ) => {
    const strings = useOpalStrings();
    // The list stays mounted one exit animation longer than `isOpen`, so it
    // can animate out without living in the tree while closed.
    const presence = usePresence(isOpen);

    // The search field takes focus when the list opens, so typing starts at
    // once. An effect rather than autoFocus: the field mounts with the list,
    // and focus must follow every open, not only the first mount.
    const searchRef = useRef<HTMLInputElement>(null);
    const hasSearch = searchField !== undefined;
    useEffect(() => {
      if (isOpen && hasSearch) searchRef.current?.focus();
    }, [isOpen, hasSearch]);

    const listRef = useRef<HTMLDivElement | null>(null);

    // Keyboard navigation keeps the highlighted row in view. Pointer
    // highlights never scroll: the list must not move under the mouse.
    useEffect(() => {
      if (!isOpen || !keyboardNav || highlightedIndex < 0) return;
      const stop = listRef.current?.querySelector(
        `[data-index="${highlightedIndex}"]`
      );
      // A foldable group's stop is its wrapper, title and rows together;
      // "nearest" is satisfied while any of that tall block shows, so
      // scroll the title itself.
      const highlighted = stop?.classList.contains("opal-dropdown-group")
        ? stop.firstElementChild
        : stop;
      highlighted?.scrollIntoView({ block: "nearest", behavior: "instant" });
    }, [highlightedIndex, isOpen, keyboardNav]);

    // Opening shows the selection: the (first) selected row is centred in
    // view, so a long list opens around the current value. Waits for
    // floating-ui to size the box: before that the rows lay out single-line
    // at the wrong width, the centre is computed on those heights, and the
    // selection lands below the fold once the descriptions wrap.
    useEffect(() => {
      if (!isOpen || !isPositioned) return;
      const selected = listRef.current?.querySelector(
        '[role="option"][aria-selected="true"]'
      );
      selected?.scrollIntoView({ block: "center", behavior: "instant" });
    }, [isOpen, isPositioned]);

    if (!presence.mounted || disabled || typeof document === "undefined") {
      return null;
    }

    const totalRows = groups.reduce(
      (count, group) => count + group.rows.length,
      0
    );

    return createPortal(
      // oxlint-disable-next-line jsx-a11y/no-static-element-interactions -- the role is always listbox or menu; the rule cannot read a ternary
      <div
        ref={(node) => {
          listRef.current = node;
          setFloatingRef(node);
          if (typeof ref === "function") ref(node);
          else if (ref) ref.current = node;
        }}
        id={`${listId}-listbox`}
        role={mode === "picker" ? "listbox" : "menu"}
        tabIndex={-1}
        aria-label={label}
        // Closed while exiting: invisible to AT and to the pointer.
        aria-hidden={presence.state === "closed" || undefined}
        data-state={presence.state}
        // Highlighting is modal: while the keyboard drives it, rows and
        // titles ignore the pointer so no hover paints beside the keyboard
        // stop. The first pointer movement hands control back.
        data-keyboard-nav={keyboardNav || undefined}
        onMouseMove={onMouseMove}
        className={cn("opal-dropdown", WIDTH_CLASSES[width])}
        style={floatingStyles}
        onAnimationEnd={presence.onAnimationEnd}
        onMouseDown={(e) => {
          // Clicks on padding, gaps, or dividers must not steal focus from
          // the trigger (the list is tabIndex={-1} for AT only).
          e.preventDefault();
        }}
        onWheel={(e) => {
          // Scroll here, not in whatever sits behind the portal.
          e.stopPropagation();
        }}
        onTouchMove={(e) => {
          e.stopPropagation();
        }}
      >
        {searchField && (
          <div
            role="presentation"
            className="opal-dropdown-search"
            // The list root cancels mousedown to keep focus on the trigger;
            // a click into the search field must focus it. The click is held
            // too: React bubbles through the portal, and a trigger root's
            // click would pull focus straight back.
            onMouseDown={(e) => e.stopPropagation()}
            onClick={(e) => e.stopPropagation()}
          >
            <InputTypeIn
              ref={searchRef}
              searchIcon
              variant="internal"
              placeholder={searchField.placeholder}
              aria-label={searchField.placeholder}
              value={searchField.value}
              onChange={(e) => searchField.onChange(e.target.value)}
              onKeyDown={searchField.onKeyDown}
            />
          </div>
        )}
        <ShadowDiv
          shadowHeight={3}
          // Fade the rows themselves at the scroll edges. A painted shadow
          // sat on top of the rows and read as a smudge on the light surface.
          variant="mask"
          // The rise-and-settle runs on this non-scrolling wrapper: a
          // transform on the scroller itself makes Chromium repaint it at
          // scroll offset 0 for a frame when compositing switches.
          containerClassName="opal-dropdown-content"
          className={cn("opal-dropdown-scroll", !maxHeight && "max-h-60")}
          style={{
            // Scroll independently of whatever sits behind the portal.
            overscrollBehavior: "contain",
            maxHeight: maxHeight || undefined,
          }}
          onScroll={(e) => {
            const el = e.currentTarget;
            const remaining = el.scrollHeight - el.scrollTop - el.clientHeight;
            if (remaining <= SCROLL_END_THRESHOLD_PX) onReachEnd?.();
          }}
        >
          {totalRows === 0 && !create ? (
            // An empty SET gets the icon'd empty state; a filter that
            // matched nothing keeps the lightweight text row.
            emptySet ? (
              <div className="opal-dropdown-empty-set">
                <Text as="p" color="text-03" font="secondary-body">
                  {strings.selectEmptySet}
                </Text>
              </div>
            ) : (
              <div className="opal-dropdown-no-match">
                {strings.comboBoxNoOptions}
              </div>
            )
          ) : (
            <Rows
              listId={listId}
              mode={mode}
              groups={groups}
              isSelected={isSelected}
              exactValue={exactValue}
              highlightedIndex={highlightedIndex}
              onActivate={onActivate}
              onToggleGroup={onToggleGroup}
              create={create}
            />
          )}
        </ShadowDiv>
      </div>,
      container ?? document.body
    );
  }
);

DropdownList.displayName = "DropdownList";

// ---------------------------------------------------------------------------
// Rows
// ---------------------------------------------------------------------------

interface RowsProps {
  listId: string;
  mode: DropdownMode;
  groups: RowGroup[];
  isSelected: (row: DropdownRow) => boolean;
  exactValue: string | undefined;
  highlightedIndex: number;
  onActivate: (row: DropdownRow) => void;
  onToggleGroup: (group: RowGroup) => void;
  create?: { text: string; onCreate: (text: string) => void };
}

/**
 * The grouped rows: a titled Divider above each titled group, plain rows
 * for loose rows, and the create row pinned first. The stops are numbered
 * in render order, the same order the keyboard walks.
 */
function Rows({
  listId,
  mode,
  groups,
  isSelected,
  exactValue,
  highlightedIndex,
  onActivate,
  onToggleGroup,
  create,
}: RowsProps) {
  const strings = useOpalStrings();
  let index = create ? 1 : 0;

  return (
    <>
      {create && (
        <LineItemButton
          presentational
          selectVariant="select-heavy"
          interaction={highlightedIndex === 0 ? "hover" : "rest"}
          rounding={2}
          title={create.text}
          sizePreset="main-ui"
          variant="body"
          rightChildren={<SvgPlus className="opal-dropdown-create-icon" />}
          id={rowElementId(listId, create.text)}
          data-index={0}
          role={mode === "picker" ? "option" : "menuitem"}
          tabIndex={-1}
          {...(mode === "picker" && { "aria-selected": false })}
          aria-label={strings.comboBoxCreateOption(
            strings.comboBoxCreate,
            create.text
          )}
          onClick={(e) => {
            e.stopPropagation();
            create.onCreate(create.text);
          }}
          onMouseDown={(e) => {
            e.preventDefault();
          }}
        />
      )}

      {/* A line separates consecutive groups; it carries the group's title
          when it has one. A titled first group keeps its title line. */}
      {groups.map((group, groupIndex) => {
        const isFoldable = group.foldable && group.title !== undefined;
        // The title claims its stop before the rows claim theirs.
        const headerIndex = isFoldable ? index++ : -1;
        // A folded group's rows stay mounted for the fold animation but
        // hold no keyboard stop: no index, no highlight.
        const rows = group.rows.map((row) => {
          const rowIndex = group.folded ? -1 : index++;
          return (
            <Row
              key={rowKey(row)}
              listId={listId}
              mode={mode}
              row={row}
              index={rowIndex}
              isHighlighted={rowIndex >= 0 && rowIndex === highlightedIndex}
              isSelected={
                isSelected(row) ||
                (!group.folded &&
                  row.kind === "option" &&
                  row.value === exactValue)
              }
              onActivate={onActivate}
            />
          );
        });
        // A foldable group's title is its fold control and a keyboard stop
        // of its own; its rows are its children, withheld while folded.
        if (isFoldable && group.title !== undefined) {
          return (
            <div
              key={groupIndex}
              // Plumbing only: the id for aria-activedescendant and the
              // index for scroll-into-view. Hover and press styling are the
              // Divider's own Interactive.
              id={groupElementId(listId, group.title)}
              role="presentation"
              className="opal-dropdown-group"
              data-index={headerIndex}
            >
              <Divider
                title={group.title}
                foldable
                open={!group.folded}
                onOpenChange={() => onToggleGroup(group)}
                // Only the keyboard stop reads as hover; an open title stays
                // at rest, unlike a standalone foldable Divider.
                interaction={
                  headerIndex === highlightedIndex ? "hover" : "rest"
                }
              >
                <div className="opal-dropdown-group-rows">{rows}</div>
              </Divider>
            </div>
          );
        }
        return (
          <React.Fragment key={groupIndex}>
            {group.title !== undefined ? (
              <Divider title={group.title} />
            ) : (
              groupIndex > 0 && <Divider />
            )}
            {rows}
          </React.Fragment>
        );
      })}
    </>
  );
}
