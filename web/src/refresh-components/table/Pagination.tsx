import { Button } from "@opal/components";
import Text from "@/refresh-components/texts/Text";
import { cn } from "@/lib/utils";
import { SvgChevronLeft, SvgChevronRight } from "@opal/icons";

type PaginationSize = "lg" | "md" | "sm";

/**
 * Minimal page navigation showing `currentPage / totalPages` with prev/next arrows.
 * Use when you only need simple forward/backward navigation.
 */
interface SimplePaginationProps {
  type: "simple";
  /** The 1-based current page number. */
  currentPage: number;
  /** Total number of pages. */
  totalPages: number;
  /** Called when the user navigates to a different page. */
  onPageChange: (page: number) => void;
  /** When `true`, displays the word "pages" after the page indicator. */
  showUnits?: boolean;
  /** Controls button and text sizing. Defaults to `"lg"`. */
  size?: PaginationSize;
  className?: string;
}

/**
 * Item-count pagination showing `currentItems of totalItems` with optional page
 * controls and a "Go to" button. Use inside table footers that need to communicate
 * how many items the user is viewing.
 */
interface CountPaginationProps {
  type: "count";
  /** Number of items displayed per page. Used to compute the visible range. */
  pageSize: number;
  /** Total number of items across all pages. */
  totalItems: number;
  /** The 1-based current page number. */
  currentPage: number;
  /** Total number of pages. */
  totalPages: number;
  /** Called when the user navigates to a different page. */
  onPageChange: (page: number) => void;
  /** When `true` (default), shows the prev/next arrows with a page indicator. */
  showPage?: boolean;
  /** When `true`, renders a "Go to" button. Requires `onGoTo`. */
  showGoTo?: boolean;
  /** Callback invoked when the "Go to" button is clicked. */
  onGoTo?: () => void;
  /** When `true`, displays the word "items" after the total count. */
  showUnits?: boolean;
  /** Controls button and text sizing. Defaults to `"lg"`. */
  size?: PaginationSize;
  className?: string;
}

/**
 * Numbered page-list pagination with clickable page buttons and ellipsis
 * truncation for large page counts. Does not support `"sm"` size.
 */
interface ListPaginationProps {
  type: "list";
  /** The 1-based current page number. */
  currentPage: number;
  /** Total number of pages. */
  totalPages: number;
  /** Called when the user navigates to a different page. */
  onPageChange: (page: number) => void;
  /** Controls button and text sizing. Defaults to `"lg"`. Only `"lg"` and `"md"` are supported. */
  size?: Exclude<PaginationSize, "sm">;
  className?: string;
}

/**
 * Discriminated union of all pagination variants.
 * Use the `type` prop to select between `"simple"`, `"count"`, and `"list"`.
 */
export type PaginationProps =
  | SimplePaginationProps
  | CountPaginationProps
  | ListPaginationProps;

function getPageNumbers(currentPage: number, totalPages: number) {
  const pages: (number | string)[] = [];
  const maxPagesToShow = 7;

  if (totalPages <= maxPagesToShow) {
    for (let i = 1; i <= totalPages; i++) {
      pages.push(i);
    }
  } else {
    pages.push(1);

    let startPage = Math.max(2, currentPage - 1);
    let endPage = Math.min(totalPages - 1, currentPage + 1);

    if (currentPage <= 3) {
      endPage = 5;
    } else if (currentPage >= totalPages - 2) {
      startPage = totalPages - 4;
    }

    if (startPage > 2) {
      pages.push("start-ellipsis");
    }

    for (let i = startPage; i <= endPage; i++) {
      pages.push(i);
    }

    if (endPage < totalPages - 1) {
      pages.push("end-ellipsis");
    }

    pages.push(totalPages);
  }

  return pages;
}

function sizedTextProps(isSmall: boolean, variant: "mono" | "muted") {
  if (variant === "mono") {
    return isSmall ? { secondaryMono: true } : { mainUiMono: true };
  }
  return isSmall ? { secondaryBody: true } : { mainUiMuted: true };
}

interface NavButtonsProps {
  currentPage: number;
  totalPages: number;
  onPageChange: (page: number) => void;
  size: PaginationSize;
  children?: React.ReactNode;
}

function NavButtons({
  currentPage,
  totalPages,
  onPageChange,
  size,
  children,
}: NavButtonsProps) {
  return (
    <>
      <Button
        icon={SvgChevronLeft}
        onClick={() => onPageChange(currentPage - 1)}
        disabled={currentPage <= 1}
        size={size}
        prominence="tertiary"
      />
      {children}
      <Button
        icon={SvgChevronRight}
        onClick={() => onPageChange(currentPage + 1)}
        disabled={currentPage >= totalPages}
        size={size}
        prominence="tertiary"
      />
    </>
  );
}

