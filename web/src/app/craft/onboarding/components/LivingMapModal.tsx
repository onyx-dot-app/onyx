"use client";

import { useEffect, useRef, useState } from "react";
import { AnimatePresence, motion, useReducedMotion } from "motion/react";
import Modal from "@/refresh-components/Modal";
import { Button, Text } from "@opal/components";
import { SvgArrowLeft, SvgArrowRight } from "@opal/icons";
import { cn } from "@opal/utils";
import LivingMapDiagram, {
  LIVING_MAP_DIVE_MS,
  LIVING_MAP_STAGES,
  LivingMapStageId,
} from "@/app/craft/onboarding/components/LivingMapDiagram";

// ---------------------------------------------------------------------------
// The Living Map tour — one fixed "Meet Craft" title, four camera framings of
// one world. Each Next pulls the camera back and refocuses; the final CTA
// dives back into the prompt and hands off to the real input. Clicking any
// map node jumps to its stage.
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
  initialStage = "prompt",
}: LivingMapModalProps) {
  const reduceMotion = useReducedMotion() ?? false;
  const [stageIdx, setStageIdx] = useState(() => stageIndex(initialStage));
  const [diving, setDiving] = useState(false);
  const diveTimer = useRef<number | null>(null);

  useEffect(() => {
    if (open) {
      setStageIdx(stageIndex(initialStage));
      setDiving(false);
    }
  }, [open, initialStage]);

  useEffect(
    () => () => {
      if (diveTimer.current !== null) window.clearTimeout(diveTimer.current);
    },
    []
  );

  if (!open) return null;

  const stage = LIVING_MAP_STAGES[stageIdx]!;
  const isFirstStage = stageIdx === 0;
  const isLastStage = stageIdx === LIVING_MAP_STAGES.length - 1;

  // The completion shot: dive the camera back into the prompt, then hand off
  // to the real input.
  function finish() {
    if (diving) return;
    if (reduceMotion) {
      onComplete();
      return;
    }
    setDiving(true);
    diveTimer.current = window.setTimeout(onComplete, LIVING_MAP_DIVE_MS);
  }

  return (
    <Modal open onOpenChange={(o) => !o && onDismiss()}>
      {/* A stray backdrop click shouldn't permanently dismiss the tour —
          closing is via Escape, the header X, or the final CTA. */}
      <Modal.Content
        width="xl"
        height="fit"
        onPointerDownOutside={(event) => event.preventDefault()}
      >
        {/* The X routes through Radix → onOpenChange, which owns dismissal;
            a real handler here would double-fire onDismiss. */}
        <Modal.Header title="Meet Craft" onClose={() => {}} />
        <Modal.Body padding={1.5}>
          <div className="flex w-full flex-col gap-3">
            {/* Stage copy crossfades above a scene that never unmounts. */}
            <div className="relative h-14">
              <AnimatePresence initial={false}>
                <motion.div
                  key={stage.id}
                  initial={reduceMotion ? false : { opacity: 0 }}
                  animate={{ opacity: 1 }}
                  exit={reduceMotion ? undefined : { opacity: 0 }}
                  transition={{ duration: 0.3 }}
                  className="absolute inset-0 flex flex-col items-center justify-center gap-0.5 text-center"
                >
                  <Text font="heading-h3" color="text-05">
                    {stage.title}
                  </Text>
                  <Text font="secondary-body" color="text-03">
                    {stage.caption}
                  </Text>
                </motion.div>
              </AnimatePresence>
            </div>
            <LivingMapDiagram
              stage={stage.id}
              diving={diving}
              onSelectStage={(id) => {
                if (!diving) setStageIdx(stageIndex(id));
              }}
            />
          </div>
        </Modal.Body>
        <Modal.Footer justifyContent="between">
          <div className="flex-1 flex justify-start">
            {!isFirstStage && (
              <Button
                prominence="secondary"
                icon={SvgArrowLeft}
                disabled={diving}
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
              <Button disabled={diving} onClick={finish}>
                Put Craft to work
              </Button>
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
