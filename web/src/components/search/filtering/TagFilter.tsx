import React, { useState, useEffect } from "react";
import { Tag } from "@/lib/types";
import { Input } from "@/components/ui/input";

export const SelectableDropdown = ({
  value,
  selected,
  icon,
  toggle,
}: {
  value: string;
  selected: boolean;
  icon?: React.ReactNode;
  toggle: () => void;
}) => {
  return (
    <div
      key={value}
      className={`p-2 flex gap-x-2 items-center rounded cursor-pointer transition-colors duration-200 ${
        selected
          ? "bg-background-200 dark:bg-neutral-800"
          : "hover:bg-background-100 dark:hover:bg-neutral-800"
      }`}
      onClick={toggle}
    >
      {icon && <div className="flex-none">{icon}</div>}
      <span className="text-sm">{value}</span>
    </div>
  );
};

export function TagFilter({
  tags,
  selectedTags,
  setSelectedTags,
}: {
  tags: Tag[];
  selectedTags: Tag[];
  setSelectedTags: React.Dispatch<React.SetStateAction<Tag[]>>;
}) {
  const [filterValue, setFilterValue] = useState("");
  const [filteredTags, setFilteredTags] = useState<Tag[]>(tags);

  useEffect(() => {
    const lowercasedFilter = filterValue.toLowerCase();
    const filtered = tags.filter(
      (tag) =>
        tag.tag_key.toLowerCase().includes(lowercasedFilter) ||
        tag.tag_value.toLowerCase().includes(lowercasedFilter)
    );
    setFilteredTags(filtered);
  }, [filterValue, tags]);

  const toggleTag = (tag: Tag) => {
    setSelectedTags((prev) =>
      prev.some(
        (t) => t.tag_key === tag.tag_key && t.tag_value === tag.tag_value
      )
        ? prev.filter(
            (t) => t.tag_key !== tag.tag_key || t.tag_value !== tag.tag_value
          )
        : [...prev, tag]
    );
  };

  const isTagSelected = (tag: Tag) =>
    selectedTags.some(
      (t) => t.tag_key === tag.tag_key && t.tag_value === tag.tag_value
    );

  return (
    <div className="pt-4 h-full flex flex-col w-full">
      <div className="flex pb-2 px-4">
        <Input
          placeholder="Search tags..."
          value={filterValue}
          onChange={(e) => setFilterValue(e.target.value)}
          className="border border-neutral-200 dark:border-neutral-700 w-full"
        />
      </div>
      <div className="space-y-1 border-t pt-2 border-t-neutral-200 dark:border-t-neutral-700 px-4 default-scrollbar w-full max-h-64 overflow-y-auto">
        {filteredTags
          .sort((a, b) => a.tag_key.localeCompare(b.tag_key))
          .map((tag, index) => (
            <SelectableDropdown
              key={index}
              value={`${tag.tag_key}=${tag.tag_value}`}
              selected={isTagSelected(tag)}
              toggle={() => toggleTag(tag)}
            />
          ))}
      </div>
    </div>
  );
}