/**
 * Table pagination component with three variants: `simple`, `count`, and `list`.
 * Pass the `type` prop to select the variant, and the component will render the
 * appropriate UI.
 */
export default function Pagination(props: PaginationProps) {
  switch (props.type) {
    case "simple":
      return <SimplePaginationInner {...props} />;
    case "count":
      return <CountPaginationInner {...props} />;
    case "list":
      return <ListPaginationInner {...props} />;
  }
}

function SimplePaginationInner({
  currentPage,
  totalPages,
  onPageChange,
  showUnits,
  size = "lg",
  className,
}: SimplePaginationProps) {
  const isSmall = size === "sm";

  return (
    <div className={cn("flex items-center gap-1", className)}>
      <NavButtons
        currentPage={currentPage}
        totalPages={totalPages}
        onPageChange={onPageChange}
        size={size}
      >
        <Text {...sizedTextProps(isSmall, "mono")} text03>
          {currentPage}
          <Text as="span" {...sizedTextProps(isSmall, "muted")} text03>
            /
          </Text>
          {totalPages}
        </Text>
        {showUnits && (
          <Text {...sizedTextProps(isSmall, "muted")} text03>
            pages
          </Text>
        )}
      </NavButtons>
    </div>
  );
}

function CountPaginationInner({
  pageSize,
  totalItems,
  currentPage,
  totalPages,
  onPageChange,
  showPage = true,
  showGoTo,
  onGoTo,
  showUnits,
  size = "lg",
  className,
}: CountPaginationProps) {
  const isSmall = size === "sm";
  const rangeStart = (currentPage - 1) * pageSize + 1;
  const rangeEnd = Math.min(currentPage * pageSize, totalItems);
  const currentItems = `${rangeStart}~${rangeEnd}`;

  return (
    <div className={cn("flex items-center gap-1", className)}>
      <Text {...sizedTextProps(isSmall, "mono")} text03>
        {currentItems}
      </Text>
      <Text {...sizedTextProps(isSmall, "muted")} text03>
        of
      </Text>
      <Text {...sizedTextProps(isSmall, "mono")} text03>
        {totalItems}
      </Text>
      {showUnits && (
        <Text {...sizedTextProps(isSmall, "muted")} text03>
          items
        </Text>
      )}

      {showPage && (
        <NavButtons
          currentPage={currentPage}
          totalPages={totalPages}
          onPageChange={onPageChange}
          size={size}
        >
          <Text {...sizedTextProps(isSmall, "mono")} text03>
            {currentPage}
          </Text>
        </NavButtons>
      )}

      {showGoTo && onGoTo && (
        <Button onClick={onGoTo} size={size} prominence="tertiary">
          Go to
        </Button>
      )}
    </div>
  );
}

function ListPaginationInner({
  currentPage,
  totalPages,
  onPageChange,
  size = "lg",
  className,
}: ListPaginationProps) {
  const pageNumbers = getPageNumbers(currentPage, totalPages);

  return (
    <div className={cn("flex items-center gap-1", className)}>
      <NavButtons
        currentPage={currentPage}
        totalPages={totalPages}
        onPageChange={onPageChange}
        size={size}
      >
        <div className="flex items-center">
          {pageNumbers.map((page) => {
            if (typeof page === "string") {
              return (
                <Text
                  key={page}
                  mainUiMuted={size === "lg"}
                  secondaryBody={size === "md"}
                  text03
                >
                  ...
                </Text>
              );
            }

            const pageNum = page as number;
            const isActive = pageNum === currentPage;

            return (
              <Button
                key={pageNum}
                onClick={() => onPageChange(pageNum)}
                size={size}
                prominence="tertiary"
                transient={isActive}
                icon={({ className: iconClassName }) => (
                  <div
                    className={cn(
                      iconClassName,
                      "flex flex-col justify-center"
                    )}
                  >
                    {size === "lg" ? (
                      <Text
                        mainUiBody={isActive}
                        mainUiMuted={!isActive}
                        text04={isActive}
                        text02={!isActive}
                      >
                        {pageNum}
                      </Text>
                    ) : (
                      <Text
                        secondaryAction={isActive}
                        secondaryBody={!isActive}
                        text04={isActive}
                        text02={!isActive}
                      >
                        {pageNum}
                      </Text>
                    )}
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
