import React, { useState, useEffect } from "react";
import { Tag } from "@/lib/types";
import { Input } from "@/components/ui/input";

interface TagFilterProps {
  tags: Tag[];
  selectedTags: Tag[];
  setSelectedTags: React.Dispatch<React.SetStateAction<Tag[]>>;
}

export function TagFilter({
  tags,
  selectedTags,
  setSelectedTags,
}: TagFilterProps) {
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
        className="w-full"
      />
      <div className="space-y-1 max-h-48 overflow-y-auto">
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
              className={`px-3 py-2 text-sm cursor-pointer transition-colors duration-200 ${
                selectedTags.some(
                  (t) =>
                    t.tag_key === tag.tag_key && t.tag_value === tag.tag_value
                )
                  ? "bg-accent text-accent-foreground"
                  : "hover:bg-accent hover:text-accent-foreground"
              }`}
              onClick={() => toggleTag(tag)}
            >
              {tag.tag_key}={tag.tag_value}
            </div>
          ))}
      </div>
    </div>
  );
}
