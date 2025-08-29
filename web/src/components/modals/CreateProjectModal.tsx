"use client";

import { useState } from "react";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { FolderPlus } from "lucide-react";

interface CreateProjectModalProps {
  open: boolean;
  setOpen: (open: boolean) => void;
  onCreate?: (name: string) => void | Promise<void>;
}

export default function CreateProjectModal({
  open,
  setOpen,
  onCreate,
}: CreateProjectModalProps) {
  const [projectName, setProjectName] = useState("");
  const [isSubmitting, setIsSubmitting] = useState(false);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    const name = projectName.trim();
    if (!name) return;
    try {
      setIsSubmitting(true);
      await onCreate?.(name);
      setOpen(false);
      setProjectName("");
    } finally {
      setIsSubmitting(false);
    }
  };

  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogContent className="w-[95%] max-w-2xl">
        <DialogHeader>
          <FolderPlus size={26} className="mb-2" />
          <DialogTitle>Create New Project</DialogTitle>
          <DialogDescription>
            Use projects to organize your files and chats in one place, and add
            custom instructions for ongoing work.
          </DialogDescription>
        </DialogHeader>
        <form onSubmit={handleSubmit} className="flex flex-col gap-3 w-full">
          <div className="space-y-2 w-full">
            <Label htmlFor="project-name">Project Name</Label>
            <Input
              id="project-name"
              autoFocus
              autoComplete="off"
              placeholder="What are you working on?"
              value={projectName}
              onChange={(e) => setProjectName(e.target.value)}
              className="w-full focus-visible:border focus-visible:border-neutral-200 focus-visible:ring-0 !focus:ring-offset-0 !focus:ring-0 !focus:border-0 !focus:ring-transparent !focus:outline-none"
            />
          </div>
          <div className="flex justify-end gap-3 pt-2">
            <Button
              type="button"
              variant="outline"
              onClick={() => setOpen(false)}
              disabled={isSubmitting}
            >
              Cancel
            </Button>
            <Button
              type="submit"
              disabled={isSubmitting || projectName.trim().length === 0}
            >
              Create Project
            </Button>
          </div>
        </form>
      </DialogContent>
    </Dialog>
  );
}
