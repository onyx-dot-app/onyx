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

  const handleSubmit = async () => {
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

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      handleSubmit();
    }
  };

  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogContent className="w-[95%] max-w-2xl">
        <DialogHeader>
          <FolderPlus size={26} className="mb-2" />
          <DialogTitle>Create New Project</DialogTitle>
          <DialogDescription>
            Projects help keep your chats organized. Add files and instructions
            to easily start new conversations on the same topic.
          </DialogDescription>
        </DialogHeader>
        <div className="bg-background-100 dark:bg-transparent -mx-6 px-6 py-4 space-y-2">
          <Label htmlFor="project-name">Project Name</Label>
          <Input
            id="project-name"
            autoFocus
            autoComplete="off"
            placeholder="What are you working on?"
            value={projectName}
            onChange={(e) => setProjectName(e.target.value)}
            onKeyDown={handleKeyDown}
            removeFocusRing
          />
        </div>
        <div className="flex justify-end gap-3 pt-2 w-full">
          <Button
            type="button"
            variant="outline"
            onClick={() => setOpen(false)}
            disabled={isSubmitting}
          >
            Cancel
          </Button>
          <Button
            type="button"
            onClick={handleSubmit}
            disabled={isSubmitting || projectName.trim().length === 0}
          >
            Create Project
          </Button>
        </div>
      </DialogContent>
    </Dialog>
  );
}
