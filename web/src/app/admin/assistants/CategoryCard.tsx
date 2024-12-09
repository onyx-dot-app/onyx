import { useState } from "react";
import {
  Card,
  CardHeader,
  CardTitle,
  CardContent,
  CardFooter,
} from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { Button } from "@/components/ui/button";
import { PersonaCategory } from "./interfaces";
import { PopupSpec } from "@/components/admin/connectors/Popup";

interface CategoryCardProps {
  category: PersonaCategory;
  onUpdate: (id: number, name: string, description: string) => void;
  onDelete: (id: number) => void;
  refreshCategories: () => Promise<void>;
  setPopup: (popup: PopupSpec) => void;
}

export function CategoryCard({
  category,
  onUpdate,
  onDelete,
  refreshCategories,
}: CategoryCardProps) {
  const [isEditing, setIsEditing] = useState(false);
  const [name, setName] = useState(category.name);
  const [description, setDescription] = useState(category.description);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    await onUpdate(category.id, name, description);
    await refreshCategories();
    setIsEditing(false);
  };
  const handleEdit = (e: React.MouseEvent) => {
    e.preventDefault();
    setIsEditing(true);
  };

  return (
    <Card key={category.id} className="w-full max-w-sm">
      <CardHeader className="w-full">
        <CardTitle className="text-2xl font-bold">
          {isEditing ? (
            <Input
              value={name}
              onChange={(e) => setName(e.target.value)}
              className="text-lg font-semibold"
            />
          ) : (
            <span>{category.name}</span>
          )}
        </CardTitle>
      </CardHeader>
      <CardContent className="w-full">
        {isEditing ? (
          <Textarea
            value={description}
            onChange={(e) => setDescription(e.target.value)}
            className="resize-none w-full"
          />
        ) : (
          <p className="text-sm text-gray-600">{category.description}</p>
        )}
      </CardContent>
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
                await onDelete(category.id);
                await refreshCategories();
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
