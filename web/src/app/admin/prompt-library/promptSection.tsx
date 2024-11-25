"use client";

import { usePopup } from "@/components/admin/connectors/Popup";
import { ThreeDotsLoader } from "@/components/Loading";
import { ErrorCallout } from "@/components/ErrorCallout";
import { Button } from "@/components/ui/button";
import { Separator } from "@/components/ui/separator";
import Text from "@/components/ui/text";
import { useState } from "react";
import AddPromptModal from "./modals/AddPromptModal";
import EditPromptModal from "./modals/EditPromptModal";
import { PromptLibraryTable } from "./promptLibrary";
import { CreateInputPromptRequest, InputPrompt } from "./interfaces";

export const PromptSection = ({
  promptLibrary,
  isLoading,
  error,
  refreshPrompts,
  centering = false,
  isPublic,
}: {
  promptLibrary: InputPrompt[];
  isLoading: boolean;
  error: any;
  refreshPrompts: () => void;
  centering?: boolean;
  isPublic: boolean;
}) => {
  const { popup, setPopup } = usePopup();
  const [newPrompt, setNewPrompt] = useState(false);
  const [newPromptId, setNewPromptId] = useState<number | null>(null);

  const createInputPrompt = async (
    promptData: CreateInputPromptRequest
  ): Promise<InputPrompt> => {
    const response = await fetch("/api/input_prompt", {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
      },
      body: JSON.stringify({ ...promptData, is_public: isPublic }),
    });

    if (!response.ok) {
      setPopup({ message: "Failed to create input prompt", type: "error" });
    }

    refreshPrompts();
    return response.json();
  };

  const editInputPrompt = async (
    promptId: number,
    values: CreateInputPromptRequest
  ) => {
    try {
      const response = await fetch(`/api/input_prompt/${promptId}`, {
        method: "PATCH",
        headers: {
          "Content-Type": "application/json",
        },
        body: JSON.stringify(values),
      });

      if (!response.ok) {
        setPopup({ message: "Failed to update prompt!", type: "error" });
      }

      setNewPromptId(null);
      refreshPrompts();
    } catch (err) {
      setPopup({ message: `Failed to update prompt: ${err}`, type: "error" });
    }
  };

  if (isLoading) {
    return <ThreeDotsLoader />;
  }

  if (error || !promptLibrary) {
    return (
      <ErrorCallout
        errorTitle="Error loading standard answers"
        errorMsg={error?.info?.message || error?.message?.info?.detail}
      />
    );
  }

  const handleEdit = (promptId: number) => {
    setNewPromptId(promptId);
  };

  return (
    <div
      className={`w-full ${
        centering ? "flex-col flex justify-center" : ""
      } mb-8`}
    >
      {popup}

      {newPrompt && (
        <AddPromptModal
          onSubmit={createInputPrompt}
          onClose={() => setNewPrompt(false)}
        />
      )}

      {newPromptId && (
        <EditPromptModal
          promptId={newPromptId}
          editInputPrompt={editInputPrompt}
          onClose={() => setNewPromptId(null)}
        />
      )}
      <div className={centering ? "max-w-sm mx-auto" : ""}>
        <Text className="mb-2 my-auto">
          Create prompts that can be accessed with the <i>`/`</i> shortcut in
          Danswer Chat.{" "}
          {isPublic
            ? "Prompts created here will be accessible to all users."
            : "Prompts created here will be available only to you."}
        </Text>
      </div>

      <div className="mb-2"></div>

      <Button
        onClick={() => setNewPrompt(true)}
        className={centering ? "mx-auto" : ""}
        variant="navigate"
        size="sm"
      >
        New Prompt
      </Button>

      <Separator />

      <div>
        <PromptLibraryTable
          isPublic={isPublic}
          promptLibrary={promptLibrary}
          setPopup={setPopup}
          refresh={refreshPrompts}
          handleEdit={handleEdit}
        />
      </div>
    </div>
  );
};
