import type { ReactNode } from "react";
import type { RichStr } from "@opal/types";
import { useDirection } from "@radix-ui/react-direction";
import { Button, Text } from "@opal/components";
import { SvgSidebar, SvgChevronLeft, SvgChevronRight } from "@opal/icons";

interface DocumentPreviewControlsProps {
  label: string;
  previousLabel: string;
  nextLabel: string;
  thumbnailsLabel: string;
  counter: string | RichStr;
  page: number;
  pageCount: number;
  showThumbnails: boolean;
  onToggleThumbnails: () => void;
  onPageChange: (page: number) => void;
  children?: ReactNode;
}

export default function DocumentPreviewControls({
  label,
  previousLabel,
  nextLabel,
  thumbnailsLabel,
  counter,
  page,
  pageCount,
  showThumbnails,
  onToggleThumbnails,
  onPageChange,
  children,
}: DocumentPreviewControlsProps) {
  const direction = useDirection();
  return (
    <div
      role="toolbar"
      aria-label={label}
      className="flex shrink-0 flex-wrap items-center justify-between gap-1 border-b border-border-02 px-2 py-1.5"
    >
      <div className="flex items-center gap-1">
        <Button
          icon={SvgSidebar}
          size="xs"
          prominence={showThumbnails ? "secondary" : "tertiary"}
          aria-label={thumbnailsLabel}
          aria-pressed={showThumbnails}
          onClick={onToggleThumbnails}
        />
        <Button
          icon={direction === "rtl" ? SvgChevronRight : SvgChevronLeft}
          size="xs"
          prominence="tertiary"
          aria-label={previousLabel}
          disabled={page <= 1}
          onClick={() => onPageChange(page - 1)}
        />
        <Text font="secondary-body" color="text-03">
          {counter}
        </Text>
        <Button
          icon={direction === "rtl" ? SvgChevronLeft : SvgChevronRight}
          size="xs"
          prominence="tertiary"
          aria-label={nextLabel}
          disabled={page >= pageCount}
          onClick={() => onPageChange(page + 1)}
        />
      </div>
      {children}
    </div>
  );
}
