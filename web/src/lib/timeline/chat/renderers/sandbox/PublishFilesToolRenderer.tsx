import { type ComponentProps, useMemo } from "react";
import { useTranslations } from "next-intl";
import { Section } from "@opal/layouts";
import { Text } from "@opal/components";
import { SvgFiles } from "@opal/icons";
import {
  PacketType,
  PublishFilesEnd,
  PublishFilesStart,
  PublishFilesToolPacket,
} from "@/app/app/services/streamingModels";
import { MessageRenderer } from "@/app/app/message/messageComponents/types";
import {
  SandboxCallContent,
  SandboxCallError,
} from "@/lib/timeline/chat/renderers/sandbox/sandboxCall";
import { useSandboxCallStatus } from "@/lib/sandbox/hooks";

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
  const { error, stopped } = useSandboxCallStatus(
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
            label: file.title ?? file.name,
            path: file.path,
          }))
        : (start?.files ?? []).map((file) => ({
            label: file.title ?? file.path.split("/").pop() ?? file.path,
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

  const content = (
    <SandboxCallContent renderType={renderType}>
      {start?.description && (
        <Text as="p" font="secondary-body" color="text-03">
          {start.description}
        </Text>
      )}

      {rows.length > 0 && (
        <Section gap={0.5} alignItems="start" height="fit">
          {rows.map((row, index) => (
            <Section
              key={`${row.path}-${index}`}
              flexDirection="row"
              justifyContent="start"
              alignItems="start"
              gap={0.5}
              height="fit"
            >
              <Text font="secondary-action" color="text-04">
                {row.label}
              </Text>
              {row.path !== row.label && (
                <Text
                  font="secondary-mono"
                  color="text-03"
                  wordWrap="break-all"
                >
                  {row.path}
                </Text>
              )}
            </Section>
          ))}
        </Section>
      )}

      {error !== null && <SandboxCallError error={error} />}
    </SandboxCallContent>
  );

  return children([
    {
      icon: SvgFiles,
      status,
      supportsCollapsible: true,
      content,
    },
  ]);
}
