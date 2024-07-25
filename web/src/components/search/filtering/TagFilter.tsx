import { containsObject, objectsAreEquivalent } from "@/lib/contains";
import { Tag } from "@/lib/types";
import { useEffect, useRef, useState } from "react";
import { FiTag, FiX } from "react-icons/fi";
import debounce from "lodash/debounce";
import { getValidTags } from "@/lib/tags/tagUtils";

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
  const [tagOptionsAreVisible, setTagOptionsAreVisible] = useState(false);
  const [filteredTags, setFilteredTags] = useState<Tag[]>(tags);
  const inputRef = useRef<HTMLInputElement>(null);
  const popupRef = useRef<HTMLDivElement>(null);

  const onSelectTag = (tag: Tag) => {
    setSelectedTags((prev) => {
      if (containsObject(prev, tag)) {
        return prev.filter((t) => !objectsAreEquivalent(t, tag));
      } else {
        return [...prev, tag];
      }
    });
  };

  useEffect(() => {
    const handleClickOutside = (event: MouseEvent) => {
      if (
        popupRef.current &&
        !popupRef.current.contains(event.target as Node) &&
        inputRef.current &&
        !inputRef.current.contains(event.target as Node)
      ) {
        setTagOptionsAreVisible(false);
      }
    };

    document.addEventListener("mousedown", handleClickOutside);
    return () => {
      document.removeEventListener("mousedown", handleClickOutside);
    };
  }, []);

  const debouncedFetchTags = useRef(
    debounce(async (value: string) => {
      if (value) {
        const fetchedTags = await getValidTags(value);
        setFilteredTags(fetchedTags);
      } else {
        setFilteredTags(tags);
      }
    }, 50)
  ).current;

  useEffect(() => {
    debouncedFetchTags(filterValue);

    return () => {
      debouncedFetchTags.cancel();
    };
  }, [filterValue, tags, debouncedFetchTags]);

  const handleFilterChange = (event: React.ChangeEvent<HTMLInputElement>) => {
    setFilterValue(event.target.value);
  };

  return (
    <div className="relative">
      <input
        ref={inputRef}
        className="w-full border border-border py-0.5 px-2 rounded text-sm h-8"
        placeholder="Find a tag"
        value={filterValue}
        onChange={handleFilterChange}
        onFocus={() => setTagOptionsAreVisible(true)}
      />
      {selectedTags.length > 0 && (
        <div className="mt-2">
          <div className="mt-1 flex flex-wrap gap-x-1 gap-y-1">
            {selectedTags.map((tag) => (
              <div
                key={tag.tag_key + tag.tag_value}
                onClick={() => onSelectTag(tag)}
                className="max-w-full break-all line-clamp-1 text-ellipsis flex text-sm border border-border py-0.5 px-2 rounded cursor-pointer bg-background hover:bg-hover"
              >
                {tag.tag_key}
                <b>=</b>
                {tag.tag_value}
                <FiX className="my-auto ml-1" />
              </div>
            ))}
          </div>
          <div
            onClick={() => setSelectedTags([])}
            className="pl-0.5 text-xs text-accent cursor-pointer mt-2 w-fit"
          >
            Clear all
          </div>
        </div>
      )}
      {tagOptionsAreVisible && (
        <div className="absolute top-0 right-0 transform translate-x-[105%] z-40">
          <div
            ref={popupRef}
            className="p-2 border border-border rounded shadow-lg w-72 bg-background"
          >
            <div className="flex border-b border-border font-medium pb-1 text-xs mb-2">
              <FiTag className="mr-1 my-auto" />
              Tags
            </div>
            <div className="flex flex-wrap gap-x-1 gap-y-1">
              {filteredTags.length > 0 ? (
                filteredTags.map((tag) => (
                  <div
                    key={tag.tag_key + tag.tag_value}
                    onClick={() => onSelectTag(tag)}
                    className={`
                    text-sm 
                    max-w-full
                    border 
                    border-border 
                    py-0.5 
                    px-2 
                    rounded 
                    cursor-pointer 
                    bg-background 
                    hover:bg-hover
                    ${selectedTags.includes(tag) ? "bg-hover" : ""}
                  `}
                  >
                    {tag.tag_key}
                    <b>=</b>
                    {tag.tag_value}
                  </div>
                ))
              ) : (
                <div className="text-sm px-2 py-2">No matching tags found</div>
              )}
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
