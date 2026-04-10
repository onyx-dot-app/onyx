"use client";

import { useState, useCallback } from "react";
import { Button, Text, Card } from "@opal/components";
import {
  SvgCheckCircle,
  SvgAlertTriangle,
  SvgXCircle,
  SvgRefreshCw,
} from "@opal/icons";
import InputTextArea from "@/refresh-components/inputs/InputTextArea";
import { toast } from "@/hooks/useToast";
import {
  submitProposalDecision,
  syncToJira,
} from "@/app/proposal-review/services/apiServices";
import type {
  ProposalDecisionOutcome,
  Finding,
} from "@/app/proposal-review/types";

// ---------------------------------------------------------------------------
// Props
// ---------------------------------------------------------------------------

interface DecisionPanelProps {
  proposalId: string;
  findings: Finding[];
  onDecisionSubmitted: () => void;
}

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

export default function DecisionPanel({
  proposalId,
  findings,
  onDecisionSubmitted,
}: DecisionPanelProps) {
  const [selectedDecision, setSelectedDecision] =
    useState<ProposalDecisionOutcome | null>(null);
  const [notes, setNotes] = useState("");
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [isSyncing, setIsSyncing] = useState(false);
  const [submitError, setSubmitError] = useState<string | null>(null);
  const [decisionSaved, setDecisionSaved] = useState(false);

  // Check for unresolved hard stops
  const unresolvedHardStops = findings.filter(
    (f) =>
      f.rule_is_hard_stop &&
      (f.verdict === "FAIL" || f.verdict === "FLAG") &&
      (!f.decision || f.decision.action === "ISSUE")
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
      <div className="flex flex-col gap-3">
        <Text font="main-ui-action" color="text-01">
          Final Decision
        </Text>

        {/* Decision buttons */}
        <div className="flex flex-col gap-2">
          <Button
            variant={selectedDecision === "APPROVED" ? "action" : "default"}
            prominence={
              selectedDecision === "APPROVED" ? "primary" : "secondary"
            }
            icon={SvgCheckCircle}
            disabled={hasUnresolvedHardStops || isSubmitting}
            onClick={() => setSelectedDecision("APPROVED")}
          >
            Approve
          </Button>

          {hasUnresolvedHardStops && (
            <Text font="secondary-body" color="text-03">
              {`Cannot approve: ${
                unresolvedHardStops.length
              } unresolved hard stop${
                unresolvedHardStops.length !== 1 ? "s" : ""
              }`}
            </Text>
          )}

          <Button
            variant={
              selectedDecision === "CHANGES_REQUESTED" ? "action" : "default"
            }
            prominence={
              selectedDecision === "CHANGES_REQUESTED" ? "primary" : "secondary"
            }
            icon={SvgAlertTriangle}
            disabled={isSubmitting}
            onClick={() => setSelectedDecision("CHANGES_REQUESTED")}
          >
            Request Changes
          </Button>

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
        </div>

        {/* Notes */}
        <InputTextArea
          placeholder="Decision notes (optional)"
          value={notes}
          onChange={(e) => setNotes(e.target.value)}
          rows={3}
        />

        {/* Submit + Sync */}
        <div className="flex flex-col gap-2">
          <Button
            variant="action"
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
        </div>

        {submitError && (
          <Text font="secondary-body" color="text-03">
            {submitError}
          </Text>
        )}
      </div>
    </Card>
  );
}
