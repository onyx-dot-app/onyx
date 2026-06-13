"use client";

import React, { useState, useImperativeHandle, forwardRef } from "react";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuGroup,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
  DropdownMenuCheckboxItem,
} from "@/components/ui/dropdown-menu";
import { Input } from "@/components/ui/input";
import { Badge } from "@/components/ui/badge";
import { AccessType, ValidStatuses } from "@/lib/types";
import { Button } from "@opal/components";
import { SvgFilter } from "@opal/icons";
export interface FilterOptions {
  accessType: AccessType[] | null;
  docsCountFilter: {
    operator: ">" | "<" | "=" | null;
    value: number | null;
  };
  lastStatus: ValidStatuses[] | null;
}

interface FilterComponentProps {
  onFilterChange: (filters: FilterOptions) => void;
}

export const FilterComponent = forwardRef<
  { resetFilters: () => void },
  FilterComponentProps
>(({ onFilterChange }, ref) => {
  const [isOpen, setIsOpen] = useState(false);
  const [filters, setFilters] = useState<FilterOptions>({
    accessType: null,
    docsCountFilter: {
      operator: null,
      value: null,
    },
    lastStatus: null,
  });

  // Local state for tracking selected filters before applying
  const [docsOperator, setDocsOperator] = useState<">" | "<" | "=" | null>(
    null
  );
  const [docsValue, setDocsValue] = useState<string>("");
  const [selectedAccessTypes, setSelectedAccessTypes] = useState<AccessType[]>(
    []
  );
  const [selectedStatuses, setSelectedStatuses] = useState<ValidStatuses[]>([]);

  // Expose resetFilters method via ref
  useImperativeHandle(ref, () => ({
    resetFilters: () => {
      setDocsOperator(null);
      setDocsValue("");
      setSelectedAccessTypes([]);
      setSelectedStatuses([]);
      setFilters({
        accessType: null,
        docsCountFilter: {
          operator: null,
          value: null,
        },
        lastStatus: null,
      });
    },
  }));

  const handleAccessTypeChange = (accessType: AccessType) => {
    const newAccessTypes = selectedAccessTypes.includes(accessType)
      ? selectedAccessTypes.filter((type) => type !== accessType)
      : [...selectedAccessTypes, accessType];

    setSelectedAccessTypes(newAccessTypes);
  };

  const handleStatusChange = (status: ValidStatuses) => {
    const newStatuses = selectedStatuses.includes(status)
      ? selectedStatuses.filter((s) => s !== status)
      : [...selectedStatuses, status];

    setSelectedStatuses(newStatuses);
  };

  const applyFilters = () => {
    const newFilters = {
      ...filters,
      accessType: selectedAccessTypes.length > 0 ? selectedAccessTypes : null,
      lastStatus: selectedStatuses.length > 0 ? selectedStatuses : null,
      docsCountFilter: {
        operator: docsOperator,
        value: docsValue ? parseInt(docsValue) : null,
      },
    };

    setFilters(newFilters);
    onFilterChange(newFilters);
    setIsOpen(false);
  };

  // Sync local state with filters when dropdown opens
  const handleOpenChange = (open: boolean) => {
    if (open) {
      // When opening, initialize local state from current filters
      setSelectedAccessTypes(filters.accessType || []);
      setSelectedStatuses(filters.lastStatus || []);
      setDocsOperator(filters.docsCountFilter.operator);
      setDocsValue(
        filters.docsCountFilter.value !== null
          ? filters.docsCountFilter.value.toString()
          : ""
      );
    }
    setIsOpen(open);
  };

  const hasActiveFilters =
    (filters.accessType && filters.accessType.length > 0) ||
    (filters.lastStatus && filters.lastStatus.length > 0) ||
    filters.docsCountFilter.operator !== null;

  return (
    <div className="relative">
      <DropdownMenu open={isOpen} onOpenChange={handleOpenChange}>
        <DropdownMenuTrigger asChild>
          <Button
            icon={SvgFilter}
            prominence="secondary"
            interaction={isOpen ? "hover" : "rest"}
          />
        </DropdownMenuTrigger>
        <DropdownMenuContent
          align="end"
          className="w-72"
          onCloseAutoFocus={(e) => e.preventDefault()}
        >
          <div className="flex items-center justify-between px-2 py-1.5">
            <DropdownMenuLabel className="text-base font-medium">
              筛选连接器
            </DropdownMenuLabel>
          </div>
          <DropdownMenuSeparator />

          <DropdownMenuGroup>
            <DropdownMenuLabel className="px-2 py-1.5 text-xs text-muted-foreground">
              访问类型
            </DropdownMenuLabel>
            <div onClick={(e) => e.stopPropagation()}>
              <DropdownMenuCheckboxItem
                checked={selectedAccessTypes.includes("public")}
                onCheckedChange={() => handleAccessTypeChange("public")}
                className="flex items-center justify-between"
                onSelect={(e) => e.preventDefault()}
              >
                公开
              </DropdownMenuCheckboxItem>
              <DropdownMenuCheckboxItem
                checked={selectedAccessTypes.includes("private")}
                onCheckedChange={() => handleAccessTypeChange("private")}
                className="flex items-center justify-between"
                onSelect={(e) => e.preventDefault()}
              >
                私有
              </DropdownMenuCheckboxItem>
              <DropdownMenuCheckboxItem
                checked={selectedAccessTypes.includes("sync")}
                onCheckedChange={() => handleAccessTypeChange("sync")}
                className="flex items-center justify-between"
                onSelect={(e) => e.preventDefault()}
              >
                自动同步
              </DropdownMenuCheckboxItem>
            </div>
          </DropdownMenuGroup>

          <DropdownMenuSeparator />

          <DropdownMenuGroup>
            <DropdownMenuLabel className="px-2 py-1.5 text-xs text-muted-foreground">
              最近状态
            </DropdownMenuLabel>
            <div onClick={(e) => e.stopPropagation()}>
              <DropdownMenuCheckboxItem
                checked={selectedStatuses.includes("success")}
                onCheckedChange={() => handleStatusChange("success")}
                className="flex items-center justify-between"
                onSelect={(e) => e.preventDefault()}
              >
                成功
              </DropdownMenuCheckboxItem>
              <DropdownMenuCheckboxItem
                checked={selectedStatuses.includes("failed")}
                onCheckedChange={() => handleStatusChange("failed")}
                className="flex items-center justify-between"
                onSelect={(e) => e.preventDefault()}
              >
                失败
              </DropdownMenuCheckboxItem>
              <DropdownMenuCheckboxItem
                checked={selectedStatuses.includes("in_progress")}
                onCheckedChange={() => handleStatusChange("in_progress")}
                className="flex items-center justify-between"
                onSelect={(e) => e.preventDefault()}
              >
                进行中
              </DropdownMenuCheckboxItem>
              <DropdownMenuCheckboxItem
                checked={selectedStatuses.includes("not_started")}
                onCheckedChange={() => handleStatusChange("not_started")}
                className="flex items-center justify-between"
                onSelect={(e) => e.preventDefault()}
              >
                未开始
              </DropdownMenuCheckboxItem>
              <DropdownMenuCheckboxItem
                checked={selectedStatuses.includes("completed_with_errors")}
                onCheckedChange={() =>
                  handleStatusChange("completed_with_errors")
                }
                className="flex items-center justify-between"
                onSelect={(e) => e.preventDefault()}
              >
                已完成但有错误
              </DropdownMenuCheckboxItem>
            </div>
          </DropdownMenuGroup>

          <DropdownMenuSeparator />

          <DropdownMenuGroup>
            <DropdownMenuLabel className="px-2 py-1.5 text-xs text-muted-foreground">
              文档数量
            </DropdownMenuLabel>
            <div
              className="flex items-center px-2 py-2 gap-2"
              onClick={(e) => e.stopPropagation()}
            >
              <div className="flex gap-2">
                <Button
                  prominence={docsOperator !== ">" ? "secondary" : "primary"}
                  onClick={(e) => {
                    e.preventDefault();
                    e.stopPropagation();
                    setDocsOperator(docsOperator === ">" ? null : ">");
                  }}
                  type="button"
                >
                  &gt;
                </Button>
                <Button
                  prominence={docsOperator !== "<" ? "secondary" : "primary"}
                  onClick={(e) => {
                    e.preventDefault();
                    e.stopPropagation();
                    setDocsOperator(docsOperator === "<" ? null : "<");
                  }}
                  type="button"
                >
                  &lt;
                </Button>
                <Button
                  prominence={docsOperator !== "=" ? "secondary" : "primary"}
                  onClick={(e) => {
                    e.preventDefault();
                    e.stopPropagation();
                    setDocsOperator(docsOperator === "=" ? null : "=");
                  }}
                  type="button"
                >
                  =
                </Button>
              </div>
              <Input
                type="number"
                placeholder="数量"
                value={docsValue}
                onChange={(e) => setDocsValue(e.target.value)}
                className="h-8 w-full"
                onClick={(e) => e.stopPropagation()}
              />
            </div>
            <div className="px-2 py-1.5">
              <Button
                width="full"
                onClick={(e) => {
                  e.preventDefault();
                  e.stopPropagation();
                  applyFilters();
                }}
                type="button"
              >
                应用
              </Button>
            </div>
          </DropdownMenuGroup>
        </DropdownMenuContent>
      </DropdownMenu>

      {hasActiveFilters && (
        <div className="absolute -top-1 -right-1">
          <Badge className="h-2 bg-red-400! border-red-400! w-2 p-0 border-2 flex items-center justify-center" />
        </div>
      )}
    </div>
  );
});

FilterComponent.displayName = "FilterComponent";
