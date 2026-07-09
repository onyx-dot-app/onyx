"use client";

import { useEffect, useState } from "react";
import type { KeyboardEvent, ReactNode } from "react";
import { AnimatePresence, motion, useReducedMotion } from "motion/react";
import { Divider, Text } from "@opal/components";
import {
  SvgBlocks,
  SvgBookOpen,
  SvgAlertCircle,
  SvgBranch,
  SvgBubbleText,
  SvgClock,
  SvgCpu,
  SvgDashboard,
  SvgDocFile,
  SvgFolder,
  SvgMail,
  SvgPaperclip,
  SvgPlug,
  SvgShield,
  SvgSlack,
  SvgSlidesFile,
  SvgSparkle,
  SvgSpreadsheetFile,
  SvgUsers,
} from "@opal/icons";
import type { IconFunctionComponent } from "@opal/types";
import { cn } from "@opal/utils";
import CometEdge from "@/app/craft/components/CometEdge";

// ---------------------------------------------------------------------------
// The Living Map diagram — the whole Craft ecosystem on one map. The core
// loop (prompt → Craft in its workspace reading your sources → output) sits in
// the center band; the ecosystem (apps, skills, scheduled tasks, team sharing)
// attaches to it one stage at a time, ending on the complete constellation.
// Nodes and edges share one design space so layers stay aligned at any width.
// ---------------------------------------------------------------------------

const MAP_W = 900;
const MAP_H = 560;
// Height shown before any ecosystem card exists — the canvas grows to MAP_H
// once the bottom row starts filling in, instead of reserving empty space.
const CORE_H = 400;

function leftPct(x: number): string {
  return `${(x / MAP_W) * 100}%`;
}

function topPct(y: number): string {
  return `${(y / MAP_H) * 100}%`;
}

export type LivingMapStageId =
  | "loop"
  | "share"
  | "schedule"
  | "skills"
  | "apps"
  | "workshop";

export interface LivingMapStage {
  id: LivingMapStageId;
  description: string;
}

export const LIVING_MAP_STAGES: LivingMapStage[] = [
  {
    id: "loop",
    description:
      "Give Craft a task and it works on its own machine, reading your connected sources and handing back something real.",
  },
  {
    id: "apps",
    description:
      "It acts where you already work: Gmail, Slack, Linear, Drive. Nothing goes out without your approval.",
  },
  {
    id: "skills",
    description:
      "Skills carry your team's playbooks: templates, formats, house style. Craft follows them wherever they apply.",
  },
  {
    id: "schedule",
    description:
      "Anything you can ask for once, you can put on a schedule. Craft runs it fresh each time, even with your laptop closed.",
  },
  {
    id: "share",
    description:
      "Finished work is easy to share. Hosted apps go out with one link; docs, drafts, and PRs are already where you work.",
  },
  {
    id: "workshop",
    description:
      "That's Craft: it sees what you see and acts where you work. Click any part of the map to revisit it.",
  },
];

const STAGE_IDS: LivingMapStageId[] = LIVING_MAP_STAGES.map(
  (stage) => stage.id
);

type MapNodeId =
  | "prompt"
  | "slack"
  | "drive"
  | "linear"
  | "confluence"
  | "files"
  | "sandbox"
  | "artifact"
  | "team"
  | "schedule"
  | "skills"
  | "apps";

type MapEdgeId =
  | "prompt"
  | "slack"
  | "drive"
  | "linear"
  | "confluence"
  | "files"
  | "ship"
  | "team"
  | "schedule"
  | "skills"
  | "apps";

const ALL_NODES: MapNodeId[] = [
  "prompt",
  "slack",
  "drive",
  "linear",
  "confluence",
  "files",
  "sandbox",
  "artifact",
  "team",
  "schedule",
  "skills",
  "apps",
];

const ALL_EDGES: MapEdgeId[] = [
  "prompt",
  "slack",
  "drive",
  "linear",
  "confluence",
  "files",
  "ship",
  "team",
  "schedule",
  "skills",
  "apps",
];

