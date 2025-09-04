import React, { useState, useEffect, useCallback } from "react";
import { InputPrompt } from "@/app/chat/interfaces";
import { Button } from "@/components/ui/button";
import { PlusIcon } from "@/components/icons/icons";
import { MoreVertical, XIcon } from "lucide-react";
import { Textarea } from "@/components/ui/textarea";
import Title from "@/components/ui/title";
import Text from "@/components/ui/text";
import { usePopup } from "@/components/admin/connectors/Popup";
import { BackButton } from "@/components/BackButton";
import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from "@/components/ui/tooltip";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { SourceChip } from "../components/input/ChatInputBar";

export default function InputPrompts() {
  const [inputPrompts, setInputPrompts] = useState<InputPrompt[]>([]);
  const [editingPromptId, setEditingPromptId] = useState<number | null>(null);
  const [newPrompt, setNewPrompt] = useState<Partial<InputPrompt>>({});
  const [isCreatingNew, setIsCreatingNew] = useState(false);
  const { popup, setPopup } = usePopup();

  useEffect(() => {
    fetchInputPrompts();
  }, []);

  const fetchInputPrompts = async () => {
    try {
      const response = await fetch("/api/input_prompt");
      if (response.ok) {
        const data = await response.json();
        setInputPrompts(data);
      } else {
        throw new Error("Failed to fetch prompt shortcuts");
      }
    } catch (error) {
      setPopup({ message: "Failed to fetch prompt shortcuts", type: "error" });
    }
  };

  const isPromptPublic = (prompt: InputPrompt): boolean => {
    return prompt.is_public;
  };

  // UPDATED: Remove partial merging to avoid overwriting fresh data
  const handleEdit = (promptId: number) => {
    setEditingPromptId(promptId);
  };

  const handleSave = async (
    promptId: number,
    updatedPrompt: string,
    updatedContent: string
  ) => {
    const promptToUpdate = inputPrompts.find((p) => p.id === promptId);
    if (!promptToUpdate || isPromptPublic(promptToUpdate)) return;

    try {
      const response = await fetch(`/api/input_prompt/${promptId}`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          prompt: updatedPrompt,
          content: updatedContent,
          active: true,
        }),
      });

      if (!response.ok) {
        throw new Error("Failed to update prompt");
      }

      // Update local state with new values
      setInputPrompts((prevPrompts) =>
        prevPrompts.map((prompt) =>
          prompt.id === promptId
            ? { ...prompt, prompt: updatedPrompt, content: updatedContent }
            : prompt
        )
      );

      setEditingPromptId(null);
      setPopup({ message: "Prompt updated successfully", type: "success" });
    } catch (error) {
      setPopup({ message: "Failed to update prompt", type: "error" });
    }
  };

  const handleDelete = async (id: number) => {
    const promptToDelete = inputPrompts.find((p) => p.id === id);
    if (!promptToDelete) return;

    try {
      let response;
      if (isPromptPublic(promptToDelete)) {
        // For public prompts, use the hide endpoint
        response = await fetch(`/api/input_prompt/${id}/hide`, {
          method: "POST",
        });
      } else {
        // For user-created prompts, use the delete endpoint
        response = await fetch(`/api/input_prompt/${id}`, {
          method: "DELETE",
        });
      }

      if (!response.ok) {
        throw new Error("Failed to delete/hide prompt");
      }

      setInputPrompts((prevPrompts) =>
        prevPrompts.filter((prompt) => prompt.id !== id)
      );
      setPopup({
        message: isPromptPublic(promptToDelete)
          ? "Prompt hidden successfully"
          : "Prompt deleted successfully",
        type: "success",
      });
    } catch (error) {
      setPopup({ message: "Failed to delete/hide prompt", type: "error" });
    }
  };

  const handleCreate = async () => {
    try {
      const response = await fetch("/api/input_prompt", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ ...newPrompt, is_public: false }),
      });

      if (!response.ok) {
        throw new Error("Failed to create prompt");
      }

      const createdPrompt = await response.json();
      setInputPrompts((prevPrompts) => [...prevPrompts, createdPrompt]);
      setNewPrompt({});
      setIsCreatingNew(false);
      setPopup({ message: "Prompt created successfully", type: "success" });
    } catch (error) {
      setPopup({ message: "Failed to create prompt", type: "error" });
    }
  };

  return (
    <div className="mx-auto max-w-4xl">
      <div className="absolute top-4 left-4">
        <BackButton />
      </div>
      {popup}
      <div className="flex justify-between items-start mb-6">
        <div className="flex flex-col gap-2">
          <Title>Prompt Shortcuts</Title>
          <Text>
            Manage and customize prompt shortcuts for your assistants. Use your
            prompt shortcuts by starting a new message with &quot;/&quot; in
            chat.
          </Text>
        </div>
      </div>

      {inputPrompts.map((prompt) => (
        <PromptCard
          key={prompt.id}
          prompt={prompt}
          onEdit={handleEdit}
          onSave={handleSave}
          onDelete={handleDelete}
          isEditing={editingPromptId === prompt.id}
        />
      ))}

      {isCreatingNew ? (
        <div className="space-y-2 border p-4 rounded-md mt-4">
          <Textarea
            placeholder="Prompt Shortcut (e.g. Summarize)"
            value={newPrompt.prompt || ""}
            onChange={(e) =>
              setNewPrompt({ ...newPrompt, prompt: e.target.value })
            }
            className="resize-none"
          />
          <Textarea
            placeholder="Actual Prompt (e.g. Summarize the uploaded document and highlight key points.)"
            value={newPrompt.content || ""}
            onChange={(e) =>
              setNewPrompt({ ...newPrompt, content: e.target.value })
            }
            className="resize-none"
          />
          <div className="flex space-x-2">
            <Button onClick={handleCreate}>Create</Button>
            <Button variant="ghost" onClick={() => setIsCreatingNew(false)}>
              Cancel
            </Button>
          </div>
        </div>
      ) : (
        <Button onClick={() => setIsCreatingNew(true)} className="w-full mt-4">
          <PlusIcon size={14} className="mr-2" />
          Create New Prompt
        </Button>
      )}
    </div>
  );
}

