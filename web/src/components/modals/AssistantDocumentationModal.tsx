"use client";

import { useState, useEffect } from "react";
import Modal from "@/refresh-components/Modal";
import Text from "@/refresh-components/texts/Text";
import { MinimalPersonaSnapshot } from "@/app/admin/assistants/interfaces";
import { useAgentsContext } from "@/refresh-components/contexts/AgentsContext";

interface AssistantDocumentationModalProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  assistantId: number | null;
}

export default function AssistantDocumentationModal({
  open,
  onOpenChange,
  assistantId,
}: AssistantDocumentationModalProps) {
  const { agents } = useAgentsContext();
  const [assistant, setAssistant] = useState<MinimalPersonaSnapshot | null>(
    null
  );

  useEffect(() => {
    if (assistantId && agents) {
      const foundAssistant = agents.find((a) => a.id === assistantId);
      setAssistant(foundAssistant || null);
    }
  }, [assistantId, agents]);

  if (!assistant) {
    return null;
  }

  return (
    <Modal open={open} onOpenChange={onOpenChange}>
      <Modal.Content medium>
        <Modal.Header className="p-6" withBottomShadow>
          <Modal.CloseButton />
          <Modal.Title>Documentation - {assistant.name}</Modal.Title>
          {assistant.description && (
            <Modal.Description className="mt-2">
              {assistant.description}
            </Modal.Description>
          )}
        </Modal.Header>

        <Modal.Body className="flex-1 overflow-auto p-6">
          <div className="flex flex-col gap-4">
            <div>
              <Text headingH3 className="mb-2">
                À propos de cet assistant
              </Text>
              <Text text03>
                Cet assistant est configuré pour vous aider avec vos questions.
                {assistant.description
                  ? ` ${assistant.description}`
                  : " Utilisez-le pour obtenir des réponses rapides et précises."}
              </Text>
            </div>

            {assistant.tools && assistant.tools.length > 0 && (
              <div>
                <Text headingH3 className="mb-2">
                  Outils disponibles
                </Text>
                <div className="flex flex-wrap gap-2">
                  {assistant.tools.map((tool, index) => (
                    <div
                      key={index}
                      className="bg-background-tint-01 rounded-8 px-3 py-1"
                    >
                      <Text text03>{tool.display_name || tool.name}</Text>
                    </div>
                  ))}
                </div>
              </div>
            )}

            <div>
              <Text headingH3 className="mb-2">
                Comment utiliser cet assistant
              </Text>
              <Text text03>
                • Posez vos questions directement dans la zone de saisie
                <br />
                • L'assistant peut rechercher dans vos documents si configuré
                <br />
                • Vous pouvez joindre des fichiers pour obtenir des réponses
                contextuelles
                <br />
                • Utilisez les suggestions pour démarrer rapidement une
                conversation
              </Text>
            </div>
          </div>
        </Modal.Body>
      </Modal.Content>
    </Modal>
  );
}

