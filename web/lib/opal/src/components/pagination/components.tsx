import { Button } from "@opal/components";
import { Disabled } from "@opal/core";
import { SvgChevronLeft, SvgChevronRight } from "@opal/icons";
import type { WithoutStyles } from "@opal/types";
import { cn } from "@opal/utils";
import type { HTMLAttributes, ReactNode } from "react";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

type PaginationSize = "lg" | "md" | "sm";

/**
 * Compact `currentPage / totalPages` display with prev/next arrows.
 */
interface SimplePaginationProps
  extends Omit<WithoutStyles<HTMLAttributes<HTMLDivElement>>, "onChange"> {
  variant: "simple";
  /** The 1-based current page number. */
  currentPage: number;
  /** Total number of pages. */
  totalPages: number;
  /** Called when a prev/next arrow is clicked. */
  onArrowClick?: (page: number) => void;
  /** Controls button and text sizing. Default: `"lg"`. */
  size?: PaginationSize;
  /** Whether to show the `currentPage/totalPages` summary text. Default: `true`. */
  showPages?: boolean;
  /** Unit label shown after the summary (e.g. `"pages"`). Always has 4px spacing. */
  units?: string;
}

/**
 * Item-count display (`X~Y of Z`) with prev/next arrows.
 * Designed for table footers.
 */
interface CountPaginationProps
  extends Omit<WithoutStyles<HTMLAttributes<HTMLDivElement>>, "onChange"> {
  variant: "count";
  /** The 1-based current page number. */
  currentPage: number;
  /** Total number of pages. */
  totalPages: number;
  /** Number of items displayed per page. Used to compute the visible range. */
  pageSize: number;
  /** Total number of items across all pages. */
  totalItems: number;
  /** Called when a prev/next arrow is clicked. */
  onArrowClick?: (page: number) => void;
  /** Controls button and text sizing. Default: `"lg"`. */
  size?: PaginationSize;
  /** Whether to show the current page number between the arrows. Default: `true`. */
  showPages?: boolean;
  /** Unit label shown after the total count (e.g. `"items"`). Always has 4px spacing. */
  units?: string;
  /** If provided, renders a "Go to" button that calls this callback when clicked. */
  goto?: () => void;
}

/**
 * Numbered page buttons with ellipsis truncation for large page counts.
 * This is the default variant.
 */
interface ListPaginationProps
  extends Omit<WithoutStyles<HTMLAttributes<HTMLDivElement>>, "onChange"> {
  variant?: "list";
  /** The 1-based current page number. */
  currentPage: number;
  /** Total number of pages. */
  totalPages: number;
  /** Called when a page is selected (via page button or arrow). */
  onPageClick: (page: number) => void;
  /** Controls button and text sizing. Default: `"lg"`. */
  size?: PaginationSize;
}

/**
 * Discriminated union of all pagination variants.
 * Use `variant` to select between `"simple"`, `"count"`, and `"list"` (default).
 */
type PaginationProps =
  | SimplePaginationProps
  | CountPaginationProps
  | ListPaginationProps;

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

/**
 * Computes the page numbers to display.
 *
 * - <=7 pages: render all pages individually (no ellipsis).
 * - >7 pages: always render exactly 7 slots (numbers or ellipsis).
 *   First and last page are always shown. Ellipsis takes one slot.
 *
 * Examples for totalPages=20:
 * - page 1:  `1  2  3  4  5  ...  20`
 * - page 4:  `1  2  3  4  5  ...  20`
 * - page 5:  `1  ...  4  5  6  ...  20`
 * - page 16: `1  ...  15  16  17  ...  20`
 * - page 17: `1  ...  16  17  18  19  20`
 * - page 20: `1  ...  16  17  18  19  20`
 */
