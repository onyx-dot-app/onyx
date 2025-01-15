import React, { useState, useEffect } from "react";
import { InputPrompt } from "@/app/chat/interfaces";
import { Button } from "@/components/ui/button";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { TrashIcon, PlusIcon } from "@/components/icons/icons";
import { FiCheck, FiX } from "react-icons/fi";
import { Textarea } from "@/components/ui/textarea";
import Title from "@/components/ui/title";
import Text from "@/components/ui/text";
import { usePopup } from "@/components/admin/connectors/Popup";
import { BackButton } from "@/components/BackButton";

export default function InputPrompts() {
  const [inputPrompts, setInputPrompts] = useState<InputPrompt[]>([]);
  const [editingPromptId, setEditingPromptId] = useState<number | null>(null);
  const [newPrompt, setNewPrompt] = useState<Partial<InputPrompt>>({});
  const [isCreatingNew, setIsCreatingNew] = useState(false);
  const [isCollapsed, setIsCollapsed] = useState(false);
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
        console.log("INPUT PROMPTS");
        console.log(data);
      } else {
        console.log("INPUT PROMPTS ERROR");
        throw new Error("Failed to fetch prompt shortcuts");
      }
    } catch (error) {
      setPopup({ message: "Failed to fetch prompt shortcuts", type: "error" });
    }
  };

  const isPromptPublic = (prompt: InputPrompt): boolean => {
    return prompt.is_public;
  };

  const handleEdit = (
    promptId: number,
    updatedFields: Partial<InputPrompt>
  ) => {
    setInputPrompts((prevPrompts) =>
      prevPrompts.map((prompt) =>
        prompt.id === promptId && !isPromptPublic(prompt)
          ? { ...prompt, ...updatedFields }
          : prompt
      )
    );
    setEditingPromptId(promptId);
  };

  const handleSave = async (promptId: number) => {
    const promptToUpdate = inputPrompts.find((p) => p.id === promptId);
    if (!promptToUpdate || isPromptPublic(promptToUpdate)) return;

    try {
      const response = await fetch(`/api/input_prompt/${promptId}`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(promptToUpdate),
      });

      if (!response.ok) {
        throw new Error("Failed to update prompt");
      }

      setEditingPromptId(null);
      setPopup({ message: "Prompt updated successfully", type: "success" });
    } catch (error) {
      setPopup({ message: "Failed to update prompt", type: "error" });
    }
  };

  const handleDelete = async (id: number) => {
    const promptToDelete = inputPrompts.find((p) => p.id === id);
    if (!promptToDelete || isPromptPublic(promptToDelete)) return;

    try {
      const response = await fetch(`/api/input_prompt/${id}`, {
        method: "DELETE",
      });

      if (!response.ok) {
        throw new Error("Failed to delete prompt");
      }

      setInputPrompts((prevPrompts) =>
        prevPrompts.filter((prompt) => prompt.id !== id)
      );
      setPopup({ message: "Prompt deleted successfully", type: "success" });
    } catch (error) {
      setPopup({ message: "Failed to delete prompt", type: "error" });
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
          <Text>Manage and customize prompt shortcuts for your assistants</Text>
        </div>
      </div>

      <Table>
        <TableHeader>
          <TableRow>
            <TableHead className="w-1/3">Prompt</TableHead>
            <TableHead className="w-1/2">Content</TableHead>
            <TableHead className="w-1/6">Actions</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {inputPrompts.map((prompt) => (
            <TableRow className="fltart" key={prompt.id}>
              <TableCell className="">
                <Textarea
                  value={prompt.prompt}
                  onChange={(e) =>
                    handleEdit(prompt.id, { prompt: e.target.value })
                  }
                  className="min-h-[80px] mb-auto resize-none"
                  disabled={isPromptPublic(prompt)}
                />
              </TableCell>
              <TableCell>
                <Textarea
                  value={prompt.content}
                  onChange={(e) =>
                    handleEdit(prompt.id, { content: e.target.value })
                  }
                  className="min-h-[80px]"
                  disabled={isPromptPublic(prompt)}
                />
              </TableCell>
              <TableCell>
                <div className="flex space-x-2">
                  {!isPromptPublic(prompt) && (
                    <>
                      {editingPromptId === prompt.id ? (
                        <>
                          <Button
                            variant="ghost"
                            size="sm"
                            onClick={() => handleSave(prompt.id)}
                          >
                            <FiCheck size={14} />
                          </Button>
                          <Button
                            variant="ghost"
                            size="sm"
                            onClick={() => {
                              setEditingPromptId(null);
                              fetchInputPrompts(); // Revert changes
                            }}
                          >
                            <FiX size={14} />
                          </Button>
                        </>
                      ) : (
                        <Button
                          variant="ghost"
                          size="sm"
                          onClick={() => handleDelete(prompt.id)}
                        >
                          <TrashIcon size={14} />
                        </Button>
                      )}
                    </>
                  )}
                </div>
              </TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>

      {isCreatingNew ? (
        <div className="space-y-2 border p-4 rounded-md mt-4">
          <Textarea
            placeholder="New prompt"
            value={newPrompt.prompt || ""}
            onChange={(e) =>
              setNewPrompt({ ...newPrompt, prompt: e.target.value })
            }
            className="min-h-[40px] resize-none"
          />
          <Textarea
            placeholder="New content"
            value={newPrompt.content || ""}
            onChange={(e) =>
              setNewPrompt({ ...newPrompt, content: e.target.value })
            }
            className="min-h-[80px]"
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
