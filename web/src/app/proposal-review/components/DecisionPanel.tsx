"use client";

import { useState, useCallback } from "react";
import { Button, Text, Card } from "@opal/components";
import {
  SvgCheckCircle,
  SvgAlertTriangle,
  SvgXCircle,
  SvgRefreshCw,
} from "@opal/icons";
import { cn } from "@/lib/utils";
import { Section } from "@/layouts/general-layouts";
import InputTextArea from "@/refresh-components/inputs/InputTextArea";
import "@/app/proposal-review/components/decision-toggle.css";
import { toast } from "@/hooks/useToast";
import {
  submitProposalDecision,
  syncToJira,
} from "@/app/proposal-review/services/apiServices";
import type {
  ProposalDecisionOutcome,
  ProposalStatus,
  Finding,
} from "@/app/proposal-review/types";

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

/** Map proposal status back to a decision outcome, or null if no decision yet. */
function statusToDecision(
  status: ProposalStatus
): ProposalDecisionOutcome | null {
  if (status === "APPROVED") return "APPROVED";
  if (status === "CHANGES_REQUESTED") return "CHANGES_REQUESTED";
  if (status === "REJECTED") return "REJECTED";
  return null;
}

// ---------------------------------------------------------------------------
// Props
// ---------------------------------------------------------------------------

interface DecisionPanelProps {
  proposalId: string;
  findings: Finding[];
  proposalStatus: ProposalStatus;
  existingDecisionNotes?: string;
  onDecisionSubmitted: () => void;
}

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

export default function DecisionPanel({
  proposalId,
  findings,
  proposalStatus,
  existingDecisionNotes,
  onDecisionSubmitted,
}: DecisionPanelProps) {
  const existingDecision = statusToDecision(proposalStatus);

  const [selectedDecision, setSelectedDecision] =
    useState<ProposalDecisionOutcome | null>(existingDecision);
  const [notes, setNotes] = useState(existingDecisionNotes ?? "");
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [isSyncing, setIsSyncing] = useState(false);
  const [submitError, setSubmitError] = useState<string | null>(null);
  const [decisionSaved, setDecisionSaved] = useState(existingDecision !== null);

  // Check for unresolved hard stops
  const unresolvedHardStops = findings.filter(
    (f) =>
      f.rule_is_hard_stop &&
      (f.verdict === "FAIL" || f.verdict === "FLAG") &&
      (!f.decision_action || f.decision_action === "ISSUE")
  );
  const hasUnresolvedHardStops = unresolvedHardStops.length > 0;

  const handleSubmit = useCallback(async () => {
    if (!selectedDecision) return;

    setIsSubmitting(true);
    setSubmitError(null);

    try {
      await submitProposalDecision(
        proposalId,
        selectedDecision,
        notes || undefined
      );
      setDecisionSaved(true);
      onDecisionSubmitted();
    } catch (err) {
      setSubmitError(
        err instanceof Error ? err.message : "Failed to submit decision"
      );
    } finally {
      setIsSubmitting(false);
    }
  }, [proposalId, selectedDecision, notes, onDecisionSubmitted]);

  const handleSync = useCallback(async () => {
    setIsSyncing(true);
    try {
      await syncToJira(proposalId);
    } catch {
      toast.error("Failed to sync to Jira");
    } finally {
      setIsSyncing(false);
    }
  }, [proposalId]);

  return (
    <Card padding="md" border="solid" background="light">
      <Section
        gap={0.75}
        height="auto"
        justifyContent="start"
        alignItems="start"
      >
        <Text font="main-ui-action" color="text-04">
          Final Decision
        </Text>

        {/* Decision buttons */}
        <Section
          gap={0.5}
          height="auto"
          justifyContent="start"
          alignItems="start"
        >
          <div
            className={cn(
              selectedDecision === "APPROVED" && "decision-toggle-green"
            )}
          >
            <Button
              variant="default"
              prominence="secondary"
              icon={SvgCheckCircle}
              disabled={hasUnresolvedHardStops || isSubmitting}
              onClick={() => setSelectedDecision("APPROVED")}
            >
              Approve
            </Button>
          </div>

          {hasUnresolvedHardStops && (
            <Text font="secondary-body" color="text-03">
              {`Cannot approve: ${
                unresolvedHardStops.length
              } unresolved hard stop${
                unresolvedHardStops.length !== 1 ? "s" : ""
              }`}
            </Text>
          )}

          <div
            className={cn(
              selectedDecision === "CHANGES_REQUESTED" &&
                "decision-toggle-yellow"
            )}
          >
            <Button
              variant="default"
              prominence="secondary"
              icon={SvgAlertTriangle}
              disabled={isSubmitting}
              onClick={() => setSelectedDecision("CHANGES_REQUESTED")}
            >
              Request Changes
            </Button>
          </div>

          <Button
            variant={selectedDecision === "REJECTED" ? "danger" : "default"}
            prominence={
              selectedDecision === "REJECTED" ? "primary" : "secondary"
            }
            icon={SvgXCircle}
            disabled={isSubmitting}
            onClick={() => setSelectedDecision("REJECTED")}
          >
            Reject
          </Button>
        </Section>

        {/* Notes */}
        <InputTextArea
          placeholder="Decision notes (optional)"
          value={notes}
          onChange={(e) => setNotes(e.target.value)}
          rows={3}
        />

        {/* Submit + Sync */}
        <Section
          gap={0.5}
          height="auto"
          justifyContent="start"
          alignItems="start"
        >
          <Button
            variant="default"
            prominence="primary"
            disabled={!selectedDecision || isSubmitting}
            onClick={handleSubmit}
          >
            {isSubmitting ? "Submitting..." : "Submit Decision"}
          </Button>

          <Button
            variant="default"
            prominence="secondary"
            icon={SvgRefreshCw}
            disabled={!decisionSaved || isSyncing}
            onClick={handleSync}
          >
            {isSyncing ? "Syncing..." : "Sync to Jira"}
          </Button>
        </Section>

        {submitError && (
          <Text font="secondary-body" color="text-03">
            {submitError}
          </Text>
        )}
      </Section>
    </Card>
  );
}
