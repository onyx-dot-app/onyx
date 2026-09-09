"use client";

import { useEffect, useState } from "react";
import type { KeyboardEvent, ReactNode } from "react";
import { useTranslations } from "next-intl";
import { AnimatePresence, motion, useReducedMotion } from "motion/react";
import { Text } from "@opal/components";
import {
  SvgAlertCircle,
  SvgBubbleText,
  SvgClock,
  SvgCpu,
  SvgDashboard,
  SvgPaperclip,
  SvgShield,
  SvgUsers,
} from "@opal/icons";
import {
  SvgGithub,
  SvgGmail,
  SvgGoogleDocs,
  SvgGoogleDrive,
  SvgLinear,
  SvgSlack,
} from "@opal/logos";
import type { IconFunctionComponent } from "@opal/types";
import { cn } from "@opal/utils";
import CometEdge from "@/app/craft/components/CometEdge";

// ---------------------------------------------------------------------------
// The Living Map, filmed by a camera. The whole Craft system is one fixed
// world (prompt → Craft's machine reading your sources → outputs, with the
// schedule and your team at the edges); each tour stage is a camera framing
// of that world. Advancing pulls the camera back and refocuses: the current
// stage's subjects are sharp, everything else sits soft at the edges like
// out-of-focus depth — so the scene itself says "there's more out here".
// The final CTA dives the camera back into the prompt and lands the user on
// the real input, ready to type.
// ---------------------------------------------------------------------------

const MAP_W = 920;
const MAP_H = 560;

function leftPct(x: number): string {
  return `${(x / MAP_W) * 100}%`;
}

function topPct(y: number): string {
  return `${(y / MAP_H) * 100}%`;
}

export type LivingMapStageId =
  | "prompt"
  | "machine"
  | "output"
  | "constellation";

export interface LivingMapStage {
  id: LivingMapStageId;
}

// Stage title/caption copy lives in the craft.onboarding.livingMap.stages
// message namespace, keyed by stage id.
export const LIVING_MAP_STAGES: LivingMapStage[] = [
  { id: "prompt" },
  { id: "machine" },
  { id: "output" },
  { id: "constellation" },
];

/** What the camera frames per stage: center + visible world width. */
interface Camera {
  cx: number;
  cy: number;
  w: number;
}

const STAGE_CAMERA: Record<LivingMapStageId, Camera> = {
  prompt: { cx: 135, cy: 280, w: 360 },
  machine: { cx: 405, cy: 228, w: 780 },
  output: { cx: 560, cy: 320, w: 680 },
  constellation: { cx: 460, cy: 285, w: 950 },
};

/** Where the completion dive lands: back inside the prompt card. */
const DIVE_CAMERA: Camera = { cx: 130, cy: 280, w: 240 };

/** How long the dive-out shot runs before the modal should hand off. */
export const LIVING_MAP_DIVE_MS = 450;

type MapGroupId =
  | "prompt"
  | "sources"
  | "workspace"
  | "outputs"
  | "schedule"
  | "team";

/** Groups the camera has in focus per stage; the rest blur into depth. */
const STAGE_SHARP: Record<LivingMapStageId, MapGroupId[]> = {
  prompt: ["prompt"],
  machine: ["prompt", "sources", "workspace"],
  output: ["workspace", "outputs", "schedule"],
  constellation: [
    "prompt",
    "sources",
    "workspace",
    "outputs",
    "schedule",
    "team",
  ],
};

/** Which tour stage a click on each group jumps to. */
const GROUP_STAGE: Record<MapGroupId, LivingMapStageId> = {
  prompt: "prompt",
  sources: "machine",
  workspace: "machine",
  outputs: "output",
  schedule: "output",
  team: "constellation",
};

interface MapEdge {
  id: string;
  group: MapGroupId;
  d: string;
}

