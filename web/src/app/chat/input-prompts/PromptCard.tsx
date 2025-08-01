import { SourceChip } from "../components/input/ChatInputBar";

import { useEffect } from "react";
import { useState } from "react";
import { InputPrompt } from "../interfaces";
import { Button } from "@/components/ui/button";
import { XIcon } from "@/components/icons/icons";
import { Textarea } from "@/components/ui/textarea";
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
import { MoreVertical } from "lucide-react";

export const PromptCard = ({
  prompt,
  editingPromptId,
  setEditingPromptId,
  handleSave,
  handleDelete,
  isPromptPublic,
  handleEdit,
  fetchInputPrompts,
}: {
  prompt: InputPrompt;
  editingPromptId: number | null;
  setEditingPromptId: (id: number | null) => void;
  handleSave: (id: number, prompt: string, content: string) => void;
  handleDelete: (id: number) => void;
  isPromptPublic: (prompt: InputPrompt) => boolean;
  handleEdit: (id: number) => void;
  fetchInputPrompts: () => void;
}) => {
  const isEditing = editingPromptId === prompt.id;
  const [localPrompt, setLocalPrompt] = useState(prompt.prompt);
  const [localContent, setLocalContent] = useState(prompt.content);

  // Sync local edits with any prompt changes from outside
  useEffect(() => {
    setLocalPrompt(prompt.prompt);
    setLocalContent(prompt.content);
  }, [prompt, isEditing]);

  const handleLocalEdit = (field: "prompt" | "content", value: string) => {
    if (field === "prompt") {
      setLocalPrompt(value);
    } else {
      setLocalContent(value);
    }
  };

  const handleSaveLocal = () => {
    handleSave(prompt.id, localPrompt, localContent);
  };

  return (
    <div className="border dark:border-none dark:bg-[#333333] rounded-lg p-4 mb-4 relative">
      {isEditing ? (
        <>
          <div className="absolute top-2 right-2">
            <Button
              variant="ghost"
              size="sm"
              onClick={() => {
                setEditingPromptId(null);
                fetchInputPrompts(); // Revert changes from server
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
                  <DropdownMenuItem onClick={() => handleEdit(prompt.id)}>
                    Edit
                  </DropdownMenuItem>
                )}
                <DropdownMenuItem onClick={() => handleDelete(prompt.id)}>
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
