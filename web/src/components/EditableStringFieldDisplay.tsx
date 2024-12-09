import { usePopup } from "@/components/admin/connectors/Popup";
import { CheckmarkIcon, EditIcon, XIcon } from "@/components/icons/icons";
import { Button } from "@/components/ui/button";
import { useEffect, useRef, useState } from "react";
import { Input } from "@/components/ui/input";
import { cn } from "@/lib/utils";

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
  const { popup, setPopup } = usePopup();
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

  return (
    <div ref={containerRef} className={"flex items-center"}>
      {popup}

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
      {!isEditing && (
        <span
          onClick={() => isEditable && setIsEditing(true)}
          className={cn(
            textClassName,
            "text-3xl font-bold text-text-800",
            "cursor-pointer user-text"
          )}
          style={{ fontSize: `${scale}rem` }}
        >
          {value}
        </span>
      )}
      {isEditing && isEditable ? (
        <>
          <div className={cn("flex", "flex-row")}>
            <Button
              onClick={handleUpdate}
              variant="ghost"
              size="sm"
              className="p-0 hover:bg-transparent ml-2"
            >
              <CheckmarkIcon className={`text-600`} size={12 * scale} />
            </Button>
            <Button
              onClick={resetEditing}
              variant="ghost"
              size="sm"
              className="p-0 hover:bg-transparent ml-2"
            >
              <XIcon className={`text-600`} size={12 * scale} />
            </Button>
          </div>
        </>
      ) : (
        <h1
          onClick={() => isEditable && setIsEditing(true)}
          className={`group flex ${isEditable ? "cursor-pointer" : ""} ${""}`}
          style={{ fontSize: `${scale}rem` }}
        >
          {isEditable && (
            <EditIcon className={`visible ml-2`} size={12 * scale} />
          )}
        </h1>
      )}
    </div>
  );
}