const EDGES: MapEdge[] = [
  // Sources rain into the workspace.
  {
    id: "src-slack",
    group: "sources",
    d: "M 280 66 C 280 118, 385 132, 405 168",
  },
  {
    id: "src-drive",
    group: "sources",
    d: "M 390 66 C 390 112, 430 130, 440 168",
  },
  {
    id: "src-linear",
    group: "sources",
    d: "M 500 66 C 500 110, 480 130, 476 168",
  },
  {
    id: "src-gmail",
    group: "sources",
    d: "M 610 66 C 610 112, 520 130, 512 168",
  },
  {
    id: "src-files",
    group: "sources",
    d: "M 720 66 C 720 118, 565 132, 548 168",
  },
  // The prompt feeds the machine.
  {
    id: "prompt-in",
    group: "workspace",
    d: "M 232 280 C 268 280, 294 280, 328 280",
  },
  // Work flows out.
  {
    id: "out-doc",
    group: "outputs",
    d: "M 622 225 C 640 215, 640 184, 653 176",
  },
  {
    id: "out-app",
    group: "outputs",
    d: "M 622 265 C 636 268, 642 275, 653 279",
  },
  {
    id: "out-pr",
    group: "outputs",
    d: "M 622 305 C 640 320, 640 372, 653 384",
  },
  // The schedule re-runs the prompt.
  {
    id: "schedule-loop",
    group: "schedule",
    d: "M 320 472 C 300 420, 190 380, 150 335",
  },
  // The hosted app reaches the team — one link shares it.
  {
    id: "team-share",
    group: "team",
    d: "M 806 310 C 862 352, 858 438, 800 484",
  },
];

const TERMINAL_LINES: string[] = [
  '$ onyx search "q2 invoices"',
  "$ python analyze_spend.py",
  "$ write outputs/summary.md",
];

// Typed lines plus the trailing approval pill.
const TERMINAL_STEPS = TERMINAL_LINES.length + 1;

const EXAMPLE_PROMPT_KEYS = [
  "vendorSpend",
  "slackToLinear",
  "launchDeck",
  "flakyRetryTest",
  "rfpSecurity",
] as const;

const PROMPT_ROTATION_MS = 3000;

interface SourceChipSpec {
  x: number;
  label: string;
  icon: IconFunctionComponent;
  /** Token-tinted line icon (not a full-color brand logo). */
  tint?: boolean;
}

const SOURCE_CHIPS: SourceChipSpec[] = [
  { x: 280, label: "Slack", icon: SvgSlack },
  { x: 390, label: "Drive", icon: SvgGoogleDrive },
  { x: 500, label: "Linear", icon: SvgLinear },
  { x: 610, label: "Gmail", icon: SvgGmail },
  { x: 720, label: "Your files", icon: SvgPaperclip, tint: true },
];

interface OutputCardSpec {
  y: number;
  label: string;
  caption: string;
  icon: IconFunctionComponent;
  /** Token-tinted line icon (not a full-color brand logo). */
  tint?: boolean;
}

const OUTPUT_CARD_KEYS = ["googleDoc", "liveApp", "githubPr"] as const;

const OUTPUT_CARD_LAYOUT: Record<
  (typeof OUTPUT_CARD_KEYS)[number],
  Omit<OutputCardSpec, "label" | "caption">
> = {
  googleDoc: { y: 170, icon: SvgGoogleDocs },
  liveApp: { y: 280, icon: SvgDashboard, tint: true },
  githubPr: { y: 390, icon: SvgGithub },
};

// ---------------------------------------------------------------------------
// Building blocks
// ---------------------------------------------------------------------------

function activateOnKeys(onSelect: () => void) {
  return (event: KeyboardEvent<HTMLDivElement>) => {
    if (event.key === "Enter" || event.key === " ") {
      event.preventDefault();
      onSelect();
    }
  };
}

interface MapNodeProps {
  x: number;
  y: number;
  sharp: boolean;
  label: string;
  reduceMotion: boolean;
  onSelect: () => void;
  children: ReactNode;
}

/**
 * A clickable node pinned to a world coordinate. Positioning lives on a plain
 * wrapper (motion owns `transform` on the inner element, so the centering
 * translate can't share it); focus/blur is animated on the inner layer.
 */
function MapNode({
  x,
  y,
  sharp,
  label,
  reduceMotion,
  onSelect,
  children,
}: MapNodeProps) {
  return (
    <div
      className="absolute -translate-x-1/2 -translate-y-1/2"
      style={{ left: leftPct(x), top: topPct(y) }}
    >
      <motion.div
        role="button"
        tabIndex={0}
        aria-label={label}
        initial={false}
        animate={{
          filter: sharp ? "blur(0px)" : "blur(5px)",
          opacity: sharp ? 1 : 0.45,
        }}
        transition={{ duration: reduceMotion ? 0 : 0.5 }}
        className="cursor-pointer outline-none"
        onClick={onSelect}
        onKeyDown={activateOnKeys(onSelect)}
      >
        {children}
      </motion.div>
    </div>
  );
}

interface EdgeLayerProps {
  sharpGroups: MapGroupId[];
  reduceMotion: boolean;
}