function getPageNumbers(
  currentPage: number,
  totalPages: number
): (number | string)[] {
  if (totalPages <= 7) {
    const pages: number[] = [];
    for (let i = 1; i <= totalPages; i++) pages.push(i);
    return pages;
  }

  // Always 7 slots. First and last are always page 1 and totalPages.
  // That leaves 5 inner slots.

  // Near the start: no start-ellipsis needed
  // Slots: 1, 2, 3, 4, 5, ..., totalPages
  if (currentPage <= 4) {
    return [1, 2, 3, 4, 5, "end-ellipsis", totalPages];
  }

  // Near the end: no end-ellipsis needed
  // Slots: 1, ..., tp-4, tp-3, tp-2, tp-1, tp
  if (currentPage >= totalPages - 3) {
    return [
      1,
      "start-ellipsis",
      totalPages - 4,
      totalPages - 3,
      totalPages - 2,
      totalPages - 1,
      totalPages,
    ];
  }

  // Middle: both ellipses
  // Slots: 1, ..., cur-1, cur, cur+1, ..., totalPages
  return [
    1,
    "start-ellipsis",
    currentPage - 1,
    currentPage,
    currentPage + 1,
    "end-ellipsis",
    totalPages,
  ];
}

function monoClass(size: PaginationSize): string {
  return size === "sm" ? "font-secondary-mono" : "font-main-ui-mono";
}

function textClasses(size: PaginationSize, style: "mono" | "muted"): string {
  if (style === "mono") return monoClass(size);
  return size === "sm" ? "font-secondary-body" : "font-main-ui-muted";
}

/** Matches the icon-only Button dimensions for each size. */
const ELLIPSIS_SIZE: Record<PaginationSize, string> = {
  lg: "w-[2.25rem] h-[2.25rem]",
  md: "w-[1.75rem] h-[1.75rem]",
  sm: "w-[1.5rem] h-[1.5rem]",
};

const PAGE_NUMBER_FONT: Record<
  PaginationSize,
  { active: string; inactive: string }
> = {
  lg: {
    active: "font-main-ui-body text-text-04",
    inactive: "font-main-ui-muted text-text-02",
  },
  md: {
    active: "font-secondary-action text-text-04",
    inactive: "font-secondary-body text-text-02",
  },
  sm: {
    active: "font-secondary-action text-text-04",
    inactive: "font-secondary-body text-text-02",
  },
};

// ---------------------------------------------------------------------------
// Nav buttons (shared across all variants)
// ---------------------------------------------------------------------------

interface NavButtonsProps {
  currentPage: number;
  totalPages: number;
  onChange: (page: number) => void;
  size: PaginationSize;
  children?: ReactNode;
}

function NavButtons({
  currentPage,
  totalPages,
  onChange,
  size,
  children,
}: NavButtonsProps) {
  return (
    <>
      <Disabled disabled={currentPage <= 1}>
        <Button
          icon={SvgChevronLeft}
          onClick={() => onChange(Math.max(1, currentPage - 1))}
          size={size}
          prominence="tertiary"
          tooltip="Previous page"
        />
      </Disabled>
      {children}
      <Disabled disabled={currentPage >= totalPages}>
        <Button
          icon={SvgChevronRight}
          onClick={() => onChange(Math.min(totalPages, currentPage + 1))}
          size={size}
          prominence="tertiary"
          tooltip="Next page"
        />
      </Disabled>
    </>
  );
}

// ---------------------------------------------------------------------------
// PaginationSimple
// ---------------------------------------------------------------------------

function PaginationSimple({
  currentPage,
  totalPages,
  onArrowClick,
  size = "lg",
  showPages = true,
  units,
  ...props
}: SimplePaginationProps) {
  const handleChange = (page: number) => onArrowClick?.(page);

  return (
    <div {...props} className="flex items-center">
      <NavButtons
        currentPage={currentPage}
        totalPages={totalPages}
        onChange={handleChange}
        size={size}
      >
        {showPages && (
          <span className={cn(monoClass(size), "px-1 text-text-03")}>
            {currentPage}/{totalPages}
            {units && <span className="ml-1">{units}</span>}
          </span>
        )}
      </NavButtons>
    </div>
  );
}

// ---------------------------------------------------------------------------
// PaginationCount
// ---------------------------------------------------------------------------

