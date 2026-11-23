import { type ComponentProps, useMemo } from "react";
import { useTranslations } from "next-intl";
import { Section } from "@opal/layouts";
import { Text, type TextColor } from "@opal/components";
import { codeSpan, markdown, richNodes, stripBidiControls } from "@opal/utils";
import { STEP_ICONS } from "@/lib/timeline/icons";
import {
  ApplyPatchEnd,
  ApplyPatchFileChange,
  ApplyPatchStart,
  ApplyPatchToolPacket,
  FileToolProgress,
  PacketType,
} from "@/app/app/services/streamingModels";
import { MessageRenderer } from "@/app/app/message/messageComponents/types";
import ExpandableTextDisplay from "@/refresh-components/texts/ExpandableTextDisplay";
import {
  SandboxCallContent,
  SandboxCallError,
} from "@/lib/timeline/chat/renderers/sandbox/sandboxCall";
import { useSandboxCallStatus } from "@/lib/sandbox/hooks";

// git-style status letters for the changed files
const CHANGE_MARKERS = {
  add: { marker: "A", color: "status-success-05" },
  update: { marker: "M", color: "status-warning-05" },
  delete: { marker: "D", color: "status-error-05" },
} satisfies Record<
  ApplyPatchFileChange["change"],
  { marker: string; color: TextColor }
>;

const COLLAPSED_PATCH_LINES = 6;
// Lines that get their own colored element. The rest of a larger patch shows
// as one plain block, so even a 1 MiB patch opens quickly.
const MAX_COLORED_PATCH_LINES = 2000;

function renderPatchLines(text: string) {
  const patch = text.endsWith("\n") ? text.slice(0, -1) : text;
  const coloredLines = patch.split("\n", MAX_COLORED_PATCH_LINES);
  const plainRest = patch.slice(
    coloredLines.reduce((length, line) => length + line.length + 1, 0)
  );
  return (
    <div dir="ltr" className="whitespace-pre-wrap wrap-break-word">
      {coloredLines.map((line, index) => (
        <Text
          key={index}
          font="secondary-mono"
          color={
            line.startsWith("+")
              ? "status-success-05"
              : line.startsWith("-")
                ? "status-error-05"
                : line.startsWith("***") || line.startsWith("@@")
                  ? "text-02"
                  : "text-04"
          }
        >
          {`${line}\n`}
        </Text>
      ))}
      {plainRest && (
        <Text font="secondary-mono" color="text-04">
          {plainRest}
        </Text>
      )}
    </div>
  );
}

interface FileRow {
  path: string;
  // Set once the call changed the file
  change: ApplyPatchFileChange["change"] | null;
  movePath: string | null;
}

/** The files of a call: named while it streams, then marked as changed. */
function FileList({ files }: { files: FileRow[] }) {
  return (
    <Section gap={1} alignItems="start" height="fit">
      {files.map((file, index) => (
        <Section
          key={index}
          flexDirection="row"
          justifyContent="start"
          alignItems="start"
          gap={2}
          height="fit"
        >
          {file.change !== null && (
            <Text
              font="secondary-mono"
              color={CHANGE_MARKERS[file.change].color}
            >
              {CHANGE_MARKERS[file.change].marker}
            </Text>
          )}
          <Text font="secondary-mono" color="text-04" wordWrap="break-all">
            {richNodes(
              <>
                <span dir="ltr">{stripBidiControls(file.path)}</span>
                {file.movePath !== null && (
                  <>
                    {" → "}
                    <span dir="ltr">{stripBidiControls(file.movePath)}</span>
                  </>
                )}
              </>
            )}
          </Text>
        </Section>
      ))}
    </Section>
  );
}

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
  const patch = start?.patch ?? "";
  const { isComplete, error, stopped } = useSandboxCallStatus(
    packets,
    end,
    stopPacketSeen,
    onComplete
  );

  // The collapsed view gets one line more than it shows, so it detects the
  // cut, and never lays out the whole patch. That line is never blank: a
  // blank last line would render as nothing and hide the cut.
  const patchHead = useMemo(() => {
    let lineEnd = -1;
    for (let line = 0; line < COLLAPSED_PATCH_LINES; line++) {
      lineEnd = patch.indexOf("\n", lineEnd + 1);
      if (lineEnd === -1) return patch;
    }
    return lineEnd + 1 < patch.length ? `${patch.slice(0, lineEnd)}\n…` : patch;
  }, [patch]);

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

  const content = (
    <SandboxCallContent renderType={renderType}>
      {liveProgress?.tool_name === "apply_patch" && (
        <FileList
          files={liveProgress.paths.map((path) => ({
            path,
            change: null,
            movePath: null,
          }))}
        />
      )}

      {end !== null && end.files.length > 0 && (
        <FileList
          files={end.files.map((file) => ({
            path: file.path,
            change: file.change,
            movePath: file.move_path,
          }))}
        />
      )}

      {error !== null && <SandboxCallError error={error} />}

      {patch && (
        <ExpandableTextDisplay
          title={t("sandbox.patch.title")}
          content={patch}
          displayContent={patchHead}
          maxLines={COLLAPSED_PATCH_LINES}
          renderContent={renderPatchLines}
        />
      )}
    </SandboxCallContent>
  );

  return children([
    {
      icon: STEP_ICONS.edit,
      status,
      // The live progress updates in place; only the end of the call swaps
      // the title.
      statusKey: liveProgress === null ? undefined : "progress",
      supportsCollapsible: true,
      content,
    },
  ]);
}