/** Stage index at which each node joins the map (cumulative reveal). */
const NODE_INTRO: Record<MapNodeId, number> = {
  prompt: 0,
  slack: 0,
  drive: 0,
  linear: 0,
  confluence: 0,
  files: 0,
  sandbox: 0,
  artifact: 0,
  apps: 1,
  skills: 2,
  schedule: 3,
  team: 4,
};

const EDGE_INTRO: Record<MapEdgeId, number> = {
  prompt: 0,
  slack: 0,
  drive: 0,
  linear: 0,
  confluence: 0,
  files: 0,
  ship: 0,
  apps: 1,
  skills: 2,
  schedule: 3,
  team: 4,
};

const CORE_NODES: MapNodeId[] = [
  "prompt",
  "slack",
  "drive",
  "linear",
  "confluence",
  "files",
  "sandbox",
  "artifact",
];

const CORE_EDGES: MapEdgeId[] = [
  "prompt",
  "slack",
  "drive",
  "linear",
  "confluence",
  "files",
  "ship",
];

const STAGE_ACTIVE_NODES: Record<LivingMapStageId, MapNodeId[]> = {
  loop: CORE_NODES,
  share: ["artifact", "team"],
  schedule: ["schedule", "prompt"],
  skills: ["skills", "sandbox"],
  apps: ["apps", "sandbox"],
  workshop: ALL_NODES,
};

const STAGE_ACTIVE_EDGES: Record<LivingMapStageId, MapEdgeId[]> = {
  loop: CORE_EDGES,
  share: ["team"],
  schedule: ["schedule", "prompt"],
  skills: ["skills"],
  apps: ["apps"],
  workshop: ALL_EDGES,
};

/** Which tour stage a click on each map node jumps to. */
const NODE_STAGE: Record<MapNodeId, LivingMapStageId> = {
  prompt: "loop",
  slack: "loop",
  drive: "loop",
  linear: "loop",
  confluence: "loop",
  files: "loop",
  sandbox: "loop",
  artifact: "share",
  team: "share",
  schedule: "schedule",
  skills: "skills",
  apps: "apps",
};

interface MapEdge {
  id: MapEdgeId;
  d: string;
}

const EDGES: MapEdge[] = [
  { id: "prompt", d: "M 185 220 C 225 220, 250 220, 288 220" },
  { id: "slack", d: "M 245 58 C 245 86, 300 96, 340 108" },
  { id: "drive", d: "M 355 58 C 355 84, 385 94, 405 108" },
  { id: "linear", d: "M 460 58 C 460 84, 460 94, 460 108" },
  { id: "confluence", d: "M 570 58 C 570 84, 540 94, 520 108" },
  { id: "files", d: "M 685 58 C 685 86, 625 96, 585 108" },
  { id: "ship", d: "M 632 220 C 668 220, 696 220, 733 220" },
  { id: "schedule", d: "M 105 448 C 105 400, 105 320, 105 268" },
  { id: "apps", d: "M 350 448 C 350 420, 350 392, 350 362" },
  { id: "skills", d: "M 570 448 C 570 420, 570 392, 570 362" },
  { id: "team", d: "M 815 272 C 815 320, 815 400, 815 448" },
];

interface SourceChipSpec {
  id: MapNodeId;
  x: number;
  label: string;
  icon: IconFunctionComponent;
}

const SOURCE_CHIPS: SourceChipSpec[] = [
  { id: "slack", x: 245, label: "Slack", icon: SvgSlack },
  { id: "drive", x: 355, label: "Drive", icon: SvgFolder },
  { id: "linear", x: 460, label: "Linear", icon: SvgBranch },
  { id: "confluence", x: 570, label: "Confluence", icon: SvgBookOpen },
  { id: "files", x: 685, label: "Your files", icon: SvgPaperclip },
];

const TERMINAL_LINES: string[] = [
  '$ onyx-cli search "q2 vendor invoices"',
  "$ python analyze_spend.py",
  '$ skill run drive-doc "Q2 spend summary"',
];

// Typed lines plus the trailing approval pill.
const TERMINAL_STEPS = TERMINAL_LINES.length + 1;

interface OutputForm {
  label: string;
  icon: IconFunctionComponent;
  caption: string;
}

