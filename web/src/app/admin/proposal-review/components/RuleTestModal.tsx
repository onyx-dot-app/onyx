"use client";

import { useState } from "react";
import { Button, Text, Tag } from "@opal/components";
import { SvgPlayCircle } from "@opal/icons";
import Modal from "@/refresh-components/Modal";
import SimpleLoader from "@/refresh-components/loaders/SimpleLoader";
import { Section } from "@/layouts/general-layouts";
import type { TagColor } from "@opal/components";

type Verdict = "PASS" | "FAIL" | "FLAG" | "NEEDS_REVIEW" | "NOT_APPLICABLE";
type Confidence = "HIGH" | "MEDIUM" | "LOW";

interface RuleTestResult {
  verdict: Verdict;
  confidence: Confidence;
  evidence: string | null;
  explanation: string;
  suggested_action: string | null;
  llm_model: string;
  llm_tokens_used: number;
}

interface RuleTestResponse {
  rule_id: string;
  success: boolean;
  result?: RuleTestResult;
  error?: string;
}

interface RuleTestModalProps {
  open: boolean;
  onClose: () => void;
  rule: { id: string; name: string } | null;
}

const VERDICT_COLOR: Record<Verdict, TagColor> = {
  PASS: "green",
  FAIL: "purple",
  FLAG: "amber",
  NEEDS_REVIEW: "blue",
  NOT_APPLICABLE: "gray",
};

const VERDICT_LABEL: Record<Verdict, string> = {
  PASS: "Pass",
  FAIL: "Fail",
  FLAG: "Flag",
  NEEDS_REVIEW: "Needs Review",
  NOT_APPLICABLE: "Not Applicable",
};

const CONFIDENCE_COLOR: Record<Confidence, TagColor> = {
  HIGH: "green",
  MEDIUM: "amber",
  LOW: "gray",
};

function RuleTestModal({ open, onClose, rule }: RuleTestModalProps) {
  const [loading, setLoading] = useState(false);
  const [response, setResponse] = useState<RuleTestResponse | null>(null);

  async function runTest() {
    if (!rule) return;
    setLoading(true);
    setResponse(null);
    try {
      const res = await fetch(`/api/proposal-review/rules/${rule.id}/test`, {
        method: "POST",
      });
      const data: RuleTestResponse = await res.json();
      setResponse(data);
    } catch {
      setResponse({
        rule_id: rule.id,
        success: false,
        error: "Network error. Please try again.",
      });
    } finally {
      setLoading(false);
    }
  }

  function handleClose() {
    setResponse(null);
    setLoading(false);
    onClose();
  }

  if (!open || !rule) return null;

  return (
    <Modal open onOpenChange={(isOpen) => !isOpen && handleClose()}>
      <Modal.Content width="sm" height="lg" preventAccidentalClose={false}>
        <Modal.Header
          icon={SvgPlayCircle}
          title={`Test Rule: ${rule.name}`}
          description="Tests the rule against a minimal sample context. Results are illustrative only."
          onClose={handleClose}
        />

        <Modal.Body>
          {!loading && !response && (
            <Section alignItems="center" gap={1}>
              <Text font="main-ui-body" color="text-03">
                Click the button below to evaluate this rule against a minimal
                sample context.
              </Text>
              <Button icon={SvgPlayCircle} onClick={runTest}>
                Run Test
              </Button>
            </Section>
          )}

          {loading && (
            <Section alignItems="center" gap={1}>
              <SimpleLoader />
              <Text font="main-ui-body" color="text-03">
                Running test...
              </Text>
            </Section>
          )}

          {response && !response.success && (
            <Section alignItems="start" gap={0.5}>
              <Text font="main-ui-action" color="text-04">
                Error
              </Text>
              <div className="w-full rounded-08 bg-status-error-01 p-3">
                <Text font="main-ui-body" color="text-05">
                  {response.error || "An unknown error occurred."}
                </Text>
              </div>
            </Section>
          )}

          {response && response.success && response.result && (
            <Section alignItems="start" gap={1}>
              {/* Verdict and Confidence */}
              <div className="flex items-center gap-2">
                <Tag
                  title={VERDICT_LABEL[response.result.verdict]}
                  color={VERDICT_COLOR[response.result.verdict]}
                  size="md"
                />
                <Tag
                  title={response.result.confidence}
                  color={CONFIDENCE_COLOR[response.result.confidence]}
                />
              </div>

              {/* Evidence */}
              {response.result.evidence && (
                <Section alignItems="start" gap={0.25}>
                  <Text font="main-ui-action" color="text-04">
                    Evidence
                  </Text>
                  <div className="w-full rounded-08 bg-background-neutral-02 p-3 border-l-2 border-border-03">
                    <Text font="secondary-body" color="text-03" as="p">
                      {response.result.evidence}
                    </Text>
                  </div>
                </Section>
              )}

              {/* Explanation */}
              <Section alignItems="start" gap={0.25}>
                <Text font="main-ui-action" color="text-04">
                  Explanation
                </Text>
                <Text font="main-ui-body" color="text-03" as="p">
                  {response.result.explanation}
                </Text>
              </Section>

              {/* Suggested Action */}
              {response.result.suggested_action && (
                <Section alignItems="start" gap={0.25}>
                  <Text font="main-ui-action" color="text-04">
                    Suggested Action
                  </Text>
                  <Text font="main-ui-body" color="text-03" as="p">
                    {response.result.suggested_action}
                  </Text>
                </Section>
              )}

              {/* LLM info footer */}
              <div className="flex items-center gap-3 pt-2 w-full">
                <Text font="secondary-body" color="text-02">
                  {`Model: ${response.result.llm_model}`}
                </Text>
                <Text font="secondary-body" color="text-02">
                  {`Tokens: ${response.result.llm_tokens_used.toLocaleString()}`}
                </Text>
              </div>
            </Section>
          )}
        </Modal.Body>

        <Modal.Footer>
          <Button prominence="secondary" onClick={handleClose}>
            Close
          </Button>
          {response && (
            <Button icon={SvgPlayCircle} onClick={runTest} disabled={loading}>
              Run Again
            </Button>
          )}
        </Modal.Footer>
      </Modal.Content>
    </Modal>
  );
}

export default RuleTestModal;
