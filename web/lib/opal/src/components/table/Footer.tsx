"use client";

import { Button, Pagination, SelectButton } from "@opal/components";
import { Text } from "@opal/components";
import { useTableSize } from "@opal/components/table/TableSizeContext";
import { SvgEye, SvgXCircle } from "@opal/icons";
import type { ReactNode } from "react";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

type SelectionState = "none" | "partial" | "all";

/**
 * Footer mode for tables with selectable rows.
 * Displays a selection message on the left (with optional view/clear actions)
 * and a `count`-type pagination on the right.
 */
interface FooterSelectionModeProps {
  mode: "selection";
  /** Whether the table supports selecting multiple rows. */
  multiSelect: boolean;
  /** Current selection state: `"none"`, `"partial"`, or `"all"`. */
  selectionState: SelectionState;
  /** Number of currently selected items. */
  selectedCount: number;
  /** Toggle view-filter on/off. */
  onView?: () => void;
  /** Whether the view-filter is currently active. */
  isViewingSelected?: boolean;
  /** Clears all selections. */
  onClear?: () => void;
  /** Number of items displayed per page. */
  pageSize: number;
  /** Total number of items across all pages. */
  totalItems: number;
  /** The 1-based current page number. */
  currentPage: number;
  /** Total number of pages. */
  totalPages: number;
  /** Called when the user navigates to a different page. */
  onPageChange: (page: number) => void;
  /** Unit label for count pagination. @default "items" */
  units?: string;
}

/**
 * Footer mode for read-only tables (no row selection).
 * Displays "Showing X~Y of Z" on the left and a `list`-type pagination
 * on the right.
 */
interface FooterSummaryModeProps {
  mode: "summary";
  /** First item number in the current page (e.g. `1`). */
  rangeStart: number;
  /** Last item number in the current page (e.g. `25`). */
  rangeEnd: number;
  /** Total number of items across all pages. */
  totalItems: number;
  /** The 1-based current page number. */
  currentPage: number;
  /** Total number of pages. */
  totalPages: number;
  /** Called when the user navigates to a different page. */
  onPageChange: (page: number) => void;
  /** Optional extra element rendered after the summary text (e.g. a download icon). */
  leftExtra?: ReactNode;
  /** Unit label for the summary text, e.g. "users". */
  units?: string;
}

/**
 * Discriminated union of footer modes.
 * Use `mode: "selection"` for tables with selectable rows, or
 * `mode: "summary"` for read-only tables.
 */
export type FooterProps = FooterSelectionModeProps | FooterSummaryModeProps;

// ---------------------------------------------------------------------------
// Footer
// ---------------------------------------------------------------------------

function getSelectionMessage(
  state: SelectionState,
  multi: boolean,
  count: number,
  isViewingSelected: boolean
): string {
  if (state === "none" && !isViewingSelected) {
    return multi ? "Select items to continue" : "Select an item to continue";
  }
  if (!multi) return "Item selected";
  return `${count} item${count !== 1 ? "s" : ""} selected`;
}

/**
 * Table footer combining status information on the left with pagination on the
 * right. Use `mode: "selection"` for tables with selectable rows, or
 * `mode: "summary"` for read-only tables.
 */
export default function Footer(props: FooterProps) {
  const resolvedSize = useTableSize();
  const isSmall = resolvedSize === "md";
  return (
    <div
      className="table-footer flex w-full items-center justify-between border-t border-border-01"
      data-size={resolvedSize}
    >
      {/* Left side */}
      <div className="flex items-center gap-1 px-1">
        {props.mode === "selection" ? (
          <SelectionLeft
            selectionState={props.selectionState}
            multiSelect={props.multiSelect}
            selectedCount={props.selectedCount}
            onView={props.onView}
            isViewingSelected={props.isViewingSelected}
            onClear={props.onClear}
            isSmall={isSmall}
          />
        ) : (
          <>
            <SummaryLeft
              rangeStart={props.rangeStart}
              rangeEnd={props.rangeEnd}
              totalItems={props.totalItems}
              units={props.units}
              isSmall={isSmall}
            />
            {props.leftExtra}
          </>
        )}
      </div>

      {/* Right side */}
      <div className="flex items-center gap-2 px-1 py-2">
        {props.mode === "selection" ? (
          <Pagination
            variant="count"
            pageSize={props.pageSize}
            totalItems={props.totalItems}
            currentPage={props.currentPage}
            totalPages={props.totalPages}
            onChange={props.onPageChange}
            units={props.units}
            size={isSmall ? "sm" : "md"}
          />
        ) : (
          <Pagination
            currentPage={props.currentPage}
            totalPages={props.totalPages}
            onChange={props.onPageChange}
            size={isSmall ? "md" : "lg"}
          />
        )}
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Footer — left-side content
// ---------------------------------------------------------------------------

interface SelectionLeftProps {
  selectionState: SelectionState;
  multiSelect: boolean;
  selectedCount: number;
  onView?: () => void;
  isViewingSelected?: boolean;
  onClear?: () => void;
  isSmall: boolean;
}

function SelectionLeft({
  selectionState,
  multiSelect,
  selectedCount,
  onView,
  isViewingSelected = false,
  onClear,
  isSmall,
}: SelectionLeftProps) {
  const message = getSelectionMessage(
    selectionState,
    multiSelect,
    selectedCount,
    isViewingSelected
  );
  const hasSelection = selectionState !== "none";
  // Show buttons when items are selected OR when the view filter is active
  const showActions = hasSelection || isViewingSelected;

  return (
    <div className="flex flex-row gap-1 items-center justify-center w-fit flex-shrink-0 h-fit px-1">
      {isSmall ? (
        <Text
          font={hasSelection ? "secondary-action" : "secondary-body"}
          color="text-03"
        >
          {message}
        </Text>
      ) : (
        <Text
          font={hasSelection ? "main-ui-body" : "main-ui-muted"}
          color="text-03"
        >
          {message}
        </Text>
      )}

      {showActions && (
        <div className="flex flex-row items-center w-fit flex-shrink-0 h-fit">
          {onView && (
            <SelectButton
              icon={SvgEye}
              state={isViewingSelected ? "selected" : "empty"}
              onClick={onView}
              tooltip="View selected"
              size={isSmall ? "sm" : "md"}
            />
          )}
          {onClear && (
            <Button
              icon={SvgXCircle}
              onClick={onClear}
              tooltip="Deselect all"
              size={isSmall ? "sm" : "md"}
              prominence="tertiary"
            />
          )}
        </div>
      )}
    </div>
  );
}

interface SummaryLeftProps {
  rangeStart: number;
  rangeEnd: number;
  totalItems: number;
  units?: string;
  isSmall: boolean;
}

function SummaryLeft({
  rangeStart,
  rangeEnd,
  totalItems,
  units,
  isSmall,
}: SummaryLeftProps) {
  const suffix = units ? ` ${units}` : "";
  const bodyFont = isSmall ? "secondary-body" : "main-ui-muted";
  const monoFont = isSmall ? "secondary-mono" : "main-ui-mono";
  return (
    <div className="flex flex-row items-center w-fit h-fit px-1">
      <Text font={bodyFont} color="text-03">
        {`Showing `}
      </Text>
      <Text font={monoFont} color="text-03">
        {`${rangeStart}~${rangeEnd}`}
      </Text>
      <Text font={bodyFont} color="text-03">
        {` of `}
      </Text>
      <Text font={monoFont} color="text-03">
        {`${totalItems}${suffix}`}
      </Text>
    </div>
  );
}
