"use client";

import React from "react";
import * as GeneralLayouts from "@/layouts/general-layouts";
import * as TableLayouts from "@/layouts/table-layouts";
import Text from "@/refresh-components/texts/Text";
import { Checkbox, Divider, InputTypeIn, Spacer } from "@opal/components";
import { SvgFilter } from "@opal/icons";

export interface KnowledgeTableColumn<T> {
  key: string;
  header: string;
  sortable?: boolean;
  width?: number;
  render: (item: T) => React.ReactNode;
}

interface KnowledgeTableProps<T> {
  items: T[];
  columns: KnowledgeTableColumn<T>[];
  getItemId: (item: T) => string | number;
  selectedIds: (string | number)[];
  onToggleItem: (id: string | number) => void;
  searchValue?: string;
  onSearchChange?: (value: string) => void;
  searchPlaceholder?: string;
  headerActions?: React.ReactNode;
  emptyMessage?: string;
}

export function KnowledgeTable<T>({
  items,
  columns,
  getItemId,
  selectedIds,
  onToggleItem,
  searchValue,
  onSearchChange,
  searchPlaceholder = "Filter...",
  headerActions,
  emptyMessage = "No items available.",
  ariaLabelPrefix,
}: KnowledgeTableProps<T> & { ariaLabelPrefix?: string }) {
  return (
    <GeneralLayouts.Section gap={0} alignItems="stretch" justifyContent="start">
      <GeneralLayouts.Section
        flexDirection="row"
        justifyContent="start"
        alignItems="center"
        gap={0.5}
        height="auto"
      >
        {onSearchChange !== undefined && (
          <GeneralLayouts.Section height="auto">
            <InputTypeIn
              value={searchValue ?? ""}
              onChange={(e) => onSearchChange?.(e.target.value)}
              placeholder={searchPlaceholder}
              variant="internal"
              rightChildren={
                <SvgFilter className="w-4 h-4 stroke-text-02 shrink-0" />
              }
            />
          </GeneralLayouts.Section>
        )}
        {headerActions}
      </GeneralLayouts.Section>

      <Spacer rem={0.5} />

      <TableLayouts.TableRow>
        <TableLayouts.CheckboxCell />
        {columns.map((column) => (
          <TableLayouts.TableCell
            key={column.key}
            flex={!column.width}
            width={column.width}
          >
            <GeneralLayouts.Section
              flexDirection="row"
              justifyContent="start"
              alignItems="center"
              gap={0.25}
              height="auto"
            >
              <Text secondaryBody text03>
                {column.header}
              </Text>
            </GeneralLayouts.Section>
          </TableLayouts.TableCell>
        ))}
      </TableLayouts.TableRow>

      <Divider paddingParallel="fit" paddingPerpendicular="fit" />

      {items.length === 0 ? (
        <GeneralLayouts.Section height="auto" padding={1}>
          <Text text03 secondaryBody>
            {emptyMessage}
          </Text>
        </GeneralLayouts.Section>
      ) : (
        <GeneralLayouts.Section gap={0} alignItems="stretch" height="auto">
          {items.map((item) => {
            const id = getItemId(item);
            const isSelected = selectedIds.includes(id);

            return (
              <TableLayouts.TableRow
                key={String(id)}
                selected={isSelected}
                onClick={() => onToggleItem(id)}
                aria-label={
                  ariaLabelPrefix ? `${ariaLabelPrefix}-${id}` : undefined
                }
              >
                <TableLayouts.CheckboxCell>
                  <Checkbox
                    checked={isSelected}
                    onCheckedChange={() => onToggleItem(id)}
                  />
                </TableLayouts.CheckboxCell>
                {columns.map((column) => (
                  <TableLayouts.TableCell
                    key={column.key}
                    flex={!column.width}
                    width={column.width}
                  >
                    {column.render(item)}
                  </TableLayouts.TableCell>
                ))}
              </TableLayouts.TableRow>
            );
          })}
        </GeneralLayouts.Section>
      )}
    </GeneralLayouts.Section>
  );
}