// Prompts and output forms cycle in anti-phase, so no single use case or
// output reads as the flagship. Index 0 of each matches the terminal's
// vendor-spend story for the reduced-motion static frame.
const EXAMPLE_PROMPTS: string[] = [
  "“Summarize our Q2 vendor spend as a doc in Drive.”",
  "“Draft the parental-leave update as a Google Doc.”",
  "“Condense our Slack discussion into tickets and assign to the team.”",
  "“Reconcile this billing CSV against our HubSpot deals.”",
  "“Build the spring launch deck from the brief in Drive. Use our template.”",
  "“Fix the flaky retry test and open a PR.”",
  "“Fill out the RFP in my email with our security details.”",
];

const OUTPUT_FORMS: OutputForm[] = [
  { label: "Google Doc", icon: SvgDocFile, caption: "Written to your Drive" },
  {
    label: "Live dashboard",
    icon: SvgDashboard,
    caption: "Hosted and shared with your team",
  },
  { label: "Gmail drafts", icon: SvgMail, caption: "Ready to send" },
  {
    label: "Excel workbook",
    icon: SvgSpreadsheetFile,
    caption: "Ready to download",
  },
  { label: "Slide deck", icon: SvgSlidesFile, caption: "Using your template" },
  { label: "GitHub PR", icon: SvgBranch, caption: "Open for review" },
];

// Shared cycle time for the prompt and output rotations (anti-phase).
const ROTATION_MS = 5000;

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

interface RotatingProps {
  /** Content identity — changing it crossfades to the new content. */
  itemKey: string;
  reduceMotion: boolean;
  className?: string;
  children: ReactNode;
}

/**
 * Crossfades children inside an absolutely-filled box when itemKey changes.
 * The flex container also block-ifies inline Text spans so each preset's own
 * line-height applies instead of the wrapper's strut.
 */
function Rotating({
  itemKey,
  reduceMotion,
  className,
  children,
}: RotatingProps) {
  return (
    <AnimatePresence initial={false}>
      <motion.div
        key={itemKey}
        initial={reduceMotion ? false : { opacity: 0 }}
        animate={{ opacity: 1 }}
        exit={reduceMotion ? undefined : { opacity: 0 }}
        transition={{ duration: 0.4 }}
        className={cn("absolute inset-0 flex", className)}
      >
        {children}
      </motion.div>
    </AnimatePresence>
  );
}

interface MapNodeProps {
  x: number;
  y: number;
  active: boolean;
  label: string;
  reduceMotion: boolean;
  onSelect: () => void;
  children: ReactNode;
}

/** A clickable node pinned to a design-space coordinate, animating in on mount. */
function MapNode({
  x,
  y,
  active,
  label,
  reduceMotion,
  onSelect,
  children,
}: MapNodeProps) {
  return (
    <motion.div
      role="button"
      tabIndex={0}
      aria-label={label}
      initial={reduceMotion ? false : { opacity: 0, scale: 0.92 }}
      animate={{ opacity: active ? 1 : 0.5, scale: 1 }}
      transition={{ duration: 0.3 }}
      className="absolute -translate-x-1/2 -translate-y-1/2 cursor-pointer outline-none"
      style={{ left: leftPct(x), top: topPct(y) }}
      onClick={onSelect}
      onKeyDown={activateOnKeys(onSelect)}
    >
      {children}
    </motion.div>
  );
}

interface EcosystemCardProps {
  icon: IconFunctionComponent;
  label: string;
  body: string;
  footer?: ReactNode;
}

/** Compact card for ecosystem nodes — visually secondary to the core loop. */
function EcosystemCard({
  icon: Icon,
  label,
  body,
  footer,
}: EcosystemCardProps) {
  return (
    <div className="flex w-40 flex-col gap-1 rounded-12 border border-border-01 bg-background-tint-00 p-3">
      <div className="flex items-center gap-1.5">
        <Icon className="h-3.5 w-3.5 stroke-text-04" />
        <Text font="secondary-action" color="text-04" nowrap>
          {label}
        </Text>
      </div>
      <Text font="secondary-body" color="text-03">
        {body}
      </Text>
      {footer}
    </div>
  );
}

interface EdgeLayerProps {
  visibleEdges: MapEdgeId[];
  activeEdges: MapEdgeId[];
  reduceMotion: boolean;
}