interface PromptCardProps {
  prompt: InputPrompt;
  onEdit: (id: number) => void;
  onSave: (id: number, prompt: string, content: string) => void;
  onDelete: (id: number) => void;
  isEditing: boolean;
}

const PromptCard: React.FC<PromptCardProps> = ({
  prompt,
  onEdit,
  onSave,
  onDelete,
  isEditing,
}) => {
  const [localPrompt, setLocalPrompt] = useState(prompt.prompt);
  const [localContent, setLocalContent] = useState(prompt.content);

  useEffect(() => {
    setLocalPrompt(prompt.prompt);
    setLocalContent(prompt.content);
  }, [prompt, isEditing]);

  const handleLocalEdit = useCallback(
    (field: "prompt" | "content", value: string) => {
      if (field === "prompt") {
        setLocalPrompt(value);
      } else {
        setLocalContent(value);
      }
    },
    []
  );

  const handleSaveLocal = useCallback(() => {
    onSave(prompt.id, localPrompt, localContent);
  }, [prompt.id, localPrompt, localContent, onSave]);

  const isPromptPublic = useCallback((p: InputPrompt): boolean => {
    return p.is_public;
  }, []);

  return (
    <div className="border dark:border-none dark:bg-[#333333] rounded-lg p-4 mb-4 relative">
      {isEditing ? (
        <>
          <div className="absolute top-2 right-2">
            <Button
              variant="ghost"
              size="sm"
              onClick={() => {
                onEdit(0);
              }}
            >
              <XIcon size={14} />
            </Button>
          </div>
          <div className="flex">
            <div className="flex-grow mr-4">
              <Textarea
                value={localPrompt}
                onChange={(e) => handleLocalEdit("prompt", e.target.value)}
                className="mb-2 resize-none"
                placeholder="Prompt"
              />
              <Textarea
                value={localContent}
                onChange={(e) => handleLocalEdit("content", e.target.value)}
                className="resize-vertical min-h-[100px]"
                placeholder="Content"
              />
            </div>
            <div className="flex items-end">
              <Button onClick={handleSaveLocal}>
                {prompt.id ? "Save" : "Create"}
              </Button>
            </div>
          </div>
        </>
      ) : (
        <>
          <TooltipProvider>
            <Tooltip>
              <TooltipTrigger asChild>
                <div className="mb-2  flex gap-x-2 ">
                  <p className="font-semibold">{prompt.prompt}</p>
                  {isPromptPublic(prompt) && <SourceChip title="Built-in" />}
                </div>
              </TooltipTrigger>
              {isPromptPublic(prompt) && (
                <TooltipContent>
                  <p>This is a built-in prompt and cannot be edited</p>
                </TooltipContent>
              )}
            </Tooltip>
          </TooltipProvider>
          <div className="whitespace-pre-wrap">{prompt.content}</div>
          <div className="absolute top-2 right-2">
            <DropdownMenu>
              <DropdownMenuTrigger className="hover:bg-transparent" asChild>
                <Button
                  className="!hover:bg-transparent"
                  variant="ghost"
                  size="sm"
                >
                  <MoreVertical size={14} />
                </Button>
              </DropdownMenuTrigger>
              <DropdownMenuContent>
                {!isPromptPublic(prompt) && (
                  <DropdownMenuItem onClick={() => onEdit(prompt.id)}>
                    Edit
                  </DropdownMenuItem>
                )}
                <DropdownMenuItem onClick={() => onDelete(prompt.id)}>
                  Delete
                </DropdownMenuItem>
              </DropdownMenuContent>
            </DropdownMenu>
          </div>
        </>
      )}
    </div>
  );
};