function PaginationCount({
  pageSize,
  totalItems,
  currentPage,
  totalPages,
  onArrowClick,
  size = "lg",
  showPages = true,
  units,
  goto: onGoto,
  ...props
}: CountPaginationProps) {
  const handleChange = (page: number) => onArrowClick?.(page);
  const rangeStart = totalItems === 0 ? 0 : (currentPage - 1) * pageSize + 1;
  const rangeEnd = Math.min(currentPage * pageSize, totalItems);

  return (
    <div {...props} className="flex items-center gap-1">
      {/* Summary: range of total [units] */}
      <span
        className={cn(
          "flex items-center gap-1",
          monoClass(size),
          "text-text-03"
        )}
      >
        {rangeStart}~{rangeEnd}
        <span className={textClasses(size, "muted")}>of</span>
        {totalItems}
        {units && <span className="ml-1">{units}</span>}
      </span>

      {/* Buttons: < [page] > */}
      <div className="flex items-center">
        <NavButtons
          currentPage={currentPage}
          totalPages={totalPages}
          onChange={handleChange}
          size={size}
        >
          {showPages && (
            <span
              className={cn(
                "flex items-center justify-center",
                size === "sm" ? "w-[20px]" : "w-[28px]",
                monoClass(size),
                "text-text-03"
              )}
            >
              {currentPage}
            </span>
          )}
        </NavButtons>
      </div>

      {/* Goto */}
      {onGoto && (
        <Button onClick={onGoto} size={size} prominence="tertiary">
          Go to
        </Button>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// PaginationList (default)
// ---------------------------------------------------------------------------

function PaginationList({
  currentPage,
  totalPages,
  onPageClick,
  size = "lg",
  ...props
}: ListPaginationProps) {
  const pageNumbers = getPageNumbers(currentPage, totalPages);
  const fonts = PAGE_NUMBER_FONT[size];

  return (
    <div {...props} className="flex items-center gap-1">
      <NavButtons
        currentPage={currentPage}
        totalPages={totalPages}
        onChange={onPageClick}
        size={size}
      >
        <div className="flex items-center">
          {pageNumbers.map((page) => {
            if (typeof page === "string") {
              return (
                <span
                  key={page}
                  className={cn(
                    "flex items-center justify-center",
                    ELLIPSIS_SIZE[size],
                    fonts.inactive
                  )}
                >
                  ...
                </span>
              );
            }

            const isActive = page === currentPage;

            return (
              <Button
                key={page}
                onClick={() => onPageClick(page)}
                size={size}
                prominence="tertiary"
                interaction={isActive ? "hover" : "rest"}
                icon={({ className: iconClassName }) => (
                  <div
                    className={cn(
                      iconClassName,
                      "flex flex-col justify-center",
                      isActive ? fonts.active : fonts.inactive
                    )}
                  >
                    {page}
                  </div>
                )}
              />
            );
          })}
        </div>
      </NavButtons>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Pagination (entry point)
// ---------------------------------------------------------------------------

/**
 * Page navigation component with three variants:
 *
 * - `"list"` (default) — Numbered page buttons with ellipsis truncation.
 * - `"simple"` — Compact `currentPage / totalPages` with prev/next arrows.
 * - `"count"` — Item-count display (`X~Y of Z`) with prev/next arrows.
 *
 * @example
 * ```tsx
 * // List (default)
 * <Pagination currentPage={3} totalPages={10} onPageClick={setPage} />
 *
 * // Simple
 * <Pagination variant="simple" currentPage={1} totalPages={5} onArrowClick={setPage} />
 *
 * // Count
 * <Pagination variant="count" pageSize={10} totalItems={95} currentPage={2} totalPages={10} onArrowClick={setPage} />
 * ```
 */
function Pagination(props: PaginationProps) {
  const normalized = {
    ...props,
    totalPages: Math.max(1, props.totalPages),
    currentPage: Math.max(1, props.currentPage),
  };
  const variant = normalized.variant ?? "list";
  switch (variant) {
    case "simple":
      return <PaginationSimple {...(normalized as SimplePaginationProps)} />;
    case "count":
      return <PaginationCount {...(normalized as CountPaginationProps)} />;
    case "list":
      return <PaginationList {...(normalized as ListPaginationProps)} />;
  }
}

export { Pagination, type PaginationProps, type PaginationSize };
