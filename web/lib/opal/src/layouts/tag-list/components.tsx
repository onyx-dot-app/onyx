import type { IconFunctionComponent } from "@opal/types";
import { Tag, type TagItem } from "@opal/components";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

interface TagListProps {
  /** Tags to render, in order. */
  items: TagItem[];

  /** Renders a remove button on every item tag. Omit for passive tags. */
  onRemove?: (id: string) => void;

  /**
   * Collapse items beyond this count into a "+N" tag whose tooltip names
   * the hidden entries.
   */
  maxVisible?: number;

  /** Icon on the "+N" overflow tag. */
  overflowIcon?: IconFunctionComponent;
}

// ---------------------------------------------------------------------------
// TagList
// ---------------------------------------------------------------------------

/**
 * Wrap-flowing row of Tags outside an input, for any labelled list. All
 * items show by default. `maxVisible` collapses the rest into a "+N" tag.
 */
function TagList({ items, onRemove, maxVisible, overflowIcon }: TagListProps) {
  const visible = maxVisible === undefined ? items : items.slice(0, maxVisible);
  const hidden = maxVisible === undefined ? [] : items.slice(maxVisible);

  return (
    <div className="flex w-full flex-wrap items-center gap-1">
      {visible.map((item) => (
        <Tag
          key={item.id}
          title={item.label}
          error={item.error}
          truncate
          onRemove={onRemove ? () => onRemove(item.id) : undefined}
        />
      ))}
      {hidden.length > 0 && (
        <Tag
          icon={overflowIcon}
          title={`+${hidden.length}`}
          tooltip={hidden.map((item) => item.label).join(", ")}
        />
      )}
    </div>
  );
}

export { TagList, type TagListProps };
