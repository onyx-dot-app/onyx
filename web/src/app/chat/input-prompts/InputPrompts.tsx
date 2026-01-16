"use client";

import { useState, useCallback, useEffect } from "react";
import { InputPrompt } from "@/app/chat/interfaces";
import Button from "@/refresh-components/buttons/Button";
import Text from "@/refresh-components/texts/Text";
import { usePopup } from "@/components/admin/connectors/Popup";
import BackButton from "@/refresh-components/buttons/BackButton";
import SimpleTooltip from "@/refresh-components/SimpleTooltip";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { SourceChip } from "@/app/chat/components/input/ChatInputBar";
import IconButton from "@/refresh-components/buttons/IconButton";
import InputTextArea from "@/refresh-components/inputs/InputTextArea";
import { SvgMoreHorizontal, SvgPlus, SvgX } from "@opal/icons";
import usePromptShortcuts from "@/hooks/usePromptShortcuts";

export default function InputPrompts() {
  const {
    promptShortcuts: inputPrompts,
    refresh,
    error,
  } = usePromptShortcuts();
  const [editingPromptId, setEditingPromptId] = useState<number | null>(null);
  const [newPrompt, setNewPrompt] = useState<Partial<InputPrompt>>({});
  const [isCreatingNew, setIsCreatingNew] = useState(false);
  const { popup, setPopup } = usePopup();

  useEffect(() => {
    if (error) {
      setPopup({ message: "Failed to fetch prompt shortcuts", type: "error" });
    }
  }, [error, setPopup]);

  function isPromptPublic(prompt: InputPrompt): boolean {
    return prompt.is_public;
  }

  // UPDATED: Remove partial merging to avoid overwriting fresh data
  function handleEdit(promptId: number) {
    setEditingPromptId(promptId);
  }

  async function handleSave(
    promptId: number,
    updatedPrompt: string,
    updatedContent: string
  ) {
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

      await refresh();
      setEditingPromptId(null);
      setPopup({ message: "Prompt updated successfully", type: "success" });
    } catch (error) {
      setPopup({ message: "Failed to update prompt", type: "error" });
    }
  }

  async function handleDelete(id: number) {
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

      await refresh();
      setPopup({
        message: isPromptPublic(promptToDelete)
          ? "Prompt hidden successfully"
          : "Prompt deleted successfully",
        type: "success",
      });
    } catch (error) {
      setPopup({ message: "Failed to delete/hide prompt", type: "error" });
    }
  }

  async function handleCreate() {
    try {
      const response = await fetch("/api/input_prompt", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ ...newPrompt, is_public: false }),
      });

      if (!response.ok) {
        throw new Error("Failed to create prompt");
      }

      await refresh();
      setNewPrompt({});
      setIsCreatingNew(false);
      setPopup({ message: "Prompt created successfully", type: "success" });
    } catch (error) {
      setPopup({ message: "Failed to create prompt", type: "error" });
    }
  }

  return (
    <div className="mx-auto max-w-4xl py-8">
      <div className="absolute top-4 left-4">
        <BackButton />
      </div>
      {popup}
      <div className="flex justify-between items-start mb-6">
        <div className="flex flex-col gap-2">
          <Text headingH3>Prompt Shortcuts</Text>
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
          <InputTextArea
            placeholder="Prompt Shortcut (e.g. Summarize)"
            value={newPrompt.prompt || ""}
            onChange={(event) =>
              setNewPrompt({ ...newPrompt, prompt: event.target.value })
            }
            className="resize-none"
          />
          <InputTextArea
            placeholder="Actual Prompt (e.g. Summarize the uploaded document and highlight key points.)"
            value={newPrompt.content || ""}
            onChange={(event) =>
              setNewPrompt({ ...newPrompt, content: event.target.value })
            }
            className="resize-none"
          />
          <div className="flex space-x-2">
            <Button onClick={handleCreate}>Create</Button>
            <Button internal onClick={() => setIsCreatingNew(false)}>
              Cancel
            </Button>
          </div>
        </div>
      ) : (
        <Button
          onClick={() => setIsCreatingNew(true)}
          className="w-full mt-4"
          leftIcon={SvgPlus}
        >
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

function PromptCard({
  prompt,
  onEdit,
  onSave,
  onDelete,
  isEditing,
}: PromptCardProps) {
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
            <IconButton
              internal
              onClick={() => {
                onEdit(0);
              }}
              icon={SvgX}
            />
          </div>
          <div className="flex">
            <div className="flex-grow mr-4">
              <InputTextArea
                value={localPrompt}
                onChange={(event) =>
                  handleLocalEdit("prompt", event.target.value)
                }
                className="mb-2 resize-none"
                placeholder="Prompt"
              />
              <InputTextArea
                value={localContent}
                onChange={(event) =>
                  handleLocalEdit("content", event.target.value)
                }
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
          <SimpleTooltip
            tooltip="This is a built-in prompt and cannot be edited"
            disabled={!isPromptPublic(prompt)}
          >
            <div className="mb-2  flex gap-x-2 ">
              <p className="font-semibold">{prompt.prompt}</p>
              {isPromptPublic(prompt) && <SourceChip title="Built-in" />}
            </div>
          </SimpleTooltip>
          <div className="whitespace-pre-wrap">{prompt.content}</div>
          <div className="absolute top-2 right-2">
            <DropdownMenu>
              <DropdownMenuTrigger className="hover:bg-transparent" asChild>
                <IconButton internal icon={SvgMoreHorizontal} />
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
}
