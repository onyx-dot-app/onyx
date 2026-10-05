"use client";

import React, {
  forwardRef,
  useEffect,
  useLayoutEffect,
  useRef,
  useState,
} from "react";
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
  createElementId,
  groupElementId,
  rowKey,
} from "@opal/components/dropdown/model";
import { Row, targetTakesFocus } from "@opal/components/dropdown/rows";
import type {
  DropdownMode,
  DropdownRow,
  DropdownSearch,
  RowGroup,
} from "@opal/components/dropdown/types";

interface DropdownListProps {
  listId: string;
  mode: DropdownMode;
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
  /** The edge the list grows from: a leaving card stays pinned to it. */
  anchoredEdge: "top" | "bottom";
  setFloatingRef: (node: HTMLDivElement | null) => void;
  /** The view on show; a change swaps the rows in place, animated. */
  viewKey: string;
  /** Which way the last view change went: the slide follows it. */
  viewDirection: "forward" | "back";
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
  noMatchText?: string;
  /** The rows scrolled to within SCROLL_END_THRESHOLD_PX of their end. */
  onReachEnd?: () => void;
  /**
   * A search field pinned above the rows. It takes focus when the list
   * opens; the key handler is the trigger's, so arrows, Enter, Escape and
   * Tab behave the same from either.
   */
  searchField?: Omit<DropdownSearch, "onChange"> & {
    value: string;
    onChange: (value: string) => void;
    onKeyDown: (event: React.KeyboardEvent<HTMLElement>) => void;
  };
}

const SCROLL_END_THRESHOLD_PX = 48;

/**
 * The list in a portal: the positioned root and, inside it, the card with
 * the search field and the scrolling listbox or menu. The role sits on the
 * scroller, so the search field stays outside the composite while pinned
 * above it. Scrolls the keyboard stop into view, opens around the
 * selection, and swaps the whole card when the view changes.
 */
