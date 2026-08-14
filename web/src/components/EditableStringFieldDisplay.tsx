import { SvgEdit } from "@opal/icons";
import { useEffect, useRef, useState } from "react";
import { Input } from "@/components/ui/input";
import { cn } from "@opal/utils";
import IconButton from "@/refresh-components/buttons/IconButton";
import { SvgCheck, SvgX } from "@opal/icons";
interface EditableStringFieldDisplayProps {
  value: string;
  isEditable: boolean;
  onUpdate: (newValue: string) => Promise<void>;
  textClassName?: string;
  scale?: number;
}

export function EditableStringFieldDisplay({
  value,
  isEditable,
  onUpdate,
  textClassName,
  scale = 1,
}: EditableStringFieldDisplayProps) {
  const [isEditing, setIsEditing] = useState(false);
  const [editableValue, setEditableValue] = useState(value);
  const inputRef = useRef<HTMLInputElement | HTMLTextAreaElement>(null);
  const containerRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (isEditing && inputRef.current) {
      inputRef.current.focus();
    }
  }, [isEditing]);

  useEffect(() => {
    const handleClickOutside = (event: MouseEvent) => {
      if (
        containerRef.current &&
        !containerRef.current.contains(event.target as Node) &&
        isEditing
      ) {
        resetEditing();
      }
    };

    document.addEventListener("mousedown", handleClickOutside);
    return () => {
      document.removeEventListener("mousedown", handleClickOutside);
    };
  }, [isEditing]);

  const handleValueChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    setEditableValue(e.target.value);
  };

  const handleUpdate = async () => {
    await onUpdate(editableValue);
    setIsEditing(false);
  };

  const resetEditing = () => {
    setIsEditing(false);
    setEditableValue(value);
  };

  const handleKeyDown = (
    e: React.KeyboardEvent<HTMLInputElement | HTMLTextAreaElement>
  ) => {
    if (e.key === "Enter") {
      handleUpdate();
    }
  };

  const displayClassName = cn(
    textClassName,
    "text-3xl font-bold text-text-800",
    "user-text",
    isEditable && "cursor-pointer"
  );

  return (
    <div ref={containerRef} className={"flex items-center"}>
      <Input
        ref={inputRef as React.RefObject<HTMLInputElement>}
        type="text"
        value={editableValue}
        onChange={handleValueChange}
        onKeyDown={handleKeyDown}
        className={cn(
          textClassName,
          "text-3xl font-bold text-text-800",
          "user-text",
          isEditing ? "block" : "hidden"
        )}
        style={{ fontSize: `${scale}rem` }}
      />
      {!isEditing &&
        (isEditable ? (
          <button
            type="button"
            onClick={() => setIsEditing(true)}
            className={displayClassName}
            style={{ fontSize: `${scale}rem` }}
          >
            {value}
          </button>
        ) : (
          <span
            className={displayClassName}
            style={{ fontSize: `${scale}rem` }}
          >
            {value}
          </span>
        ))}
      {isEditing && isEditable ? (
        <>
          <div className={cn("flex", "flex-row")}>
            {/* TODO(@raunakab): migrate to opal Button once className/iconClassName is resolved */}
            <IconButton
              onClick={handleUpdate}
              internal
              className="ml-2"
              icon={SvgCheck}
            />
            {/* TODO(@raunakab): migrate to opal Button once className/iconClassName is resolved */}
            <IconButton
              onClick={resetEditing}
              internal
              className="ml-2"
              icon={SvgX}
            />
          </div>
        </>
      ) : (
        isEditable && (
          <button
            type="button"
            onClick={() => setIsEditing(true)}
            aria-label="Rename"
            className="group flex cursor-pointer"
            style={{ fontSize: `${scale}rem` }}
          >
            <SvgEdit className="visible ml-2" size={12 * scale} />
          </button>
        )
      )}
    </div>
  );
}
