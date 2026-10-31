"use client";

import { useState } from "react";
import { useTranslations } from "next-intl";
import { SvgEmpty } from "@opal/icons";
import { Content } from "@opal/layouts";
import {
  Dropdown,
  InputTypeIn,
  type DropdownMenuItem,
  type DropdownMenuRow,
} from "@opal/components";
import { cn } from "@opal/utils";
import type { ResourcePopoverProps } from "@/views/admin/GroupsPage/SharedGroupResources/interfaces";

/**
 * A type-in that lists the resources the caller already filtered by its
 * text, in titled sections. The rendered item can hold its own buttons, so
 * each is a custom row.
 */
function ResourcePopover({
  placeholder,
  searchValue,
  onSearchChange,
  sections,
}: ResourcePopoverProps) {
  const t = useTranslations("admin.groups");
  const [open, setOpen] = useState(false);

  const totalItems = sections.reduce((sum, s) => sum + s.items.length, 0);
  const items: DropdownMenuItem[] =
    totalItems === 0
      ? [
          {
            kind: "custom",
            id: "no-results",
            disabled: true,
            render: ({ props }) => (
              <div {...props} className="px-3 py-3">
                <Content
                  icon={SvgEmpty}
                  title={t("sharedResources.popover.noResults.title")}
                  sizePreset="secondary"
                  variant="section"
                />
              </div>
            ),
          },
        ]
      : sections
          .filter((section) => section.items.length > 0)
          .map(
            (section, idx): DropdownMenuItem => ({
              kind: "group",
              ...(section.label !== undefined && { title: section.label }),
              items: section.items.map(
                (item): DropdownMenuRow => ({
                  // `item.disabled` is a look (already picked), not a lock: the
                  // row still toggles.
                  kind: "custom",
                  id: `${section.label ?? idx}-${item.key}`,
                  keywords: [item.label],
                  keepOpen: true,
                  onActivate: item.onSelect,
                  render: ({ highlighted, props }) => (
                    <div
                      {...props}
                      aria-label={item.label}
                      className={cn(
                        "rounded-08 cursor-pointer transition-colors",
                        item.disabled
                          ? "bg-background-tint-02"
                          : highlighted && "bg-background-tint-02"
                      )}
                    >
                      {item.render(!!item.disabled)}
                    </div>
                  ),
                })
              ),
            })
          );

  return (
    <Dropdown open={open} onOpenChange={setOpen}>
      <Dropdown.Trigger asChild typeIn behavior="open">
        <InputTypeIn
          placeholder={placeholder}
          value={searchValue}
          onChange={(e) => {
            onSearchChange(e.target.value);
            // Typing opens the list, as a type-in does.
            setOpen(true);
          }}
        />
      </Dropdown.Trigger>
      <Dropdown.Data label={placeholder} items={items} />
    </Dropdown>
  );
}

export default ResourcePopover;
