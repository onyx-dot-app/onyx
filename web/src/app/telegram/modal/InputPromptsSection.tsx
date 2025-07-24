import i18n from "@/i18n/init";
import k from "./../../../i18n/keys";
import React, { useState, useEffect } from "react";
import { InputPrompt } from "@/app/chat/interfaces";
import { PopupSpec } from "@/components/admin/connectors/Popup";
import { Button } from "@/components/ui/button";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import {
  EditIcon,
  TrashIcon,
  PlusIcon,
  ChevronDownIcon,
  ChevronUpIcon,
} from "@/components/icons/icons";
import { FiCheck, FiX } from "react-icons/fi";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { Switch } from "@/components/ui/switch";

interface InputPromptsSectionProps {
  inputPrompts: InputPrompt[];
  refreshInputPrompts: () => void;
  setPopup: (popup: PopupSpec | null) => void;
}

export function InputPromptsSection({
  inputPrompts,
  refreshInputPrompts,
  setPopup,
}: InputPromptsSectionProps) {
  const [editingPromptId, setEditingPromptId] = useState<number | null>(null);
  const [editedPrompt, setEditedPrompt] = useState<InputPrompt | null>(null);
  const [newPrompt, setNewPrompt] = useState<Partial<InputPrompt>>({});
  const [isCreatingNew, setIsCreatingNew] = useState(false);
  const [isCollapsed, setIsCollapsed] = useState(false);
  const [orderedPrompts, setOrderedPrompts] = useState<InputPrompt[]>([]);

  useEffect(() => {
    const sortedPrompts = [...inputPrompts].sort((a, b) => {
      if (a.active === b.active) return 0;
      return a.active ? -1 : 1;
    });
    setOrderedPrompts(sortedPrompts);
  }, [inputPrompts]);

  const handleEdit = (prompt: InputPrompt) => {
    setEditingPromptId(prompt.id);
    setEditedPrompt({ ...prompt });
  };

  const handleSave = async (prompt: InputPrompt) => {
    try {
      const response = await fetch(`/api/input_prompt/${prompt.id}`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(prompt),
      });

      if (!response.ok) {
        throw new Error("Не удалось обновить приглашение");
      }

      setEditingPromptId(null);
      setEditedPrompt(null);
      refreshInputPrompts();
      setPopup({ message: "Подсказка успешно обновлена", type: "success" });
    } catch (error) {
      setPopup({ message: "Не удалось обновить приглашение", type: "error" });
    }
  };

  const handleDelete = async (id: number) => {
    try {
      const response = await fetch(`/api/input_prompt/${id}`, {
        method: "DELETE",
      });

      if (!response.ok) {
        throw new Error("Не удалось удалить запрос");
      }

      refreshInputPrompts();
      setPopup({ message: "Подсказка успешно удалена", type: "success" });
    } catch (error) {
      setPopup({ message: "Не удалось удалить запрос", type: "error" });
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
        throw new Error("Не удалось создать приглашение");
      }

      setNewPrompt({});
      setIsCreatingNew(false);
      refreshInputPrompts();
      setPopup({ message: "Запрос создан успешно", type: "success" });
    } catch (error) {
      setPopup({ message: "Не удалось создать приглашение", type: "error" });
    }
  };

  const handleToggleActive = async (prompt: InputPrompt) => {
    try {
      const response = await fetch(`/api/input_prompt/${prompt.id}`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ ...prompt, active: !prompt.active }),
      });

      if (!response.ok) {
        throw new Error("Не удалось обновить приглашение");
      }

      refreshInputPrompts();
      setPopup({ message: "Подсказка успешно обновлена", type: "success" });
    } catch (error) {
      setPopup({ message: "Не удалось обновить приглашение", type: "error" });
    }
  };

  return (
    <div className="space-y-4">
      <div className="flex justify-between items-center">
        <h3 className="text-lg font-semibold">{i18n.t(k.INPUT_PROMPTS)}</h3>
        <Button
          variant="ghost"
          size="sm"
          onClick={() => setIsCollapsed(!isCollapsed)}
        >
          {isCollapsed ? (
            <ChevronDownIcon size={16} />
          ) : (
            <ChevronUpIcon size={16} />
          )}
        </Button>
      </div>

      {!isCollapsed && (
        <>
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead className="w-1/4">{i18n.t(k.PROMPT1)}</TableHead>
                <TableHead className="w-1/2">{i18n.t(k.CONTENT1)}</TableHead>
                <TableHead className="w-1/12">{i18n.t(k.ACTIVE)}</TableHead>
                <TableHead className="w-1/6">{i18n.t(k.ACTIONS)}</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {orderedPrompts.map((prompt) => (
                <TableRow key={prompt.id}>
                  <TableCell>
                    {editingPromptId === prompt.id ? (
                      <Input
                        value={editedPrompt?.prompt || ""}
                        onChange={(e) =>
                          setEditedPrompt({
                            ...editedPrompt!,
                            prompt: e.target.value,
                          })
                        }
                      />
                    ) : (
                      prompt.prompt
                    )}
                  </TableCell>
                  <TableCell>
                    {editingPromptId === prompt.id ? (
                      <Textarea
                        value={editedPrompt?.content || ""}
                        onChange={(e) =>
                          setEditedPrompt({
                            ...editedPrompt!,
                            content: e.target.value,
                          })
                        }
                        className="min-h-[80px]"
                      />
                    ) : (
                      <div className="max-h-[80px] overflow-y-auto">
                        {prompt.content}
                      </div>
                    )}
                  </TableCell>
                  <TableCell>
                    <Switch
                      checked={prompt.active}
                      onCheckedChange={() => handleToggleActive(prompt)}
                    />
                  </TableCell>
                  <TableCell>
                    <div className="flex space-x-2">
                      {editingPromptId === prompt.id ? (
                        <>
                          <Button
                            variant="ghost"
                            size="sm"
                            onClick={() => handleSave(editedPrompt!)}
                          >
                            <FiCheck size={14} />
                          </Button>
                          <Button
                            variant="ghost"
                            size="sm"
                            onClick={() => {
                              setEditingPromptId(null);
                              setEditedPrompt(null);
                            }}
                          >
                            <FiX size={14} />
                          </Button>
                        </>
                      ) : (
                        <>
                          <Button
                            variant="ghost"
                            size="sm"
                            onClick={() => handleEdit(prompt)}
                          >
                            <EditIcon size={14} />
                          </Button>
                          <Button
                            variant="ghost"
                            size="sm"
                            onClick={() => handleDelete(prompt.id)}
                          >
                            <TrashIcon size={14} />
                          </Button>
                        </>
                      )}
                    </div>
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>

          {isCreatingNew ? (
            <div className="space-y-2 border p-4 rounded-md">
              <Input
                placeholder="Новый промпт"
                value={newPrompt.prompt || ""}
                onChange={(e) =>
                  setNewPrompt({ ...newPrompt, prompt: e.target.value })
                }
              />

              <Textarea
                placeholder="Новый контент"
                value={newPrompt.content || ""}
                onChange={(e) =>
                  setNewPrompt({ ...newPrompt, content: e.target.value })
                }
                className="min-h-[80px]"
              />

              <div className="flex space-x-2">
                <Button onClick={handleCreate}>{i18n.t(k.CREATE1)}</Button>
                <Button variant="ghost" onClick={() => setIsCreatingNew(false)}>
                  {i18n.t(k.CANCEL)}
                </Button>
              </div>
            </div>
          ) : (
            <Button onClick={() => setIsCreatingNew(true)} className="w-full">
              <PlusIcon size={14} className="mr-2" />
              {i18n.t(k.CREATE_NEW_PROMPT)}
            </Button>
          )}
        </>
      )}
    </div>
  );
}
