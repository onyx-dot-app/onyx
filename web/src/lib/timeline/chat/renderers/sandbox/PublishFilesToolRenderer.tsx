import { type ComponentProps, useMemo } from "react";
import { useTranslations } from "next-intl";
import { SvgFiles } from "@opal/icons";
import { stripBidiControls } from "@opal/utils";
import {
  PacketType,
  PublishFilesEnd,
  PublishFilesStart,
  PublishFilesToolPacket,
} from "@/app/app/services/streamingModels";
import { MessageRenderer } from "@/app/app/message/messageComponents/types";
import { SandboxCallContent } from "@/lib/timeline/chat/renderers/sandbox/sandboxCall";
import { CommandBody } from "@/lib/timeline/components/bodies/CommandBody";
import { useSandboxCallStatus } from "@/lib/sandbox/hooks";
import { publishedFileLabel } from "@/lib/chat/publishedFiles";

type PublishFilesToolRendererProps = ComponentProps<
  MessageRenderer<PublishFilesToolPacket, {}>
>;

interface FileRow {
  label: string;
  path: string;
}

/** One publish_files call: the files it asked for, then what it published. */
export function PublishFilesToolRenderer({
  packets,
  onComplete,
  renderType,
  stopPacketSeen,
  children,
}: PublishFilesToolRendererProps) {
  const t = useTranslations("chat.messages.timeline");
  const { start, end } = useMemo(() => {
    let start: PublishFilesStart | null = null;
    let end: PublishFilesEnd | null = null;
    for (const { obj } of packets) {
      if (obj.type === PacketType.PUBLISH_FILES_START) {
        start = obj;
      } else if (obj.type === PacketType.PUBLISH_FILES_END) {
        end = obj;
      }
    }
    return { start, end };
  }, [packets]);
  const { isComplete, error, stopped } = useSandboxCallStatus(
    packets,
    end,
    stopPacketSeen,
    onComplete
  );

  // The published files carry the normalized path; until then, the request.
  const rows: FileRow[] = useMemo(
    () =>
      end !== null && end.files.length > 0
        ? end.files.map((file) => ({
            label: publishedFileLabel(file),
            path: file.path,
          }))
        : (start?.files ?? []).map((file) => ({
            label: publishedFileLabel({
              title: file.title,
              name: file.path.split("/").pop() || file.path,
            }),
            path: file.path,
          })),
    [start, end]
  );

  const status = stopped
    ? t("sandbox.stopped.status")
    : error !== null
      ? t("sandbox.publish.failed.status")
      : end !== null
        ? t("sandbox.publish.published.status", { count: end.files.length })
        : t("header.publishingFiles.label");

  // One panel: the description (as a comment) and the files, one per line,
  // then the output band, which waits with a loading shimmer while the
  // files publish, or shows the error.
  const fileLines = rows
    .map((row) =>
      row.path !== row.label
        ? `${stripBidiControls(row.path)}  # ${row.label}`
        : stripBidiControls(row.path)
    )
    .join("\n");
  const content = (
    <SandboxCallContent renderType={renderType}>
      <CommandBody
        command={fileLines}
        comment={start?.description ?? undefined}
        output=""
        error={error ?? undefined}
        outputLoading={!isComplete}
        emptyLabel=""
      />
    </SandboxCallContent>
  );

  return children([
    {
      icon: SvgFiles,
      status,
      supportsCollapsible: true,
      // Nothing to open until a description, a file or an error arrives.
      content:
        start?.description || rows.length > 0 || error !== null
          ? content
          : null,
    },
  ]);
}
