import { Button } from "@opal/components";
import { Disabled } from "@opal/core";
import { SvgChevronLeft, SvgChevronRight } from "@opal/icons";
import { cn } from "@opal/utils";
import type { WithoutStyles } from "@opal/types";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

type PaginationSize = "lg" | "md" | "sm";

/**
 * Compact `currentPage / totalPages` display with prev/next arrows.
 */
interface SimplePaginationProps
  extends Omit<
    WithoutStyles<React.HTMLAttributes<HTMLDivElement>>,
    "onChange"
  > {
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
  showSummary?: boolean;
  /** Unit label shown after the summary (e.g. `"pages"`). Always has 4px spacing. */
  units?: string;
}

/**
 * Item-count display (`X~Y of Z`) with prev/next arrows.
 * Designed for table footers.
 */
interface CountPaginationProps
  extends Omit<
    WithoutStyles<React.HTMLAttributes<HTMLDivElement>>,
    "onChange"
  > {
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
  showSummary?: boolean;
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
  extends Omit<
    WithoutStyles<React.HTMLAttributes<HTMLDivElement>>,
    "onChange"
  > {
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
 * Computes the page numbers to display, inserting `"start-ellipsis"` and/or
 * `"end-ellipsis"` sentinels when the total exceeds 7 pages.
 */
function getPageNumbers(
  currentPage: number,
  totalPages: number
): (number | string)[] {
  const pages: (number | string)[] = [];
  const maxPagesToShow = 7;

  if (totalPages <= maxPagesToShow) {
    for (let i = 1; i <= totalPages; i++) pages.push(i);
    return pages;
  }

  pages.push(1);

  let startPage = Math.max(2, currentPage - 1);
  let endPage = Math.min(totalPages - 1, currentPage + 1);

  if (currentPage <= 3) {
    endPage = 5;
  } else if (currentPage >= totalPages - 2) {
    startPage = totalPages - 4;
  }

  if (startPage > 2) {
    pages.push(startPage === 3 ? 2 : "start-ellipsis");
  }

  for (let i = startPage; i <= endPage; i++) pages.push(i);

  if (endPage < totalPages - 1) {
    pages.push(endPage === totalPages - 2 ? totalPages - 1 : "end-ellipsis");
  }

  pages.push(totalPages);
  return pages;
}

function monoClass(size: PaginationSize): string {
  return size === "sm" ? "font-secondary-mono" : "font-main-ui-mono";
}

function textClasses(size: PaginationSize, style: "mono" | "muted"): string {
  if (style === "mono") return monoClass(size);
  return size === "sm" ? "font-secondary-body" : "font-main-ui-muted";
}

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
  children?: React.ReactNode;
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
          onClick={() => onChange(currentPage - 1)}
          size={size}
          prominence="tertiary"
          tooltip="Previous page"
        />
      </Disabled>
      {children}
      <Disabled disabled={currentPage >= totalPages}>
        <Button
          icon={SvgChevronRight}
          onClick={() => onChange(currentPage + 1)}
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
  showSummary = true,
  units,
  ...props
}: SimplePaginationProps) {
  const handleChange = (page: number) => onArrowClick?.(page);

  return (
    <div
      {...props}
      className={cn("flex items-center", size !== "sm" && "gap-1")}
    >
      <NavButtons
        currentPage={currentPage}
        totalPages={totalPages}
        onChange={handleChange}
        size={size}
      >
        {showSummary && (
          <span className={cn(monoClass(size), "text-text-03")}>
            {currentPage}/{totalPages}
            {units && <span style={{ marginLeft: 4 }}>{units}</span>}
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
  showSummary = true,
  units,
  goto: onGoto,
  ...props
}: CountPaginationProps) {
  const handleChange = (page: number) => onArrowClick?.(page);
  const rangeStart = totalItems === 0 ? 0 : (currentPage - 1) * pageSize + 1;
  const rangeEnd = Math.min(currentPage * pageSize, totalItems);

  return (
    <div {...props} className="flex items-center gap-[4px]">
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
        {units && <span style={{ marginLeft: 4 }}>{units}</span>}
      </span>

      {/* Buttons: < [page] > */}
      <div className="flex items-center">
        <NavButtons
          currentPage={currentPage}
          totalPages={totalPages}
          onChange={handleChange}
          size={size}
        >
          {showSummary && (
            <span className={cn(monoClass(size), "text-text-03")}>
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
    <div {...props} className={cn("flex items-center gap-1")}>
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
                <span key={page} className={cn("px-1", fonts.inactive)}>
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
  const normalized = { ...props, totalPages: Math.max(1, props.totalPages) };
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
