import { useState } from "react";
import { Card, CardHeader, CardTitle, CardFooter } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Button } from "@/components/ui/button";
import { PersonaLabel } from "./interfaces";
import { PopupSpec } from "@/components/admin/connectors/Popup";

interface LabelCardProps {
  label: PersonaLabel;
  onUpdate: (id: number, name: string) => void;
  onDelete: (id: number) => void;
  refreshLabels: () => Promise<void>;
  setPopup: (popup: PopupSpec) => void;
}

export function LabelCard({
  label,
  onUpdate,
  onDelete,
  refreshLabels,
}: LabelCardProps) {
  const [isEditing, setIsEditing] = useState(false);
  const [name, setName] = useState(label.name);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    await onUpdate(label.id, name);
    await refreshLabels();
    setIsEditing(false);
  };
  const handleEdit = (e: React.MouseEvent) => {
    e.preventDefault();
    setIsEditing(true);
  };

  return (
    <Card key={label.id} className="w-full max-w-sm">
      <CardHeader className="w-full">
        <CardTitle className="text-2xl font-bold">
          {isEditing ? (
            <Input
              value={name}
              onChange={(e) => setName(e.target.value)}
              className="text-lg font-semibold"
            />
          ) : (
            <span>{label.name}</span>
          )}
        </CardTitle>
      </CardHeader>
      <CardFooter className="flex justify-end space-x-2">
        {isEditing ? (
          <>
            <Button type="button" variant="outline" onClick={handleSubmit}>
              Save
            </Button>
            <Button
              type="button"
              onClick={() => setIsEditing(false)}
              variant="default"
            >
              Cancel
            </Button>
          </>
        ) : (
          <>
            <Button type="button" onClick={handleEdit} variant="outline">
              Edit
            </Button>
            <Button
              type="button"
              variant="destructive"
              onClick={async (e) => {
                e.preventDefault();
                await onDelete(label.id);
                await refreshLabels();
              }}
            >
              Delete
            </Button>
          </>
        )}
      </CardFooter>
    </Card>
  );
}