/** 1px token-colored connectors; in-focus edges carry traveling dots. */
function EdgeLayer({ sharpGroups, reduceMotion }: EdgeLayerProps) {
  return (
    <svg
      viewBox={`0 0 ${MAP_W} ${MAP_H}`}
      preserveAspectRatio="none"
      aria-hidden
      className="pointer-events-none absolute inset-0 h-full w-full"
    >
      {EDGES.map((edge) => {
        const active = sharpGroups.includes(edge.group);
        return (
          <g
            key={edge.id}
            className="transition-opacity duration-500"
            opacity={active ? 1 : 0.2}
          >
            <path
              d={edge.d}
              fill="none"
              strokeWidth={1}
              vectorEffect="non-scaling-stroke"
              stroke={active ? "var(--border-03)" : "var(--border-02)"}
              className="transition-colors duration-300"
            />
            {active && !reduceMotion && (
              <motion.path
                d={edge.d}
                fill="none"
                strokeWidth={3}
                strokeLinecap="round"
                strokeDasharray="1 59"
                stroke="var(--action-selection-05)"
                vectorEffect="non-scaling-stroke"
                animate={{ strokeDashoffset: [0, -60] }}
                transition={{ duration: 1.4, repeat: Infinity, ease: "linear" }}
              />
            )}
          </g>
        );
      })}
    </svg>
  );
}

// ---------------------------------------------------------------------------
// LivingMapDiagram
// ---------------------------------------------------------------------------

interface LivingMapDiagramProps {
  stage: LivingMapStageId;
  /** Runs the completion shot: the camera dives back into the prompt. */
  diving?: boolean;
  onSelectStage: (stage: LivingMapStageId) => void;
}

