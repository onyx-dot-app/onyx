import { Button } from "@opal/components/buttons/Button/components";
import SvgEdit from "@opal/icons/edit";
import type { IconFunctionComponent } from "@opal/types";
import { useRef, useState } from "react";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

interface ContentContainerHeadingProps {
  /** Optional icon component. Rendered at 2rem with p-0.5 container (total 36px = line-height). */
  icon?: IconFunctionComponent;

  /** Icon placement relative to the content. Default: `"left"`. */
  iconPlacement?: "top" | "left";

  /** Main heading text. */
  title: string;

  /** Optional description below the title. */
  description?: React.ReactNode;

  /** Enable inline editing of the title. */
  editable?: boolean;

  /** Called when the user commits an edit. */
  onTitleChange?: (newTitle: string) => void;
}

// ---------------------------------------------------------------------------
// ContentContainerHeading
// ---------------------------------------------------------------------------

function ContentContainerHeading({
  icon: Icon,
  iconPlacement = "left",
  title,
  description,
  editable,
  onTitleChange,
}: ContentContainerHeadingProps) {
  const [editing, setEditing] = useState(false);
  const inputRef = useRef<HTMLInputElement>(null);

  function commit() {
    if (!inputRef.current) return;
    const value = inputRef.current.value.trim();
    if (value && value !== title) onTitleChange?.(value);
    setEditing(false);
  }

  return (
    <div className="opal-cc-heading" data-icon-placement={iconPlacement}>
      {Icon && (
        <div className="opal-cc-heading-icon-container shrink-0 p-0.5">
          <Icon
            className="opal-cc-heading-icon"
            style={{ width: "2rem", height: "2rem" }}
          />
        </div>
      )}

      <div className="opal-cc-heading-content">
        <div className="opal-cc-heading-title-row">
          {editing ? (
            <input
              ref={inputRef}
              className="opal-cc-heading-input font-heading-h2 text-text-04"
              defaultValue={title}
              autoFocus
              onBlur={commit}
              onKeyDown={(e) => {
                if (e.key === "Enter") commit();
                if (e.key === "Escape") setEditing(false);
              }}
            />
          ) : (
            <span
              className={`opal-cc-heading-title font-heading-h2 text-text-04${
                editable ? " cursor-pointer" : ""
              }`}
              onClick={editable ? () => setEditing(true) : undefined}
            >
              {title}
            </span>
          )}

          {editable && !editing && (
            <div className="opal-cc-heading-edit-button p-1">
              <Button
                icon={SvgEdit}
                prominence="internal"
                size="md"
                tooltip="Edit"
                tooltipSide="right"
                onClick={() => setEditing(true)}
              />
            </div>
          )}
        </div>

        {description && (
          <div className="opal-cc-heading-description font-secondary-body text-text-03">
            {description}
          </div>
        )}
      </div>
    </div>
  );
}

export { ContentContainerHeading, type ContentContainerHeadingProps };
