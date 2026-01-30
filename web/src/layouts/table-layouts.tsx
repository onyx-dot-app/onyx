import { cn } from "@/lib/utils";
import { WithoutStyles } from "@/types";
import React from "react";

// ============================================================================
// TABLE LAYOUTS - For building table-like structures without raw divs
// ============================================================================

/**
 * TableRow - A horizontal row layout for tables/lists
 *
 * @param selected - If true, applies selected background styling
 * @param onClick - Click handler for the row
 * @param children - Row content
 */
interface TableRowProps
  extends WithoutStyles<React.HtmlHTMLAttributes<HTMLDivElement>> {
  selected?: boolean;
}
function TableRow({ selected, children, onClick, ...rest }: TableRowProps) {
  return (
    <div
      className={cn("table-row-layout", onClick && "cursor-pointer")}
      data-selected={selected ? "true" : undefined}
      onClick={onClick}
      {...rest}
    >
      {children}
    </div>
  );
}

/**
 * TableCell - A cell within a table row
 *
 * @param flex - If true, cell takes remaining space (flex: 1)
 * @param fixed - If true, cell has fixed width (doesn't shrink)
 * @param width - Optional fixed width in rem
 * @param children - Cell content
 */
interface TableCellProps
  extends WithoutStyles<React.HtmlHTMLAttributes<HTMLDivElement>> {
  flex?: boolean;
  width?: number;
}
function TableCell({ flex, width, children, ...rest }: TableCellProps) {
  return (
    <div
      className="table-cell-layout"
      data-flex={flex ? "true" : undefined}
      data-fixed={width ? "true" : undefined}
      style={width ? { width: `${width}rem` } : undefined}
      {...rest}
    >
      {children}
    </div>
  );
}

/**
 * SidebarLayout - A fixed-width sidebar container
 *
 * @param children - Sidebar content
 */
interface SidebarLayoutProps
  extends WithoutStyles<React.HtmlHTMLAttributes<HTMLDivElement>> {}
function SidebarLayout({ children, ...rest }: SidebarLayoutProps) {
  return (
    <div className="sidebar-layout" {...rest}>
      {children}
    </div>
  );
}

/**
 * TwoColumnLayout - A two-column layout with sidebar and content
 *
 * @param children - Should contain sidebar and content sections
 */
interface TwoColumnLayoutProps
  extends WithoutStyles<React.HtmlHTMLAttributes<HTMLDivElement>> {
  minHeight?: number;
}
function TwoColumnLayout({
  minHeight,
  children,
  ...rest
}: TwoColumnLayoutProps) {
  return (
    <div
      className="two-column-layout"
      style={minHeight ? { minHeight: `${minHeight}rem` } : undefined}
      {...rest}
    >
      {children}
    </div>
  );
}

/**
 * ContentColumn - The main content area in a two-column layout
 */
interface ContentColumnProps
  extends WithoutStyles<React.HtmlHTMLAttributes<HTMLDivElement>> {}
function ContentColumn({ children, ...rest }: ContentColumnProps) {
  return (
    <div className="content-column-layout" {...rest}>
      {children}
    </div>
  );
}

/**
 * HiddenInput - A hidden input element (for file uploads, etc.)
 */
interface HiddenInputProps extends React.InputHTMLAttributes<HTMLInputElement> {
  inputRef?: React.Ref<HTMLInputElement>;
}
function HiddenInput({ inputRef, ...rest }: HiddenInputProps) {
  return <input ref={inputRef} className="hidden-input" {...rest} />;
}

/**
 * CheckboxCell - A fixed-width cell for checkboxes in tables
 */
interface CheckboxCellProps
  extends WithoutStyles<React.HtmlHTMLAttributes<HTMLDivElement>> {}
function CheckboxCell({ children, ...rest }: CheckboxCellProps) {
  return (
    <div className="checkbox-cell-layout" {...rest}>
      {children}
    </div>
  );
}

/**
 * SourceIconsRow - A row of source icons
 */
interface SourceIconsRowProps
  extends WithoutStyles<React.HtmlHTMLAttributes<HTMLDivElement>> {}
function SourceIconsRow({ children, ...rest }: SourceIconsRowProps) {
  return (
    <div className="source-icons-layout" {...rest}>
      {children}
    </div>
  );
}

export {
  TableRow,
  TableCell,
  SidebarLayout,
  TwoColumnLayout,
  ContentColumn,
  HiddenInput,
  CheckboxCell,
  SourceIconsRow,
};
