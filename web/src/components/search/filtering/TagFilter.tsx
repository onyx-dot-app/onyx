import React, { useState, useEffect } from "react";
import { Tag } from "@/lib/types";
import { FiTag } from "react-icons/fi";
import { Input } from "@/components/ui/input";
import { Checkbox } from "@/components/ui/checkbox";

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

  return (
    <div className="space-y-2">
      <Input
        placeholder="Search tags..."
        value={filterValue}
        onChange={(e) => setFilterValue(e.target.value)}
        className="border border-border w-full"
      />
      <div className="space-y-2 max-h-48 overflow-y-auto">
        {filteredTags
          .sort((a, b) =>
            selectedTags.some(
              (t) => t.tag_key === a.tag_key && t.tag_value === a.tag_value
            )
              ? -1
              : 1
          )
          .map((tag) => (
            <div
              key={`${tag.tag_key}-${tag.tag_value}`}
              className="flex items-center space-x-2"
            >
              <Checkbox
                id={`${tag.tag_key}-${tag.tag_value}`}
                checked={selectedTags.some(
                  (t) =>
                    t.tag_key === tag.tag_key && t.tag_value === tag.tag_value
                )}
                onCheckedChange={() => toggleTag(tag)}
              />
              <label
                htmlFor={`${tag.tag_key}-${tag.tag_value}`}
                className="text-sm cursor-pointer flex items-center"
              >
                <FiTag className="mr-1" />
                {tag.tag_key}={tag.tag_value}
              </label>
            </div>
          ))}
      </div>
    </div>
  );
}
