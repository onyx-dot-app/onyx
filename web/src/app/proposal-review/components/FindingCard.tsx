"use client";

import { useState, useCallback, useEffect, useRef } from "react";
import { Button, Tag, Text, Card } from "@opal/components";
import {
  SvgCheckCircle,
  SvgAlertTriangle,
  SvgAlertCircle,
  SvgShield,
} from "@opal/icons";
import { markdown } from "@opal/utils";
import { cn } from "@/lib/utils";
import { Section } from "@/layouts/general-layouts";
import InputTextArea from "@/refresh-components/inputs/InputTextArea";
import { toast } from "@/hooks/useToast";
import { submitFindingDecision } from "@/app/proposal-review/services/apiServices";
import {
  VERDICT_CONFIG,
  type Finding,
  type DecisionAction,
} from "@/app/proposal-review/types";

// ---------------------------------------------------------------------------
// Props
// ---------------------------------------------------------------------------

interface FindingCardProps {
  finding: Finding;
  isFocused?: boolean;
  onFocusHandled?: () => void;
  onDecisionSaved: () => void;
}

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

export default function FindingCard({
  finding,
  isFocused,
  onFocusHandled,
  onDecisionSaved,
}: FindingCardProps) {
  const cardRef = useRef<HTMLDivElement>(null);
  const {
    rule_name,
    rule_is_hard_stop,
    verdict,
    explanation,
    evidence,
    suggested_action,
    decision,
  } = finding;

  const isActionable = verdict === "FAIL" || verdict === "FLAG";
  const isNeedsReview = verdict === "NEEDS_REVIEW";
  const isPass = verdict === "PASS" || verdict === "NOT_APPLICABLE";

  // Default expansion: FAIL/FLAG/NEEDS_REVIEW expanded, PASS collapsed
  const [isExpanded, setIsExpanded] = useState(!isPass);
  const [notes, setNotes] = useState(decision?.notes ?? "");
  const [currentAction, setCurrentAction] = useState<DecisionAction | null>(
    decision?.action ?? null
  );
  const [isSaving, setIsSaving] = useState(false);

  // Scroll into view and expand when focused from sidebar.
  // Delay accounts for the Radix collapsible open animation (~200ms).
  useEffect(() => {
    if (isFocused && cardRef.current) {
      setIsExpanded(true);
      const timer = setTimeout(() => {
        cardRef.current?.scrollIntoView({
          behavior: "smooth",
          block: "center",
        });
      }, 250);
      onFocusHandled?.();
      return () => clearTimeout(timer);
    }
  }, [isFocused, onFocusHandled]);

  const verdictConfig = VERDICT_CONFIG[verdict];

  const handleDecision = useCallback(
    async (action: DecisionAction) => {
      setIsSaving(true);
      try {
        await submitFindingDecision(finding.id, action, notes || undefined);
        setCurrentAction(action);
        onDecisionSaved();
      } catch (err) {
        toast.error(
          err instanceof Error ? err.message : "Failed to save finding decision"
        );
      } finally {
        setIsSaving(false);
      }
    },
    [finding.id, notes, onDecisionSaved]
  );

  const handleNotesBlur = useCallback(async () => {
    if (currentAction && notes !== (decision?.notes ?? "")) {
      setIsSaving(true);
      try {
        await submitFindingDecision(
          finding.id,
          currentAction,
          notes || undefined
        );
        onDecisionSaved();
      } catch (err) {
        toast.error(
          err instanceof Error ? err.message : "Failed to save notes"
        );
      } finally {
        setIsSaving(false);
      }
    }
  }, [currentAction, notes, decision?.notes, finding.id, onDecisionSaved]);

  return (
    <div ref={cardRef}>
      <Card
        padding="md"
        border="solid"
        background={rule_is_hard_stop && isActionable ? "heavy" : "light"}
      >
        <Section
          gap={0.75}
          height="auto"
          justifyContent="start"
          alignItems="start"
          className={cn(
            rule_is_hard_stop &&
              isActionable &&
              "border-l-2 border-status-error-03 pl-3"
          )}
        >
          {/* Header row: verdict tag + rule name */}
          <div
            role="button"
            tabIndex={0}
            aria-expanded={isExpanded}
            aria-label={`${rule_name ?? "Unnamed Rule"} - ${
              verdictConfig.label
            }`}
            className="flex items-center gap-2 text-left w-full cursor-pointer"
            onClick={() => setIsExpanded((prev) => !prev)}
            onKeyDown={(e) => {
              if (e.key === "Enter" || e.key === " ") {
                e.preventDefault();
                setIsExpanded((prev) => !prev);
              }
            }}
          >
            <Tag title={verdictConfig.label} color={verdictConfig.color} />
            <Text font="main-ui-action" color="text-04" as="span">
              {rule_name ?? "Unnamed Rule"}
            </Text>
            {rule_is_hard_stop && isActionable && (
              <div className="flex items-center gap-1 pl-2">
                <SvgShield className="h-4 w-4 text-status-error-03" />
                <Text font="secondary-body" color="text-03">
                  Hard Stop
                </Text>
              </div>
            )}
          </div>

          {/* Expanded content */}
          {isExpanded && (
            <Section
              gap={0.75}
              height="auto"
              justifyContent="start"
              alignItems="start"
              className="pl-2"
            >
              {/* Explanation */}
              {explanation && (
                <Text font="main-ui-body" color="text-03" as="p">
                  {markdown(explanation)}
                </Text>
              )}

              {/* Evidence */}
              {evidence && (
                <Card padding="sm" rounding="sm" background="heavy">
                  <Text font="secondary-body" color="text-03" as="p">
                    Evidence:
                  </Text>
                  <Text font="main-ui-body" color="text-03" as="p">
                    {markdown(`\u201C${evidence}\u201D`)}
                  </Text>
                </Card>
              )}

              {/* Suggested action */}
              {suggested_action && (
                <div className="flex items-start gap-2">
                  <SvgAlertCircle className="h-4 w-4 text-status-warning-03 shrink-0 mt-0.5" />
                  <Text font="secondary-body" color="text-03" as="p">
                    {markdown(suggested_action)}
                  </Text>
                </div>
              )}

              {/* Action buttons + notes */}
              {(isActionable || isNeedsReview) && (
                <div className="pt-4 border-t border-border-01 w-full">
                  <Section
                    gap={0.5}
                    height="auto"
                    justifyContent="start"
                    alignItems="start"
                  >
                    <Section
                      flexDirection="row"
                      gap={0.5}
                      height="auto"
                      justifyContent="start"
                      alignItems="center"
                    >
                      <Button
                        variant={
                          currentAction === "VERIFIED" ? "action" : "default"
                        }
                        prominence={
                          currentAction === "VERIFIED" ? "primary" : "secondary"
                        }
                        size="sm"
                        icon={SvgCheckCircle}
                        disabled={isSaving}
                        onClick={() => handleDecision("VERIFIED")}
                      >
                        Verify
                      </Button>
                      <Button
                        variant={
                          currentAction === "ISSUE" ? "danger" : "default"
                        }
                        prominence={
                          currentAction === "ISSUE" ? "primary" : "secondary"
                        }
                        size="sm"
                        icon={SvgAlertTriangle}
                        disabled={isSaving}
                        onClick={() => handleDecision("ISSUE")}
                      >
                        Issue
                      </Button>
                      <Button
                        variant={
                          currentAction === "NOT_APPLICABLE"
                            ? "action"
                            : "default"
                        }
                        prominence={
                          currentAction === "NOT_APPLICABLE"
                            ? "primary"
                            : "secondary"
                        }
                        size="sm"
                        disabled={isSaving}
                        onClick={() => handleDecision("NOT_APPLICABLE")}
                      >
                        N/A
                      </Button>
                    </Section>

                    <InputTextArea
                      placeholder="Notes (optional)"
                      value={notes}
                      onChange={(e) => setNotes(e.target.value)}
                      onBlur={handleNotesBlur}
                      rows={2}
                    />
                  </Section>
                </div>
              )}
            </Section>
          )}
        </Section>
      </Card>
    </div>
  );
}
