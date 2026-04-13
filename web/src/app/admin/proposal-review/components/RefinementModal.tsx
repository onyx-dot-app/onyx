"use client";

import { useState } from "react";
import { Button, Text } from "@opal/components";
import { SvgEdit } from "@opal/icons";
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
  const [loading, setLoading] = useState(false);

  function handleClose() {
    setAnswer("");
    setLoading(false);
    onClose();
  }

  async function handleSubmit() {
    if (!rule || !answer.trim()) return;
    setLoading(true);
    try {
      const res = await fetch(`/api/proposal-review/rules/${rule.id}/refine`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ answer: answer.trim() }),
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
          description={rule.name}
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