export const DropdownList = forwardRef<HTMLDivElement, DropdownListProps>(
  (
    {
      listId,
      mode,
      container,
      isOpen,
      disabled,
      label,
      floatingStyles,
      isPositioned,
      anchoredEdge,
      setFloatingRef,
      viewKey,
      viewDirection,
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
      noMatchText,
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
    }, [isOpen, hasSearch, viewKey]);

    const listRef = useRef<HTMLDivElement | null>(null);

    // A view change swaps the whole card. The old card, re-rendered from
    // the props of the previous commit (inert, under its own ids), is kept
    // one animation longer and slides out; the new card slides in from the
    // other side. Each card keeps its own height throughout.
    const [exiting, setExiting] = useState<{
      key: string;
      props: CardProps;
      width: number | null;
      direction: "forward" | "back";
    } | null>(null);
    // The live card arrived by a view change, from this side. Kept for the
    // card's whole life: it also holds off the box's own entrance on the
    // rows, which would otherwise replay the moment the attribute left.
    const [enter, setEnter] = useState<"forward" | "back" | null>(null);
    // The card and its place as the list closed. The view resets and the
    // trigger may hide underneath the exit, so the list keeps showing this
    // snapshot, where it was, until it unmounts.
    const [frozen, setFrozen] = useState<{
      key: string;
      props: CardProps;
      styles: React.CSSProperties;
      width: number | null;
    } | null>(null);
    const lastCardRef = useRef<{
      key: string;
      props: CardProps;
      styles: React.CSSProperties;
      width: number | null;
    } | null>(null);
    const lastViewKeyRef = useRef(viewKey);
    useLayoutEffect(() => {
      if (!isOpen) {
        // Closing resets the view underneath the exit: no swap to show,
        // and the next session's first card arrives with the box.
        lastViewKeyRef.current = viewKey;
        setExiting(null);
        setEnter(null);
        setFrozen(lastCardRef.current);
        return;
      }
      setFrozen(null);
      if (lastViewKeyRef.current === viewKey) return;
      lastViewKeyRef.current = viewKey;
      setEnter(viewDirection);
      // Reduced motion swaps at once: no old card to animate away, and no
      // exit animation whose end would clear it.
      const reduceMotion =
        typeof window.matchMedia === "function" &&
        window.matchMedia("(prefers-reduced-motion: reduce)").matches;
      const last = lastCardRef.current;
      if (last && last.key !== viewKey && !reduceMotion) {
        setExiting({ ...last, direction: viewDirection });
      }
    }, [isOpen, viewKey, viewDirection]);

    // Keyboard navigation keeps the highlighted row in view. Pointer
    // highlights never scroll: the list must not move under the mouse.
    useEffect(() => {
      if (!isOpen || !keyboardNav || highlightedIndex < 0) return;
      liveCard(listRef.current)
        ?.querySelector(`[data-index="${highlightedIndex}"]`)
        ?.scrollIntoView({ block: "nearest", behavior: "instant" });
    }, [highlightedIndex, isOpen, keyboardNav]);

    // Opening shows the selection: the (first) selected row is centred in
    // view, so a long list opens around the current value. Waits for
    // floating-ui to size the box: before that the rows lay out single-line
    // at the wrong width, the centre is computed on those heights, and the
    // selection lands below the fold once the descriptions wrap.
    useEffect(() => {
      if (!isOpen || !isPositioned) return;
      const selected = liveCard(listRef.current)?.querySelector(
        '[role="option"][aria-selected="true"]'
      );
      selected?.scrollIntoView({ block: "center", behavior: "instant" });
    }, [isOpen, isPositioned]);

    const cardProps: CardProps = {
      listId,
      mode,
      label,
      groups,
      emptySet,
      isSelected,
      exactValue,
      highlightedIndex,
      onActivate,
      onToggleGroup,
      create,
      maxHeight,
      noMatchText,
      onReachEnd,
      searchField,
    };
    // What this commit shows, for the next view change to animate away.
    useLayoutEffect(() => {
      if (!isOpen) return;
      lastCardRef.current = {
        key: viewKey,
        props: cardProps,
        styles: floatingStyles,
        width: liveCard(listRef.current)?.offsetWidth ?? null,
      };
    });

    if (!presence.mounted || disabled || typeof document === "undefined") {
      return null;
    }

    return createPortal(
      <div
        ref={(node) => {
          listRef.current = node;
          setFloatingRef(node);
          if (typeof ref === "function") ref(node);
          else if (ref) ref.current = node;
        }}
        // The root: positioned, animated and dismissed as one. The listbox
        // or menu role is on the scroller inside the card, so the search
        // field is not a child of the composite.
        role="presentation"
        // Closed while exiting: invisible to AT and to the pointer.
        aria-hidden={presence.state === "closed" || undefined}
        data-state={presence.state}
        // Highlighting is modal: while the keyboard drives it, rows and
        // titles ignore the pointer so no hover paints beside the keyboard
        // stop. The first pointer movement hands control back.
        data-keyboard-nav={keyboardNav || undefined}
        onMouseMove={onMouseMove}
        className="opal-dropdown"
        style={frozen?.styles ?? floatingStyles}
        onAnimationEnd={presence.onAnimationEnd}
        onMouseDown={(e) => {
          // Clicks on padding, gaps, or dividers must not steal focus from
          // the trigger (the list is tabIndex={-1} for AT only). A control
          // that needs focus keeps the default.
          if (!targetTakesFocus(e)) e.preventDefault();
        }}
        onKeyDown={(e) => {
          // Keys typed into the list (its search field, a control in a
          // custom row) are the list's. React bubbles them through the
          // portal to the trigger's ancestors, where a row's drag handle or
          // link would otherwise claim Space and Enter.
          e.stopPropagation();
        }}
        onWheel={(e) => {
          // Scroll here, not in whatever sits behind the portal.
          e.stopPropagation();
        }}
        onTouchMove={(e) => {
          e.stopPropagation();
        }}
      >
        <div className="opal-dropdown-stage">
          {/* Keyed by view, so a change mounts a new card and plays its
              entrance. The first card of a session does not slide: the
              root's own entrance covers it. */}
          <Card
            key={frozen?.key ?? viewKey}
            live
            searchRef={searchRef}
            data-enter={enter ?? undefined}
            {...(frozen?.props ?? cardProps)}
          />
          {exiting && (
            // The card that just left, rendered after the live one so an
            // id lookup or a query finds the live card first.
            <Card
              key={`exit-${exiting.key}`}
              live={false}
              data-exit={exiting.direction}
              data-pin={anchoredEdge}
              // Its own width, should the new view ask for another.
              style={
                exiting.width === null ? undefined : { width: exiting.width }
              }
              onExit={() => setExiting(null)}
              {...exiting.props}
              listId={`${listId}-exit`}
              onReachEnd={undefined}
            />
          )}
        </div>
      </div>,
      container ?? document.body
    );
  }
);

DropdownList.displayName = "DropdownList";

// ---------------------------------------------------------------------------
// Card
// ---------------------------------------------------------------------------

/** The first card in the root: the one on show, before any that is leaving. */
function liveCard(root: HTMLElement | null): HTMLElement | null {
  return root?.querySelector<HTMLElement>(".opal-dropdown-card") ?? null;
}

