"use client";

import { Section } from "@opal/layouts";
import React from "react";
import { useTranslations } from "next-intl";
import * as TableLayouts from "@/layouts/table-layouts";
import {
  Text,
  InputCheckbox,
  Divider,
  InputTypeIn,
  Spacer,
} from "@opal/components";
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
  searchPlaceholder,
  headerActions,
  emptyMessage,
  ariaLabelPrefix,
}: KnowledgeTableProps<T> & { ariaLabelPrefix?: string }) {
  const t = useTranslations("knowledge");
  return (
    <Section gap={0} alignItems="stretch" justifyContent="start">
      <Section
        flexDirection="row"
        justifyContent="start"
        alignItems="center"
        gap={2}
        height="auto"
      >
        {onSearchChange !== undefined && (
          <Section height="auto">
            <InputTypeIn
              value={searchValue ?? ""}
              onChange={(e) => onSearchChange?.(e.target.value)}
              placeholder={searchPlaceholder ?? t("table.filter.placeholder")}
              variant="internal"
              rightChildren={
                <SvgFilter className="w-4 h-4 stroke-text-02 shrink-0" />
              }
            />
          </Section>
        )}
        {headerActions}
      </Section>

      <Spacer rem={0.5} />

      <TableLayouts.TableRow>
        <TableLayouts.CheckboxCell />
        {columns.map((column) => (
          <TableLayouts.TableCell
            key={column.key}
            flex={!column.width}
            width={column.width}
          >
            <Section
              flexDirection="row"
              justifyContent="start"
              alignItems="center"
              gap={1}
              height="auto"
            >
              <Text font="secondary-body" color="text-03">
                {column.header}
              </Text>
            </Section>
          </TableLayouts.TableCell>
        ))}
      </TableLayouts.TableRow>

      <Divider paddingParallel={0} paddingPerpendicular={0} />

      {items.length === 0 ? (
        <Section height="auto" padding={4}>
          <Text color="text-03" font="secondary-body">
            {emptyMessage ?? t("table.empty.description")}
          </Text>
        </Section>
      ) : (
        <Section gap={0} alignItems="stretch" height="auto">
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
                  <InputCheckbox
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
        </Section>
      )}
    </Section>
  );
}
