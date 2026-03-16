import { Button } from "@opal/components";
import { Disabled } from "@opal/core";
import { SvgChevronLeft, SvgChevronRight } from "@opal/icons";
import { cn } from "@opal/utils";
import type { WithoutStyles } from "@opal/types";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

type PaginationSize = "lg" | "md" | "sm";

interface PaginationBase
  extends Omit<
    WithoutStyles<React.HTMLAttributes<HTMLDivElement>>,
    "onChange"
  > {
  /** The 1-based current page number. */
  currentPage: number;
  /** Total number of pages. */
  totalPages: number;
  /** Called when the page changes (via prev/next arrows or page buttons). */
  onChange: (page: number) => void;
  /** Controls button and text sizing. Default: `"md"`. */
  size?: PaginationSize;
}

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
interface CountPaginationProps extends PaginationBase {
  variant: "count";
  /** Number of items displayed per page. Used to compute the visible range. */
  pageSize: number;
  /** Total number of items across all pages. */
  totalItems: number;
}

/**
 * Numbered page buttons with ellipsis truncation for large page counts.
 * This is the default variant.
 */
interface ListPaginationProps extends PaginationBase {
  variant?: "list";
  /** Called when a specific numbered page button is clicked. */
  onPageClick?: (page: number) => void;
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
  onChange,
  size = "md",
  ...props
}: CountPaginationProps) {
  const rangeStart = totalItems === 0 ? 0 : (currentPage - 1) * pageSize + 1;
  const rangeEnd = Math.min(currentPage * pageSize, totalItems);

  return (
    <div {...props} className={cn("flex items-center gap-1")}>
      <span className={cn(textClasses(size, "mono"), "text-text-03")}>
        {rangeStart}~{rangeEnd}
      </span>
      <span className={cn(textClasses(size, "muted"), "text-text-03")}>of</span>
      <span className={cn(textClasses(size, "mono"), "text-text-03")}>
        {totalItems}
      </span>

      <NavButtons
        currentPage={currentPage}
        totalPages={totalPages}
        onChange={onChange}
        size={size}
      >
        <span className={cn(textClasses(size, "mono"), "text-text-03")}>
          {currentPage}
        </span>
      </NavButtons>
    </div>
  );
}

// ---------------------------------------------------------------------------
// PaginationList (default)
// ---------------------------------------------------------------------------

function PaginationList({
  currentPage,
  totalPages,
  onChange,
  onPageClick,
  size = "md",
  ...props
}: ListPaginationProps) {
  const pageNumbers = getPageNumbers(currentPage, totalPages);
  const fonts = PAGE_NUMBER_FONT[size];

  const handlePageClick = (page: number) => {
    onPageClick?.(page);
    onChange(page);
  };

  return (
    <div {...props} className={cn("flex items-center gap-1")}>
      <NavButtons
        currentPage={currentPage}
        totalPages={totalPages}
        onChange={onChange}
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
                onClick={() => handlePageClick(page)}
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
 * <Pagination currentPage={3} totalPages={10} onChange={setPage} />
 *
 * // Simple
 * <Pagination variant="simple" currentPage={1} totalPages={5} onChange={setPage} />
 *
 * // Count
 * <Pagination variant="count" pageSize={10} currentPage={2} totalPages={10} onChange={setPage} />
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
