"use client";

import { useEffect, useState } from "react";
import Modal from "@/refresh-components/Modal";
import { Button } from "@opal/components";
import { SvgArrowLeft, SvgArrowRight } from "@opal/icons";
import { cn } from "@opal/utils";
import LivingMapDiagram, {
  LIVING_MAP_STAGES,
  LivingMapStageId,
} from "@/app/craft/onboarding/components/LivingMapDiagram";

// ---------------------------------------------------------------------------
// The Living Map — an onboarding tour that teaches Craft as a system, not a
// single build. One fixed title ("Meet Craft") spans all stages; each stage's
// description carries the narrative. Stage 1 covers the core loop (prompt →
// Craft in its workspace → output); later stages attach the ecosystem — apps,
// skills, scheduled tasks, team sharing — one piece at a time, ending on the
// complete constellation. Clicking any node jumps to its stage.
// ---------------------------------------------------------------------------

function stageIndex(id: LivingMapStageId): number {
  return LIVING_MAP_STAGES.findIndex((stage) => stage.id === id);
}

interface LivingMapModalProps {
  open: boolean;
  /** Explicit finish via the final CTA. */
  onComplete: () => void;
  /** Bail-out via Escape or the header X. Defaults to onComplete. */
  onDismiss?: () => void;
  /** Stage the tour opens on. */
  initialStage?: LivingMapStageId;
}

export default function LivingMapModal({
  open,
  onComplete,
  onDismiss = onComplete,
  initialStage = "loop",
}: LivingMapModalProps) {
  const [stageIdx, setStageIdx] = useState(() => stageIndex(initialStage));

  useEffect(() => {
    if (open) setStageIdx(stageIndex(initialStage));
  }, [open, initialStage]);

  if (!open) return null;

  const stage = LIVING_MAP_STAGES[stageIdx]!;
  const isFirstStage = stageIdx === 0;
  const isLastStage = stageIdx === LIVING_MAP_STAGES.length - 1;

  return (
    <Modal open onOpenChange={(o) => !o && onDismiss()}>
      <Modal.Content width="xl" height="fit">
        <Modal.Header
          title="Meet Craft"
          description={stage.description}
          onClose={onDismiss}
        />
        <Modal.Body padding={1.5}>
          <LivingMapDiagram
            stage={stage.id}
            onSelectStage={(id) => setStageIdx(stageIndex(id))}
          />
        </Modal.Body>
        <Modal.Footer justifyContent="between">
          <div className="flex-1 flex justify-start">
            {!isFirstStage && (
              <Button
                prominence="secondary"
                icon={SvgArrowLeft}
                onClick={() => setStageIdx(stageIdx - 1)}
              >
                Back
              </Button>
            )}
          </div>
          <div className="flex items-center gap-2">
            {LIVING_MAP_STAGES.map((s, i) => (
              <div
                key={s.id}
                className={cn(
                  "w-2 h-2 rounded-full transition-colors",
                  i === stageIdx ? "bg-text-05" : "bg-border-01"
                )}
              />
            ))}
          </div>
          <div className="flex-1 flex justify-end">
            {isLastStage ? (
              <Button onClick={onComplete}>Put Craft to work</Button>
            ) : (
              <Button
                rightIcon={SvgArrowRight}
                onClick={() => setStageIdx(stageIdx + 1)}
              >
                Next
              </Button>
            )}
          </div>
        </Modal.Footer>
      </Modal.Content>
    </Modal>
  );
}
