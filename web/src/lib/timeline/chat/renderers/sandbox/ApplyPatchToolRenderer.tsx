import { type ComponentProps, useMemo } from "react";
import { useTranslations } from "next-intl";
import { codeSpan, markdown, stripBidiControls } from "@opal/utils";
import { STEP_ICONS } from "@/lib/timeline/icons";
import {
  ApplyPatchEnd,
  ApplyPatchFileChange,
  ApplyPatchStart,
  ApplyPatchToolPacket,
  FileToolProgress,
  PacketType,
} from "@/app/app/services/streamingModels";
import { MessageRenderer } from "@/lib/timeline/chat/message/messageComponents/types";
import { SandboxCallContent } from "@/lib/timeline/chat/renderers/sandbox/sandboxCall";
import { CommandBody } from "@/lib/timeline/components/bodies/CommandBody";
import { DiffBody } from "@/lib/timeline/components/bodies/DiffBody";
import { DiffStat } from "@/lib/timeline/components/bodies/DiffStat";
import { parseApplyPatch } from "@/lib/timeline/components/bodies/diffLines";
import { useSandboxCallStatus } from "@/lib/sandbox/hooks";

// git-style status letters for the changed files
const CHANGE_MARKERS = {
  add: "A",
  update: "M",
  delete: "D",
} satisfies Record<ApplyPatchFileChange["change"], string>;

type ApplyPatchToolRendererProps = ComponentProps<
  MessageRenderer<ApplyPatchToolPacket, {}>
>;

/** One apply_patch call: the files it changed and the patch it applied. */
export function ApplyPatchToolRenderer({
  packets,
  onComplete,
  renderType,
  stopPacketSeen,
  children,
}: ApplyPatchToolRendererProps) {
  const t = useTranslations("chat.messages.timeline");
  const { start, end, progress } = useMemo(() => {
    let start: ApplyPatchStart | null = null;
    let end: ApplyPatchEnd | null = null;
    let progress: FileToolProgress | null = null;
    for (const { obj } of packets) {
      if (obj.type === PacketType.APPLY_PATCH_START) {
        start = obj;
      } else if (obj.type === PacketType.APPLY_PATCH_END) {
        end = obj;
      } else if (obj.type === PacketType.FILE_TOOL_PROGRESS) {
        progress = obj;
      }
    }
    return { start, end, progress };
  }, [packets]);
  const tRead = useTranslations("craft.toolCards.read");
  const patch = start?.patch ?? "";
  const patchFiles = useMemo(
    () =>
      patch === ""
        ? []
        : parseApplyPatch(patch, (count) =>
            tRead("moreLines.label", { count })
          ),
    [patch, tRead]
  );
  const totals = patchFiles.reduce(
    (sum, file) => ({
      added: sum.added + file.added,
      removed: sum.removed + file.removed,
    }),
    { added: 0, removed: 0 }
  );
  const { isComplete, error, stopped } = useSandboxCallStatus(
    packets,
    end,
    stopPacketSeen,
    onComplete
  );

  // The collapsed view gets one line more than it shows, so it detects the
  // cut, and never lays out the whole patch. That line is never blank: a
  // blank last line would render as nothing and hide the cut.
  // While the model writes the arguments, their progress names the step; the
  // start packet replaces it with the card that replay shows. A call that
  // ends without a start shows only how it ended.
  const liveProgress = start !== null || isComplete ? null : progress;
  const [progressPath] = liveProgress?.paths ?? [];
  const pathCode =
    progressPath === undefined
      ? null
      : codeSpan(stripBidiControls(progressPath));

  const status = stopped
    ? t("sandbox.stopped.status")
    : error !== null
      ? t("sandbox.patch.failed.status")
      : end !== null
        ? t("sandbox.patch.edited.status", { count: end.files.length })
        : liveProgress === null
          ? t("header.editingFiles.label")
          : liveProgress.tool_name === "apply_patch"
            ? t("sandbox.patch.progress.patching.status", {
                count: liveProgress.paths.length,
              })
            : pathCode === null
              ? t("sandbox.patch.progress.unnamed.status", {
                  tool: liveProgress.tool_name,
                })
              : markdown(
                  t("sandbox.patch.progress.named.status", {
                    tool: liveProgress.tool_name,
                    path: pathCode,
                  })
                );

  // The changed files, once the patch applied: a change marker (A, M or D)
  // and the path, with its new path when it moved.
  const changedFiles =
    end !== null && error === null
      ? end.files
          .map(
            (file) =>
              `${CHANGE_MARKERS[file.change]} ${stripBidiControls(file.path)}${
                file.move_path !== null
                  ? ` → ${stripBidiControls(file.move_path)}`
                  : ""
              }`
          )
          .join("\n")
      : "";

  // One panel: each file's diff, then the output band, which waits with a
  // loading shimmer while the patch applies, then lists the changed files or
  // shows the error.
  const content = (
    <SandboxCallContent renderType={renderType}>
      {patchFiles.map((file, index) => (
        <DiffBody
          key={index}
          title={stripBidiControls(file.path) || t("sandbox.patch.title")}
          copyText={index === 0 ? patch : undefined}
          lines={file.lines}
        />
      ))}
      <CommandBody
        command=""
        output={changedFiles}
        error={error ?? undefined}
        outputLoading={!isComplete}
        emptyLabel=""
      />
    </SandboxCallContent>
  );

  return children([
    {
      icon: STEP_ICONS.edit,
      status,
      // The live progress updates in place; only the end of the call swaps
      // the title.
      statusKey: liveProgress === null ? undefined : "progress",
      headerAccessory:
        error === null && !stopped ? (
          <DiffStat added={totals.added} removed={totals.removed} />
        ) : undefined,
      supportsCollapsible: true,
      // Nothing to open until the patch, its end or an error arrives; until
      // then the step shows a loading shimmer.
      content: patch || end !== null || error !== null ? content : null,
    },
  ]);
}
