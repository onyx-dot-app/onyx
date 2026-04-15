"use client";

import { useRef, useState } from "react";
import { Button, Text } from "@opal/components";
import { SvgEdit, SvgPaperclip, SvgX } from "@opal/icons";
import Modal from "@/refresh-components/Modal";
import InputTextArea from "@/refresh-components/inputs/InputTextArea";
import SimpleLoader from "@/refresh-components/loaders/SimpleLoader";
import { Section } from "@/layouts/general-layouts";
import { toast } from "@/hooks/useToast";
import type { RuleResponse } from "@/app/admin/proposal-review/interfaces";

interface RefinementModalProps {
  open: boolean;
  onClose: () => void;
  rule: RuleResponse | null;
  onRefined: () => void;
}

function RefinementModal({
  open,
  onClose,
  rule,
  onRefined,
}: RefinementModalProps) {
  const [answer, setAnswer] = useState("");
  const [file, setFile] = useState<File | null>(null);
  const [loading, setLoading] = useState(false);
  const fileInputRef = useRef<HTMLInputElement>(null);

  function handleClose() {
    setAnswer("");
    setFile(null);
    setLoading(false);
    onClose();
  }

  async function handleSubmit() {
    if (!rule || !answer.trim()) return;
    setLoading(true);
    try {
      const formData = new FormData();
      formData.append("answer", answer.trim());
      if (file) {
        formData.append("file", file);
      }
      const res = await fetch(`/api/proposal-review/rules/${rule.id}/refine`, {
        method: "POST",
        body: formData,
      });
      if (!res.ok) {
        const err = await res.json().catch(() => ({}));
        throw new Error(err.detail || "Refinement failed");
      }
      toast.success("Rule refined successfully.");
      onRefined();
      handleClose();
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Failed to refine rule");
    } finally {
      setLoading(false);
    }
  }

  if (!open || !rule) return null;

  return (
    <Modal open onOpenChange={(isOpen) => !isOpen && handleClose()}>
      <Modal.Content
        width="sm"
        height="lg"
        onPointerDownOutside={(e) => e.preventDefault()}
        onEscapeKeyDown={(e) => e.preventDefault()}
      >
        <Modal.Header
          icon={SvgEdit}
          title="Refine Rule"
          onClose={handleClose}
        />

        <Modal.Body>
          {loading ? (
            <Section alignItems="center" gap={1}>
              <SimpleLoader />
              <Text font="main-ui-body" color="text-03">
                Refining rule...
              </Text>
            </Section>
          ) : (
            <Section alignItems="start" gap={1}>
              <Section alignItems="start" gap={0.25}>
                <Text font="main-ui-action" color="text-04">
                  Rule
                </Text>
                <div className="w-full rounded-08 bg-background-neutral-02 p-3 flex flex-col gap-1">
                  <Text font="main-ui-action" color="text-05">
                    {rule.name}
                  </Text>
                  {rule.description && (
                    <Text font="secondary-body" color="text-03">
                      {rule.description}
                    </Text>
                  )}
                </div>
              </Section>

              <Section alignItems="start" gap={0.25}>
                <Text font="main-ui-action" color="text-04">
                  Question from the AI
                </Text>
                <div className="w-full rounded-08 bg-status-warning-01 p-3">
                  <Text font="main-ui-body" color="text-05">
                    {rule.refinement_question ?? undefined}
                  </Text>
                </div>
              </Section>

              <Section alignItems="start" gap={0.25}>
                <Text font="main-ui-action" color="text-04">
                  Your Answer
                </Text>
                <Text font="secondary-body" color="text-03">
                  Provide the institution-specific information requested above.
                  The AI will use your answer to refine the rule.
                </Text>
                <InputTextArea
                  value={answer}
                  onChange={(e) => setAnswer(e.target.value)}
                  placeholder="Enter your answer..."
                  rows={5}
                />
                <input
                  ref={fileInputRef}
                  type="file"
                  accept=".pdf,.docx,.doc,.txt,.md,.rtf"
                  onChange={(e) => {
                    const selected = e.target.files?.[0] ?? null;
                    setFile(selected);
                    e.target.value = "";
                  }}
                  className="hidden"
                />
                {file ? (
                  <div className="flex items-center gap-2 w-full rounded-08 bg-background-neutral-02 px-3 py-2">
                    <SvgPaperclip className="size-4 shrink-0 text-text-03" />
                    <div className="truncate flex-1">
                      <Text font="secondary-body" color="text-04">
                        {file.name}
                      </Text>
                    </div>
                    <Button
                      icon={SvgX}
                      prominence="tertiary"
                      size="2xs"
                      onClick={() => setFile(null)}
                      tooltip="Remove file"
                    />
                  </div>
                ) : (
                  <Button
                    icon={SvgPaperclip}
                    prominence="tertiary"
                    size="sm"
                    onClick={() => fileInputRef.current?.click()}
                  >
                    Attach file
                  </Button>
                )}
              </Section>
            </Section>
          )}
        </Modal.Body>

        <Modal.Footer>
          <Button
            prominence="secondary"
            onClick={handleClose}
            disabled={loading}
          >
            Cancel
          </Button>
          <Button onClick={handleSubmit} disabled={loading || !answer.trim()}>
            {loading ? "Refining..." : "Submit Answer"}
          </Button>
        </Modal.Footer>
      </Modal.Content>
    </Modal>
  );
}

export default RefinementModal;
