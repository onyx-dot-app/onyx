"use client";

import { useEffect } from "react";
import useSWR from "swr";
import { useTranslations } from "next-intl";
import { useNavigation, usePathname } from "@opal/navigation";
import { PageLoader } from "@opal/loaders";
import { ContentAction, IllustrationContent, Section } from "@opal/layouts";
import SvgNoResult from "@opal/illustrations/no-result";
import { SEARCH_PARAM_NAMES } from "@/app/app/services/searchParams";
import { buildImgUrl } from "@/app/app/components/files/images/utils";
import { routeWithQuery } from "@/lib/routes";
import { errorHandlingFetcher } from "@/lib/fetcher";
import { getFileIcon } from "@/lib/utils";
import {
  type ChatArtifactFile,
  parseArtifactLink,
  publishedFileLabel,
} from "@/lib/chat/publishedFiles";
import { SWR_KEYS } from "@/lib/swr-keys";
import { DownloadButton } from "@/sections/file-preview/DownloadButton";
import { PublishedFilePreview } from "@/sections/chat/PublishedFileViews";

interface ArtifactLinkPageProps {
  artifactId: string;
  version: number | null;
}

/**
 * Opens an artifact link outside a chat, as the metadata route's `access`
 * says: the owner goes to the owning chat, a reader of the chat to its shared
 * view, each with the version in the panel (`useOpenArtifactFromUrl`). A user
 * who may open only that version sees the file alone, with its preview and
 * download. Any other user gets ArtifactUnavailable.
 */
export default function ArtifactLinkPage({
  artifactId,
  version,
}: ArtifactLinkPageProps) {
  const navigation = useNavigation();
  // The page stays mounted under the loader of the next page while that
  // renders, so a late response must not send the user back.
  const shownLink = parseArtifactLink(usePathname() ?? "");
  const onLink =
    shownLink?.artifactId === artifactId && shownLink.version === version;
  const {
    data: file,
    error,
    isValidating,
  } = useSWR<ChatArtifactFile, Error>(
    SWR_KEYS.chatArtifact(artifactId, version),
    errorHandlingFetcher
  );
  useEffect(() => {
    // A cached response of an earlier visit can be stale
    if (!file || isValidating || file.access === "file_only" || !onLink) return;
    const artifact = {
      [SEARCH_PARAM_NAMES.ARTIFACT_ID]: artifactId,
      [SEARCH_PARAM_NAMES.ARTIFACT_VERSION]: version ?? undefined,
    };
    navigation.go(
      file.access === "owner"
        ? routeWithQuery("/app", {
            [SEARCH_PARAM_NAMES.CHAT_ID]: file.chat_id,
            ...artifact,
          })
        : routeWithQuery(`/app/shared/${file.chat_id}`, artifact),
      { replace: true }
    );
  }, [file, isValidating, artifactId, version, navigation, onLink]);
  // A cached error of an earlier visit can be stale too
  if (error && !isValidating && onLink) return <ArtifactUnavailable />;
  if (file?.access !== "file_only") return <PageLoader />;
  return (
    <Section gap={0} justifyContent="start" alignItems="stretch" height="full">
      <div data-testid="artifact-link-header">
        <ContentAction
          font="main-content-emphasis"
          icon={getFileIcon(file.name)}
          title={publishedFileLabel(file)}
          padding={2}
          rightChildren={
            <DownloadButton
              fileUrl={buildImgUrl(file.file_id)}
              fileName={file.name}
            />
          }
        />
      </div>
      <PublishedFilePreview file={file} />
    </Section>
  );
}

/**
 * The page of an artifact link that opens nothing: the same for a file that
 * is gone and one of another user, so the page cannot probe for files.
 */
export function ArtifactUnavailable() {
  const t = useTranslations("chat.publishedFiles.unavailable");
  return (
    <Section height="full">
      <IllustrationContent
        illustration={SvgNoResult}
        title={t("title")}
        description={t("description")}
      />
    </Section>
  );
}