/** 1px token-colored connectors, with subtle traveling dots when active. */
function EdgeLayer({
  visibleEdges,
  activeEdges,
  reduceMotion,
}: EdgeLayerProps) {
  return (
    <svg
      viewBox={`0 0 ${MAP_W} ${MAP_H}`}
      preserveAspectRatio="none"
      aria-hidden
      className="pointer-events-none absolute inset-0 h-full w-full"
    >
      {EDGES.filter((edge) => visibleEdges.includes(edge.id)).map((edge) => {
        const active = activeEdges.includes(edge.id);
        return (
          <g key={edge.id}>
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
                strokeDasharray="1 23"
                stroke="var(--action-link-05)"
                vectorEffect="non-scaling-stroke"
                animate={{ strokeDashoffset: [0, -24] }}
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
  onSelectStage: (stage: LivingMapStageId) => void;
}

export default function LivingMapDiagram({
  stage,
  onSelectStage,
}: LivingMapDiagramProps) {
  const reduceMotion = useReducedMotion() ?? false;

  const stageIdx = STAGE_IDS.indexOf(stage);
  const activeNodes = STAGE_ACTIVE_NODES[stage];
  const activeEdges = STAGE_ACTIVE_EDGES[stage];

  const visibleEdges = ALL_EDGES.filter((id) => EDGE_INTRO[id] <= stageIdx);

  const [visibleLines, setVisibleLines] = useState<number>(() =>
    stage !== "loop" || reduceMotion ? TERMINAL_STEPS : 0
  );
  const [promptIdx, setPromptIdx] = useState<number>(0);
  const [outputIdx, setOutputIdx] = useState<number>(0);

  // Terminal types itself out while the core-loop stage is in focus; the
  // interval retires itself once the last step is shown.
  useEffect(() => {
    if (stage !== "loop" || reduceMotion) {
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

  // One clock drives both rotations: every half-period tick advances one
  // side, alternating (output on odd ticks, prompt on even), so each changes
  // exactly mid-way through the other's static time — anti-phase by
  // construction, with no way for separate timers to drift apart.
  useEffect(() => {
    if (reduceMotion) return undefined;
    let tick = 0;
    const timer = setInterval(() => {
      tick += 1;
      if (tick % 2 === 1) {
        setOutputIdx((i) => (i + 1) % OUTPUT_FORMS.length);
      } else {
        setPromptIdx((i) => (i + 1) % EXAMPLE_PROMPTS.length);
      }
    }, ROTATION_MS / 2);
    return () => clearInterval(timer);
  }, [reduceMotion]);

  function nodeVisible(id: MapNodeId): boolean {
    return NODE_INTRO[id] <= stageIdx;
  }

  function nodeActive(id: MapNodeId): boolean {
    return activeNodes.includes(id);
  }

  const sandboxActive = nodeActive("sandbox");
  const examplePrompt = EXAMPLE_PROMPTS[promptIdx]!;
  const outputForm = OUTPUT_FORMS[outputIdx]!;
  const OutputIcon = outputForm.icon;

  // Crop the canvas to the core loop until the ecosystem row exists; the
  // percentage padding keeps height proportional to width, so the band
  // reveals smoothly as the tour advances.
  const cropH = stageIdx === 0 ? CORE_H : MAP_H;

  return (
    <div
      className="relative w-full overflow-hidden transition-[padding-top] duration-500 ease-in-out"
      style={{ paddingTop: `${(cropH / MAP_W) * 100}%` }}
    >
      <div
        className="absolute left-0 top-0 w-full"
        style={{ aspectRatio: `${MAP_W} / ${MAP_H}` }}
      >
        <EdgeLayer
          visibleEdges={visibleEdges}
          activeEdges={activeEdges}
          reduceMotion={reduceMotion}
        />

        {/* Caption over the sources row */}
        <div
          className="pointer-events-none absolute -translate-x-1/2 -translate-y-1/2"
          style={{ left: leftPct(465), top: topPct(10) }}
        >
          <Text font="figure-small-label" color="text-03" nowrap>
            It sees what you see
          </Text>
        </div>

        {/* Connected sources + uploaded files */}
        {SOURCE_CHIPS.map((source) => {
          const SourceIcon = source.icon;
          return (
            <MapNode
              key={source.id}
              x={source.x}
              y={40}
              active={nodeActive(source.id)}
              label={
                source.id === "files"
                  ? "Your uploaded files"
                  : `Connected source: ${source.label}`
              }
              reduceMotion={reduceMotion}
              onSelect={() => onSelectStage(NODE_STAGE[source.id])}
            >
              <div className="flex items-center gap-1.5 rounded-08 border border-border-01 bg-background-tint-00 px-3 py-1.5">
                <SourceIcon className="h-3.5 w-3.5 stroke-text-04" />
                <Text font="secondary-action" color="text-04" nowrap>
                  {source.label}
                </Text>
              </div>
            </MapNode>
          );
        })}

        {/* Your prompt */}
        <MapNode
          x={105}
          y={220}
          active={nodeActive("prompt")}
          label="Your prompt"
          reduceMotion={reduceMotion}
          onSelect={() => onSelectStage(NODE_STAGE.prompt)}
        >
          <div
            className={cn(
              "flex w-40 flex-col gap-1 rounded-12 border border-border-01 bg-background-tint-00 p-3"
            )}
          >
            <div className="flex items-center gap-1.5">
              <SvgBubbleText className="h-3.5 w-3.5 stroke-text-04" />
              <Text font="secondary-action" color="text-04" nowrap>
                Your prompt
              </Text>
            </div>
            <div className="relative h-20 w-full">
              <Rotating itemKey={examplePrompt} reduceMotion={reduceMotion}>
                <Text font="secondary-body" color="text-03">
                  {examplePrompt}
                </Text>
              </Rotating>
            </div>
          </div>
        </MapNode>

        {/* Craft's workspace — its own machine */}
        <div
          role="button"
          tabIndex={0}
          aria-label="Craft's workspace"
          className={cn(
            "absolute cursor-pointer outline-none transition-opacity duration-300",
            sandboxActive ? "opacity-100" : "opacity-50"
          )}
          style={{
            left: leftPct(290),
            top: topPct(110),
            width: leftPct(340),
            height: topPct(250),
          }}
          onClick={() => onSelectStage(NODE_STAGE.sandbox)}
          onKeyDown={activateOnKeys(() => onSelectStage(NODE_STAGE.sandbox))}
        >
          <CometEdge
            active={!reduceMotion}
            radius={12}
            speedSeconds={4}
            className="flex h-full w-full flex-col rounded-12 border border-border-01 bg-background-tint-00"
          >
            <div className="flex items-center justify-between px-3 py-2">
              <div className="flex items-center gap-1.5">
                <SvgCpu className="h-3.5 w-3.5 stroke-text-04" />
                <Text font="secondary-action" color="text-04" nowrap>
                  Craft&apos;s workspace
                </Text>
              </div>
              <div className="flex items-center gap-1">
                <SvgShield className="h-3 w-3 stroke-text-03" />
                <Text font="figure-small-label" color="text-03" nowrap>
                  Its own machine
                </Text>
              </div>
            </div>
            <Divider />

            {/* The agent, at work inside */}
            <div className="flex items-center gap-2 px-3 pt-2">
              <div className="flex h-9 w-9 shrink-0 items-center justify-center rounded-full border border-border-01 bg-background-tint-01">
                <SvgSparkle className="h-4 w-4 stroke-text-05" />
              </div>
              <div className="flex flex-col">
                <Text font="secondary-action" color="text-04" nowrap>
                  Craft
                </Text>
                <Text font="secondary-body" color="text-03">
                  Reads as you, acts with approval, and never accesses secrets
                </Text>
              </div>
            </div>

            {/* Terminal */}
            <div className="min-h-0 flex-1 px-3 py-2">
              <div className="flex h-full flex-col gap-0.5 overflow-hidden rounded-08 border border-border-01 bg-background-tint-01 p-2">
                {TERMINAL_LINES.slice(0, visibleLines).map((line) => (
                  <motion.div
                    key={line}
                    initial={reduceMotion ? false : { opacity: 0, y: 2 }}
                    animate={{ opacity: 1, y: 0 }}
                    transition={{ duration: 0.25 }}
                  >
                    <Text font="secondary-mono" color="text-03" nowrap>
                      {line}
                    </Text>
                  </motion.div>
                ))}
                {visibleLines >= TERMINAL_STEPS && (
                  <motion.div
                    initial={reduceMotion ? false : { opacity: 0, y: 2 }}
                    animate={{ opacity: 1, y: 0 }}
                    transition={{ duration: 0.25 }}
                    className="flex items-center gap-1.5 self-stretch rounded-08 border-[0.5px] border-border-01 bg-background-neutral-01 px-2 py-1"
                  >
                    <SvgAlertCircle className="h-3 w-3 shrink-0 stroke-text-04" />
                    <Text font="figure-small-label" color="text-04" nowrap>
                      Waiting for your approval
                    </Text>
                  </motion.div>
                )}
              </div>
            </div>
          </CometEdge>
        </div>

        {/* The output */}
        <MapNode
          x={815}
          y={220}
          active={nodeActive("artifact")}
          label="The output"
          reduceMotion={reduceMotion}
          onSelect={() => onSelectStage(NODE_STAGE.artifact)}
        >
          <div
            className={cn(
              "flex w-40 flex-col items-center gap-1 rounded-12 border border-border-01 bg-background-tint-00 p-3"
            )}
          >
            <div className="relative h-[4.75rem] w-full">
              <Rotating
                itemKey={outputForm.label}
                reduceMotion={reduceMotion}
                className="flex flex-col items-center gap-1 text-center"
              >
                <OutputIcon className="h-6 w-6 shrink-0 stroke-text-05" />
                <Text font="secondary-action" color="text-04" nowrap>
                  {outputForm.label}
                </Text>
                <Text font="figure-small-label" color="text-03">
                  {outputForm.caption}
                </Text>
              </Rotating>
            </div>
          </div>
        </MapNode>

        {/* Ecosystem — attaches to the loop one stage at a time */}
        {nodeVisible("schedule") && (
          <MapNode
            active={nodeActive("schedule")}
            x={105}
            y={480}
            label="Scheduled task — re-runs this prompt on a timer"
            reduceMotion={reduceMotion}
            onSelect={() => onSelectStage(NODE_STAGE.schedule)}
          >
            <EcosystemCard
              icon={SvgClock}
              label="Scheduled task"
              body="Re-runs this prompt every Monday, 8:00"
              footer={
                <Text font="figure-small-label" color="text-03" nowrap>
                  Runs while you&apos;re away
                </Text>
              }
            />
          </MapNode>
        )}

        {nodeVisible("skills") && (
          <MapNode
            active={nodeActive("skills")}
            x={570}
            y={480}
            label="Skills — your team's playbooks for Craft"
            reduceMotion={reduceMotion}
            onSelect={() => onSelectStage(NODE_STAGE.skills)}
          >
            <EcosystemCard
              icon={SvgBlocks}
              label="Skills"
              body="Standardize your agents' work"
              footer={
                <Text font="secondary-mono" color="text-03" nowrap>
                  brand-guidelines
                </Text>
              }
            />
          </MapNode>
        )}

        {nodeVisible("apps") && (
          <MapNode
            active={nodeActive("apps")}
            x={350}
            y={480}
            label="Apps — tools Craft acts in, with your approval"
            reduceMotion={reduceMotion}
            onSelect={() => onSelectStage(NODE_STAGE.apps)}
          >
            <EcosystemCard
              icon={SvgPlug}
              label="Apps"
              body="Acts in Gmail, Slack, GitHub & more with your approval"
            />
          </MapNode>
        )}

        {nodeVisible("team") && (
          <MapNode
            active={nodeActive("team")}
            x={815}
            y={480}
            label="Your team — easily share Craft's work"
            reduceMotion={reduceMotion}
            onSelect={() => onSelectStage(NODE_STAGE.team)}
          >
            <EcosystemCard
              icon={SvgUsers}
              label="Your team"
              body="Easily share Craft's work with your team"
              footer={
                <Text font="figure-small-label" color="text-03" nowrap>
                  A hosted app, a doc, a PR
                </Text>
              }
            />
          </MapNode>
        )}
      </div>
    </div>
  );
}
