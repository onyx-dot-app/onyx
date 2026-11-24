import { type ComponentProps, useContext, useMemo } from "react";
import { useTranslations } from "next-intl";
import { Tag, Text } from "@opal/components";
import { Section } from "@opal/layouts";
import { LineLoader } from "@opal/loaders";
import { SvgFiles } from "@opal/icons";
import { stripBidiControls } from "@opal/utils";
import {
  PacketType,
  PublishFilesEnd,
  PublishFilesStart,
  PublishFilesToolPacket,
  type PublishedFile,
} from "@/app/app/services/streamingModels";
import { MessageRenderer } from "@/app/app/message/messageComponents/types";
import {
  SandboxCallContent,
  SandboxCallError,
} from "@/lib/timeline/chat/renderers/sandbox/sandboxCall";
import { PublishedFilesPanelContext } from "@/sections/chat/PublishedFileCards";
import { getFileIcon } from "@/lib/utils";
import { useSandboxCallStatus } from "@/lib/sandbox/hooks";
import { publishedFileLabel } from "@/lib/chat/publishedFiles";

type PublishFilesToolRendererProps = ComponentProps<
  MessageRenderer<PublishFilesToolPacket, {}>
>;

interface FileRow {
  label: string;
  path: string;
  /** The stored file, once published. */
  published: PublishedFile | null;
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
            published: file,
          }))
        : (start?.files ?? []).map((file) => ({
            label: publishedFileLabel({
              title: file.title,
              name: file.path.split("/").pop() || file.path,
            }),
            path: file.path,
            published: null,
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

  // A published file opens in the chat's Files panel, as its card does.
  const panel = useContext(PublishedFilesPanelContext);

  // The description, then one chip per file (as search shows what it read):
  // named as soon as the call asks for them, and opening once published. A
  // shimmer waits under them while the files publish.
  const content = (
    <SandboxCallContent renderType={renderType}>
      <Section alignItems="stretch" gap={1} height="fit">
        {start?.description && (
          <Text as="p" font="secondary-body" color="text-03">
            {start.description}
          </Text>
        )}
        {rows.length > 0 && (
          <Section
            flexDirection="row"
            justifyContent="start"
            height="fit"
            gap={1}
            wrap
          >
            {rows.map((row, index) => {
              const published = row.published;
              return (
                <Tag
                  key={`${row.path}-${index}`}
                  icon={getFileIcon(row.path)}
                  title={stripBidiControls(row.label)}
                  truncate
                  onClick={
                    published && panel
                      ? () => panel.openFile(published)
                      : undefined
                  }
                />
              );
            })}
          </Section>
        )}
        {!isComplete && <LineLoader width="2/3" />}
        {error !== null && <SandboxCallError error={error} />}
      </Section>
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