export default function LivingMapDiagram({
  stage,
  diving = false,
  onSelectStage,
}: LivingMapDiagramProps) {
  const t = useTranslations("craft.onboarding.livingMap");
  const reduceMotion = useReducedMotion() ?? false;

  const sharpGroups = STAGE_SHARP[stage];
  const camera = diving ? DIVE_CAMERA : STAGE_CAMERA[stage];

  // Screen offset that brings the camera center to the viewport center once
  // the world is scaled about its own center (translate % is of the unscaled
  // world box, applied post-scale).
  const scale = MAP_W / camera.w;
  const camX = `${-((camera.cx / MAP_W) * 100 - 50) * scale}%`;
  const camY = `${-((camera.cy / MAP_H) * 100 - 50) * scale}%`;

  const [visibleLines, setVisibleLines] = useState<number>(() =>
    stage === "prompt" && !reduceMotion ? 0 : TERMINAL_STEPS
  );
  const [promptIdx, setPromptIdx] = useState<number>(0);

  // The terminal types itself out when the machine comes into focus; the
  // interval retires itself once the last step is shown.
  useEffect(() => {
    if (stage !== "machine" || reduceMotion) {
      setVisibleLines(TERMINAL_STEPS);
      return undefined;
    }
    setVisibleLines(0);
    let shown = 0;
    const timer = setInterval(() => {
      shown += 1;
      setVisibleLines(shown);
      if (shown >= TERMINAL_STEPS) clearInterval(timer);
    }, 500);
    return () => clearInterval(timer);
  }, [stage, reduceMotion]);

  useEffect(() => {
    if (reduceMotion) return undefined;
    const timer = setInterval(() => {
      setPromptIdx((i) => (i + 1) % EXAMPLE_PROMPT_KEYS.length);
    }, PROMPT_ROTATION_MS);
    return () => clearInterval(timer);
  }, [reduceMotion]);

  function sharp(group: MapGroupId): boolean {
    return sharpGroups.includes(group);
  }

  function select(group: MapGroupId): () => void {
    return () => onSelectStage(GROUP_STAGE[group]);
  }

  const examplePrompt = t(`examplePrompts.${EXAMPLE_PROMPT_KEYS[promptIdx]!}`);

  return (
    <div
      className="relative w-full overflow-hidden rounded-12 border border-border-01 bg-background-tint-00"
      style={{ paddingTop: `${(MAP_H / MAP_W) * 100}%` }}
    >
      {/* The world: one fixed scene the camera moves through. */}
      <motion.div
        className="absolute inset-0"
        initial={false}
        animate={{
          scale,
          x: camX,
          y: camY,
          opacity: diving ? 0 : 1,
        }}
        transition={
          reduceMotion
            ? { duration: 0 }
            : (() => {
                // Stage moves settle with a long ease-out; the dive is a fast
                // accelerating shot that finishes inside the handoff window.
                const cameraEase = diving
                  ? { duration: 0.45, ease: [0.7, 0, 0.84, 0] as const }
                  : { duration: 0.8, ease: [0.16, 1, 0.3, 1] as const };
                return {
                  scale: cameraEase,
                  x: cameraEase,
                  y: cameraEase,
                  opacity: { duration: 0.3, delay: diving ? 0.15 : 0 },
                };
              })()
        }
      >
        <EdgeLayer sharpGroups={sharpGroups} reduceMotion={reduceMotion} />

        {/* Connected sources + uploaded files */}
        {SOURCE_CHIPS.map((source) => {
          const SourceIcon = source.icon;
          const isFilesChip = source.label === "Your files";
          const displayLabel = isFilesChip
            ? t("sources.yourFiles.label")
            : source.label;
          return (
            <MapNode
              key={source.label}
              x={source.x}
              y={48}
              sharp={sharp("sources")}
              label={
                isFilesChip
                  ? t("sources.yourFiles.ariaLabel")
                  : t("sources.connectedAriaLabel", { name: source.label })
              }
              reduceMotion={reduceMotion}
              onSelect={select("sources")}
            >
              <div className="flex items-center gap-1.5 rounded-08 border border-border-01 bg-background-tint-00 px-3 py-1.5">
                <SourceIcon
                  className={cn("h-3.5 w-3.5", source.tint && "stroke-text-04")}
                />
                <Text
                  font="secondary-action"
                  color="text-04"
                  wordWrap="whitespace-nowrap"
                >
                  {displayLabel}
                </Text>
              </div>
            </MapNode>
          );
        })}

        {/* Your prompt */}
        <MapNode
          x={130}
          y={280}
          sharp={sharp("prompt")}
          label={t("prompt.label")}
          reduceMotion={reduceMotion}
          onSelect={select("prompt")}
        >
          <div className="flex w-[200px] flex-col gap-1.5 rounded-12 border border-border-01 bg-background-tint-00 p-3 shadow-sm">
            <div className="flex items-center gap-1.5">
              <SvgBubbleText className="h-3.5 w-3.5 stroke-text-04" />
              <Text
                font="secondary-action"
                color="text-04"
                wordWrap="whitespace-nowrap"
              >
                {t("prompt.label")}
              </Text>
            </div>
            <div className="relative h-16 w-full">
              <AnimatePresence initial={false}>
                <motion.div
                  key={examplePrompt}
                  initial={reduceMotion ? false : { opacity: 0 }}
                  animate={{ opacity: 1 }}
                  // Incoming fades faster than the outgoing leaves, so the
                  // card always shows a prompt — no blank dip mid-crossfade.
                  exit={
                    reduceMotion
                      ? undefined
                      : { opacity: 0, transition: { duration: 0.4 } }
                  }
                  transition={{ duration: 0.25 }}
                  className="absolute inset-0 flex"
                >
                  <Text font="secondary-body" color="text-03">
                    {examplePrompt}
                  </Text>
                </motion.div>
              </AnimatePresence>
            </div>
          </div>
        </MapNode>

        {/* Craft's workspace — its own machine */}
        <div
          className="absolute"
          style={{
            left: leftPct(330),
            top: topPct(170),
            width: leftPct(290),
            height: topPct(190),
          }}
        >
          <motion.div
            role="button"
            tabIndex={0}
            aria-label={t("workspace.label")}
            initial={false}
            animate={{
              filter: sharp("workspace") ? "blur(0px)" : "blur(5px)",
              opacity: sharp("workspace") ? 1 : 0.45,
            }}
            transition={{ duration: reduceMotion ? 0 : 0.5 }}
            className="h-full w-full cursor-pointer outline-none"
            onClick={select("workspace")}
            onKeyDown={activateOnKeys(select("workspace"))}
          >
            <CometEdge
              active={sharp("workspace") && !reduceMotion && !diving}
              radius={12}
              speedSeconds={4}
              className="flex h-full w-full flex-col rounded-12 border border-border-01 bg-background-tint-00 shadow-sm"
            >
              <div className="flex items-center justify-between px-3 py-2">
                <div className="flex items-center gap-1.5">
                  <SvgCpu className="h-3.5 w-3.5 stroke-text-04" />
                  <Text
                    font="secondary-action"
                    color="text-04"
                    wordWrap="whitespace-nowrap"
                  >
                    {t("workspace.label")}
                  </Text>
                </div>
                <div className="flex items-center gap-1">
                  <SvgShield className="h-3 w-3 stroke-text-03" />
                  <Text
                    font="figure-small-label"
                    color="text-03"
                    wordWrap="whitespace-nowrap"
                  >
                    {t("workspace.sandboxBadge")}
                  </Text>
                </div>
              </div>

              {/* Terminal — dark so "its own machine" is legible at a glance */}
              <div className="min-h-0 flex-1 px-3">
                <div className="flex h-full flex-col gap-1 overflow-hidden rounded-08 bg-background-neutral-inverted-00 p-2.5">
                  {TERMINAL_LINES.slice(0, visibleLines).map((line) => (
                    <motion.div
                      key={line}
                      initial={reduceMotion ? false : { opacity: 0, y: 2 }}
                      animate={{ opacity: 1, y: 0 }}
                      transition={{ duration: 0.25 }}
                    >
                      <Text
                        font="secondary-mono"
                        color="text-inverted-03"
                        wordWrap="whitespace-nowrap"
                      >
                        {line}
                      </Text>
                    </motion.div>
                  ))}
                </div>
              </div>

              {/* Approval pill — actions gate on you */}
              <div className="flex items-center px-3 py-2">
                <motion.div
                  initial={reduceMotion ? false : { opacity: 0, y: 2 }}
                  animate={{
                    opacity: visibleLines >= TERMINAL_STEPS ? 1 : 0,
                    y: 0,
                  }}
                  transition={{ duration: 0.25 }}
                  className="flex items-center gap-1.5 rounded-08 border-[0.5px] border-border-01 bg-background-neutral-01 px-2 py-1"
                >
                  <SvgAlertCircle className="h-3 w-3 shrink-0 stroke-text-04" />
                  <Text
                    font="figure-small-label"
                    color="text-04"
                    wordWrap="whitespace-nowrap"
                  >
                    {t("workspace.approvalPill")}
                  </Text>
                </motion.div>
              </div>
            </CometEdge>
          </motion.div>
        </div>

        {/* The outputs */}
        {OUTPUT_CARD_KEYS.map((cardKey) => {
          const layout = OUTPUT_CARD_LAYOUT[cardKey];
          const OutputIcon = layout.icon;
          const output = {
            ...layout,
            label: t(`outputs.${cardKey}.label`),
            caption: t(`outputs.${cardKey}.caption`),
          };
          return (
            <MapNode
              key={cardKey}
              x={740}
              y={output.y}
              sharp={sharp("outputs")}
              label={t("outputs.ariaLabel", { name: output.label })}
              reduceMotion={reduceMotion}
              onSelect={select("outputs")}
            >
              <div className="flex w-[170px] flex-col gap-1 rounded-12 border border-border-01 bg-background-tint-00 p-3">
                <div className="flex items-center gap-1.5">
                  <OutputIcon
                    className={cn(
                      "h-3.5 w-3.5 shrink-0",
                      output.tint && "stroke-text-05"
                    )}
                  />
                  <Text
                    font="secondary-action"
                    color="text-04"
                    wordWrap="whitespace-nowrap"
                  >
                    {output.label}
                  </Text>
                </div>
                <Text
                  font="figure-small-label"
                  color="text-03"
                  wordWrap="whitespace-nowrap"
                >
                  {output.caption}
                </Text>
              </div>
            </MapNode>
          );
        })}

        {/* The schedule — re-runs the prompt on a timer */}
        <MapNode
          x={320}
          y={495}
          sharp={sharp("schedule")}
          label={t("schedule.ariaLabel")}
          reduceMotion={reduceMotion}
          onSelect={select("schedule")}
        >
          <div className="flex flex-col gap-0.5 rounded-12 border border-border-01 bg-background-tint-00 px-3 py-2">
            <div className="flex items-center gap-1.5">
              <SvgClock className="h-3.5 w-3.5 stroke-text-04" />
              <Text
                font="secondary-action"
                color="text-04"
                wordWrap="whitespace-nowrap"
              >
                {t("schedule.label")}
              </Text>
            </div>
            <Text
              font="figure-small-label"
              color="text-03"
              wordWrap="whitespace-nowrap"
            >
              {t("schedule.caption")}
            </Text>
          </div>
        </MapNode>

        {/* Your team */}
        <MapNode
          x={760}
          y={500}
          sharp={sharp("team")}
          label={t("team.ariaLabel")}
          reduceMotion={reduceMotion}
          onSelect={select("team")}
        >
          <div className="flex flex-col gap-0.5 rounded-12 border border-border-01 bg-background-tint-00 px-3 py-2">
            <div className="flex items-center gap-1.5">
              <SvgUsers className="h-3.5 w-3.5 stroke-text-04" />
              <Text
                font="secondary-action"
                color="text-04"
                wordWrap="whitespace-nowrap"
              >
                {t("team.label")}
              </Text>
            </div>
            <Text
              font="figure-small-label"
              color="text-03"
              wordWrap="whitespace-nowrap"
            >
              {t("team.caption")}
            </Text>
          </div>
        </MapNode>
      </motion.div>
    </div>
  );
}
