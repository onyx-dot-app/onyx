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
  onSubmit: (name: string) => void;
  placeholder?: string;
  trigger: React.ReactNode;
  open: boolean;
  setOpen: (open: boolean) => void;
  hideLabel?: boolean;
  type?: string;
}

export default function CreateEntityModal({
  title,
  entityName,
  onSubmit,
  trigger,
  placeholder,
  open,
  setOpen,
  hideLabel = false,
  type = "text",
}: CreateEntityModalProps) {
  const [name, setName] = useState("");

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    if (name.trim()) {
      onSubmit(name.trim());
    }
  };

  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogTrigger asChild>{trigger}</DialogTrigger>
      <DialogContent className="max-w-[95%] sm:max-w-[425px]">
        <DialogHeader>
          <DialogTitle>{title}</DialogTitle>
        </DialogHeader>
        <form
          onSubmit={handleSubmit}
          className="flex flex-col justify-stretch space-y-2 w-full"
        >
          <div className="space-y-2 w-full">
            {!hideLabel && <Label htmlFor="name">{entityName} Name</Label>}
            <Input
              autoComplete="off"
              id="name"
              type={type}
              value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder={
                placeholder || `Enter ${entityName.toLowerCase()} name`
              }
              required
              className="w-full  focus-visible:border focus-visible:border-neutral-200 focus-visible:ring-0 !focus:ring-offset-0 !focus:ring-0 !focus:border-0 !focus:ring-transparent !focus:outline-none"
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
