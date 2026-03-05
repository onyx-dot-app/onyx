"use client";

import { cn } from "@/lib/utils";
import { Button } from "@opal/components";
import Text from "@/refresh-components/texts/Text";
import Pagination from "@/refresh-components/table/Pagination";
import { useTableSize } from "@/refresh-components/table/TableSizeContext";
import type { TableSize } from "@/refresh-components/table/TableSizeContext";
import { SvgEye, SvgXCircle } from "@opal/icons";

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
  /** If provided, renders a "View" icon button when items are selected. */
  onView?: () => void;
  /** If provided, renders a "Clear" icon button when items are selected. */
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
  /** Controls overall footer sizing. `"regular"` (default) or `"small"`. */
  size?: TableSize;
  className?: string;
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
  /** Controls overall footer sizing. `"regular"` (default) or `"small"`. */
  size?: TableSize;
  className?: string;
}

/**
 * Discriminated union of footer modes.
 * Use `mode: "selection"` for tables with selectable rows, or
 * `mode: "summary"` for read-only tables.
 */
export type FooterProps = FooterSelectionModeProps | FooterSummaryModeProps;

function getSelectionMessage(
  state: SelectionState,
  multi: boolean,
  count: number
): string {
  if (state === "none") {
    return multi ? "Select items to continue" : "Select an item to continue";
  }
  if (!multi) return "Item selected";
  return `${count} items selected`;
}

/**
 * Table footer combining status information on the left with pagination on the
 * right. Use `mode: "selection"` for tables with selectable rows, or
 * `mode: "summary"` for read-only tables.
 */
export default function Footer(props: FooterProps) {
  const contextSize = useTableSize();
  const resolvedSize = props.size ?? contextSize;
  const isSmall = resolvedSize === "small";
  return (
    <div
      className={cn(
        "table-footer",
        "flex w-full items-center justify-between border-t border-border-01",
        props.className
      )}
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
            onClear={props.onClear}
            isSmall={isSmall}
          />
        ) : (
          <SummaryLeft
            rangeStart={props.rangeStart}
            rangeEnd={props.rangeEnd}
            totalItems={props.totalItems}
            isSmall={isSmall}
          />
        )}
      </div>

      {/* Right side */}
      <div className="flex items-center gap-2 px-1 py-2">
        {props.mode === "selection" ? (
          <Pagination
            type="count"
            pageSize={props.pageSize}
            totalItems={props.totalItems}
            currentPage={props.currentPage}
            totalPages={props.totalPages}
            onPageChange={props.onPageChange}
            showUnits
            size={isSmall ? "sm" : "md"}
          />
        ) : (
          <Pagination
            type="list"
            currentPage={props.currentPage}
            totalPages={props.totalPages}
            onPageChange={props.onPageChange}
            size={isSmall ? "md" : "lg"}
          />
        )}
      </div>
    </div>
  );
}

interface SelectionLeftProps {
  selectionState: SelectionState;
  multiSelect: boolean;
  selectedCount: number;
  onView?: () => void;
  onClear?: () => void;
  isSmall: boolean;
}

function SelectionLeft({
  selectionState,
  multiSelect,
  selectedCount,
  onView,
  onClear,
  isSmall,
}: SelectionLeftProps) {
  const message = getSelectionMessage(
    selectionState,
    multiSelect,
    selectedCount
  );
  const hasSelection = selectionState !== "none";

  return (
    <div className="flex flex-row gap-1 items-center justify-center w-fit flex-shrink-0 h-fit px-1">
      {isSmall ? (
        <Text
          secondaryAction={hasSelection}
          secondaryBody={!hasSelection}
          text03
        >
          {message}
        </Text>
      ) : (
        <Text mainUiBody={hasSelection} mainUiMuted={!hasSelection} text03>
          {message}
        </Text>
      )}

      {hasSelection && (
        <div className="flex flex-row items-center w-fit flex-shrink-0 h-fit">
          {onView && (
            <Button
              icon={SvgEye}
              onClick={onView}
              tooltip="View"
              size={isSmall ? "sm" : "md"}
              prominence="tertiary"
            />
          )}
          {onClear && (
            <Button
              icon={SvgXCircle}
              onClick={onClear}
              tooltip="Clear selection"
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
  isSmall: boolean;
}

function SummaryLeft({
  rangeStart,
  rangeEnd,
  totalItems,
  isSmall,
}: SummaryLeftProps) {
  return (
    <div className="flex flex-row gap-1 items-center w-fit h-fit px-1">
      {isSmall ? (
        <Text secondaryBody text03>
          Showing{" "}
          <Text as="span" secondaryMono text03>
            {rangeStart}~{rangeEnd}
          </Text>{" "}
          of{" "}
          <Text as="span" secondaryMono text03>
            {totalItems}
          </Text>
        </Text>
      ) : (
        <Text mainUiMuted text03>
          Showing{" "}
          <Text as="span" mainUiMono text03>
            {rangeStart}~{rangeEnd}
          </Text>{" "}
          of{" "}
          <Text as="span" mainUiMono text03>
            {totalItems}
          </Text>
        </Text>
      )}
    </div>
  );
}
