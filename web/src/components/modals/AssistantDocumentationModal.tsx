"use client";

import { useState, useEffect, useMemo } from "react";
import Modal from "@/refresh-components/Modal";
import Text from "@/refresh-components/texts/Text";
import { MinimalPersonaSnapshot } from "@/app/admin/assistants/interfaces";
import { useAgentsContext } from "@/refresh-components/contexts/AgentsContext";
import { RichTextSubtext } from "@/components/RichTextSubtext";
import { cn } from "@/lib/utils";

interface AssistantDocumentationModalProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  assistantId: number | null;
}

// Helper function to format description text by splitting sentences
function formatDescription(text: string): string {
  // Split by periods followed by space and capital letter, or by double newlines
  // This preserves natural sentence breaks while allowing manual formatting
  const sentences = text
    .split(/(?<=[.!?])\s+(?=[A-ZÀÁÂÃÄÅÆÇÈÉÊËÌÍÎÏÐÑÒÓÔÕÖØÙÚÛÜÝÞ])/)
    .map((sentence) => sentence.trim())
    .filter((sentence) => sentence.length > 0);
  
  return sentences.join("\n\n");
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


  const hasDocumentSearch = useMemo(() => {
    return (
      assistant?.tools?.some(
        (tool) =>
          tool.name === "search_tool" ||
          tool.name === "retrieval_tool" ||
          tool.display_name?.toLowerCase().includes("search") ||
          tool.display_name?.toLowerCase().includes("recherche")
      ) || false
    );
  }, [assistant?.tools]);

  const hasWebSearch = useMemo(() => {
    return (
      assistant?.tools?.some(
        (tool) =>
          tool.name === "web_tool" ||
          tool.display_name?.toLowerCase().includes("web") ||
          tool.display_name?.toLowerCase().includes("internet")
      ) || false
    );
  }, [assistant?.tools]);

  if (!assistant) {
    return null;
  }

  return (
    <Modal open={open} onOpenChange={onOpenChange}>
      <Modal.Content medium>
        <Modal.Header className="p-6" withBottomShadow>
          <Modal.CloseButton />
          <Modal.Title>Documentation - {assistant.name}</Modal.Title>
        </Modal.Header>

        <Modal.Body className="flex-1 overflow-auto p-6">
          <div className="flex flex-col gap-6">
            {/* Description principale avec formatage simple */}
            {assistant.description && (
              <div>
                <Text headingH3 className="mb-3">
                  À propos de cet assistant
                </Text>
                <div className="whitespace-pre-wrap break-words">
                  <RichTextSubtext
                    text={formatDescription(assistant.description)}
                    className="text-text-03 leading-relaxed"
                  />
                </div>
              </div>
            )}

            {/* Outils disponibles */}
            {assistant.tools && assistant.tools.length > 0 && (
              <div>
                <Text headingH3 className="mb-3">
                  Outils disponibles
                </Text>
                <div className="flex flex-wrap gap-2">
                  {assistant.tools.map((tool, index) => (
                    <div
                      key={index}
                      className="bg-background-tint-01 rounded-8 px-3 py-1.5 border border-border-01"
                    >
                      <Text text03 className="text-text-02">
                        {tool.display_name || tool.name}
                      </Text>
                    </div>
                  ))}
                </div>
              </div>
            )}

            {/* Ensembles de documents */}
            {assistant.document_sets && assistant.document_sets.length > 0 && (
              <div>
                <Text headingH3 className="mb-3">
                  Ensembles de documents
                </Text>
                <div className="space-y-2">
                  {assistant.document_sets.map((docSet, index) => (
                    <div
                      key={index}
                      className="bg-background-tint-01 rounded-8 px-3 py-2 border border-border-01"
                    >
                      <Text text03 className="font-medium text-text-01">
                        {docSet.name}
                      </Text>
                      {docSet.description && (
                        <Text text03 className="text-text-03 mt-1 text-sm">
                          {docSet.description}
                        </Text>
                      )}
                    </div>
                  ))}
                </div>
              </div>
            )}

            {/* Messages de démarrage */}
            {assistant.starter_messages && assistant.starter_messages.length > 0 && (
              <div>
                <Text headingH3 className="mb-3">
                  Suggestions de démarrage
                </Text>
                <div className="space-y-2">
                  {assistant.starter_messages.map((starter, index) => (
                    <div
                      key={index}
                      className="bg-background-tint-01 rounded-8 px-3 py-2 border border-border-01 cursor-pointer hover:bg-background-tint-02 transition-colors"
                    >
                      <Text text03 className="text-text-02">
                        {starter.name || starter.message}
                      </Text>
                    </div>
                  ))}
                </div>
              </div>
            )}

            {/* Comment utiliser */}
            <div>
              <Text headingH3 className="mb-3">
                Comment utiliser cet assistant
              </Text>
              <div className="space-y-2">
                <Text text03 className="text-text-03">
                  • Posez vos questions directement dans la zone de saisie
                </Text>
                {hasDocumentSearch && (
                  <Text text03 className="text-text-03">
                    • L'assistant peut rechercher dans vos documents pour trouver des informations pertinentes
                  </Text>
                )}
                {hasWebSearch && (
                  <Text text03 className="text-text-03">
                    • L'assistant peut effectuer des recherches sur Internet pour obtenir des informations à jour
                  </Text>
                )}
                <Text text03 className="text-text-03">
                  • Vous pouvez joindre des fichiers pour obtenir des réponses contextuelles
                </Text>
                {assistant.starter_messages && assistant.starter_messages.length > 0 && (
                  <Text text03 className="text-text-03">
                    • Utilisez les suggestions de démarrage pour commencer rapidement une conversation
                  </Text>
                )}
              </div>
            </div>
          </div>
        </Modal.Body>
      </Modal.Content>
    </Modal>
  );
}