/** What a card renders: the search field and the rows of one view. */
interface CardProps {
  listId: string;
  mode: DropdownMode;
  label: string;
  groups: RowGroup[];
  emptySet: boolean;
  isSelected: (row: DropdownRow) => boolean;
  exactValue: string | undefined;
  highlightedIndex: number;
  onActivate: (row: DropdownRow) => void;
  onToggleGroup: (group: RowGroup) => void;
  create?: { text: string; onCreate: (text: string) => void };
  maxHeight?: string;
  noMatchText?: string;
  onReachEnd?: () => void;
  searchField?: DropdownListProps["searchField"];
}

interface CardElementProps extends CardProps {
  /**
   * The card on show. A card that is leaving is inert and hidden from AT,
   * and renders under its own ids so nothing on it collides with the live
   * card.
   */
  live: boolean;
  searchRef?: React.RefObject<HTMLInputElement | null>;
  "data-enter"?: "forward" | "back";
  "data-exit"?: "forward" | "back";
  /** Which stage edge a leaving card stays on while the live one resizes. */
  "data-pin"?: "top" | "bottom";
  style?: React.CSSProperties;
  /** The leaving card's own exit animation ended. */
  onExit?: () => void;
}

/**
 * The bordered box: a pinned search field, then the scrolling listbox or
 * menu with its groups, dividers, create row and rows.
 */
function Card({
  live,
  searchRef,
  "data-enter": enter,
  "data-exit": exit,
  "data-pin": pin,
  style,
  onExit,
  listId,
  mode,
  label,
  groups,
  emptySet,
  isSelected,
  exactValue,
  highlightedIndex,
  onActivate,
  onToggleGroup,
  create,
  maxHeight,
  noMatchText,
  onReachEnd,
  searchField,
}: CardElementProps) {
  const strings = useOpalStrings();
  const hasSearch = searchField !== undefined;
  // The list owns the field's text and keys; the rest is the caller's.
  const {
    value = "",
    placeholder = "",
    onChange = () => {},
    onKeyDown,
    ...fieldProps
  } = searchField ?? {};
  const totalRows = groups.reduce(
    (count, group) => count + group.rows.length,
    0
  );

  return (
    <div
      className="opal-dropdown-card"
      data-enter={enter}
      data-exit={exit}
      data-pin={pin}
      style={style}
      inert={!live || undefined}
      aria-hidden={!live || undefined}
      onAnimationEnd={(e) => {
        // The card's own exit, not a child's animation bubbling up.
        if (e.target === e.currentTarget) onExit?.();
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
            {...fieldProps}
            ref={searchRef}
            searchIcon
            variant="internal"
            placeholder={placeholder}
            aria-label={placeholder}
            value={value}
            onChange={(e) => onChange(e.target.value)}
            onKeyDown={onKeyDown}
          />
        </div>
      )}
      <ShadowDiv
        shadowHeight={3}
        // Rows fade out at the edges: a painted shadow sat on top of them
        // and read as a smudge on the light surface. With a search field
        // the top is different: the field casts a shadow on rows scrolled
        // under it.
        variant={hasSearch ? { top: "shadow", bottom: "mask" } : "mask"}
        // The rise-and-settle runs on this non-scrolling wrapper: a
        // transform on the scroller itself makes Chromium repaint it at
        // scroll offset 0 for a frame when compositing switches.
        containerClassName="opal-dropdown-content"
        className={cn("opal-dropdown-scroll", !maxHeight && "max-h-60")}
        // The composite: what the trigger controls and the rows belong to.
        id={`${listId}-listbox`}
        role={mode === "picker" ? "listbox" : "menu"}
        aria-label={label}
        tabIndex={-1}
        // The search field brings its own 4px below; the rows start right
        // under that, with no inset of their own.
        data-under-search={hasSearch || undefined}
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
              {noMatchText ?? strings.comboBoxNoOptions}
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
    </div>
  );
}

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
          id={createElementId(listId)}
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
        // of its own; its rows are its children, withheld while folded. The
        // group names itself by the title; the header is the stop, with the
        // id aria-activedescendant points at and its folded state.
        if (isFoldable && group.title !== undefined) {
          return (
            <div
              key={group.key}
              role="group"
              aria-label={group.title}
              className="opal-dropdown-group"
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
                // In a picker the title is a button, not an option: it is
                // never picked, and the rows stay the only options.
                headerProps={{
                  id: groupElementId(listId, group.key),
                  "data-index": headerIndex,
                  role: mode === "picker" ? "button" : "menuitem",
                  "aria-expanded": !group.folded,
                  tabIndex: -1,
                }}
              >
                <div className="opal-dropdown-group-rows">{rows}</div>
              </Divider>
            </div>
          );
        }
        return (
          <React.Fragment key={group.key}>
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
