import { usePopup } from "@/components/admin/connectors/Popup";
import { CheckmarkIcon, XIcon } from "@/components/icons/icons";
import { Button } from "@/components/ui/button";
import { useEffect, useRef, useState } from "react";
import { Textarea } from "@/components/ui/textarea";
import { cn } from "@/lib/utils";

interface EditableTextAreaDisplayProps {
  value: string;
  isEditable: boolean;
  onUpdate: (newValue: string) => Promise<void>;
  textClassName?: string;
  scale?: number;
}

export function EditableTextAreaDisplay({
  value,
  isEditable,
  onUpdate,
  textClassName,
  scale = 1,
}: EditableTextAreaDisplayProps) {
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

  return (
    <div ref={containerRef} className={"flex items-center"}>
      <Textarea
        ref={inputRef as React.RefObject<HTMLTextAreaElement>}
        value={editableValue}
        onChange={(e) => setEditableValue(e.target.value)}
        onKeyDown={handleKeyDown}
        className={cn(
          textClassName,
          "bg-white",
          isEditable && !isEditing && "cursor-pointer"
        )}
        style={{ fontSize: `${scale}rem` }}
        readOnly={!isEditing}
        onClick={() => isEditable && !isEditing && setIsEditing(true)}
      />
      {isEditing && isEditable ? (
        <div className={cn("flex", "flex-col gap-1")}>
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
      ) : null}
    </div>
  );
}
