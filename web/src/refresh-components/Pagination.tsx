import { Button } from "@opal/components";
import Text from "@/refresh-components/texts/Text";
import { cn } from "@/lib/utils";
import { SvgChevronLeft, SvgChevronRight } from "@opal/icons";
import { Section } from "@/layouts/general-layouts";

interface PaginationProps {
  currentPage: number;
  totalPages: number;
  onPageChange: (page: number) => void;
}

export default function Pagination({
  currentPage,
  totalPages,
  onPageChange,
}: PaginationProps) {
  // Generate page numbers to display
  function getPageNumbers() {
    const pages: (number | string)[] = [];
    const maxPagesToShow = 7;

    if (totalPages <= maxPagesToShow) {
      // Show all pages if total is small
      for (let i = 1; i <= totalPages; i++) {
        pages.push(i);
      }
    } else {
      // Always show first page
      pages.push(1);

      // Calculate range around current page
      let startPage = Math.max(2, currentPage - 1);
      let endPage = Math.min(totalPages - 1, currentPage + 1);

      // Adjust range if we're near the start or end
      if (currentPage <= 3) {
        endPage = 5;
      } else if (currentPage >= totalPages - 2) {
        startPage = totalPages - 4;
      }

      // Add ellipsis if needed
      if (startPage > 2) {
        pages.push("...");
      }

      // Add middle pages
      for (let i = startPage; i <= endPage; i++) {
        pages.push(i);
      }

      // Add ellipsis if needed
      if (endPage < totalPages - 1) {
        pages.push("...");
      }

      // Always show last page
      pages.push(totalPages);
    }

    return pages;
  }

  const pageNumbers = getPageNumbers();

  return (
    <Section flexDirection="row" gap={0.25}>
      {/* Previous button */}
      <Button
        onClick={() => onPageChange(currentPage - 1)}
        disabled={currentPage === 1}
        prominence="tertiary"
        icon={SvgChevronLeft}
      />

      {/* Page numbers */}
      <Section flexDirection="row" gap={0} width="fit">
        {pageNumbers.map((page, index) => {
          if (page === "...") {
            return (
              <Text key={`ellipsis-${index}`} secondaryBody text03>
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
              prominence="tertiary"
              transient={isActive}
              icon={({ className }) => (
                <div className={cn(className, "flex flex-col justify-center")}>
                  <Text>{pageNum}</Text>
                </div>
              )}
            />
          );
        })}
      </Section>

      {/* Next button */}
      <Button
        onClick={() => onPageChange(currentPage + 1)}
        disabled={currentPage === totalPages}
        prominence="tertiary"
        icon={SvgChevronRight}
      />
    </Section>
  );
}
