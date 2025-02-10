import React, { useState } from "react";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from "@/components/ui/dialog";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";

interface CreateEntityModalProps {
  title: string;
  entityName: string;
  onSubmit: (name: string, description: string) => void;
  trigger: React.ReactNode;
  open: boolean;
  setOpen: (open: boolean) => void;
}

export default function CreateEntityModal({
  title,
  entityName,
  onSubmit,
  trigger,
  open,
  setOpen,
}: CreateEntityModalProps) {
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    if (name.trim()) {
      onSubmit(name.trim(), description.trim());
    }
  };

  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogTrigger asChild>{trigger}</DialogTrigger>
      <DialogContent className="sm:max-w-[425px]">
        <DialogHeader>
          <DialogTitle>{title}</DialogTitle>
        </DialogHeader>
        <form
          onSubmit={handleSubmit}
          className="flex flex-col justify-stretch space-y-2 w-full"
        >
          <div className="space-y-2 w-full">
            <Label htmlFor="name">{entityName} Name</Label>
            <Input
              id="name"
              value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder={`Enter ${entityName.toLowerCase()} name`}
              required
              className="w-full"
            />
          </div>
          <div className="space-y-2 w-full">
            <Label htmlFor="description">Description</Label>
            <Input
              type="textarea"
              id="description"
              value={description}
              onChange={(e) => setDescription(e.target.value)}
              placeholder={`Enter ${entityName.toLowerCase()} description`}
              className="w-full"
            />
          </div>
          <Button type="submit" className="w-full">
            Create {entityName}
          </Button>
        </form>
      </DialogContent>
    </Dialog>
  );
}
