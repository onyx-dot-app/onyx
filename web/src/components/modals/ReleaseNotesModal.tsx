import { useState, useEffect } from "react";
import useSWR from "swr";
import Modal from "@/refresh-components/Modal";
import Button from "@/refresh-components/buttons/Button";
import Text from "@/refresh-components/texts/Text";
import Message from "@/refresh-components/messages/Message";
import SimpleLoader from "@/refresh-components/loaders/SimpleLoader";
import InlineExternalLink from "@/refresh-components/InlineExternalLink";
import { SvgSparkle, SvgExternalLink } from "@opal/icons";
import {
  ContentSection,
  ReleaseNoteEntry,
} from "@/app/admin/settings/interfaces";
import { errorHandlingFetcher } from "@/lib/fetcher";
import { Section } from "@/layouts/general-layouts";

interface ReleaseNotesResponse {
  entries: ReleaseNoteEntry[];
  fetched_at: string;
}

export interface ReleaseNotesModalProps {
  version: string;
  onClose: () => void;
}

function SectionRenderer({
  section,
  onImageLoad,
}: {
  section: ContentSection;
  onImageLoad?: () => void;
}) {
  switch (section.type) {
    case "heading":
      return (
        <Text
          headingH2={section.level === 2}
          headingH3={section.level !== 2}
          text05
        >
          {section.content}
        </Text>
      );

    case "text":
      return <Text text04>{section.content}</Text>;

    case "image":
      return (
        <img
          src={section.src}
          alt={section.content || ""}
          className="rounded-12 max-w-[75%] mx-auto block"
          onLoad={onImageLoad}
          onError={onImageLoad}
        />
      );

    case "callout":
      const variant = section.variant || "note";
      return (
        <Message
          static
          medium
          icon
          close={false}
          text={section.content || ""}
          info={variant === "info"}
          warning={variant === "warning"}
          success={variant === "tip"}
          default={variant === "note"}
          className="w-full"
        />
      );

    default:
      return null;
  }
}

export default function ReleaseNotesModal({
  version,
  onClose,
}: ReleaseNotesModalProps) {
  const { data, isLoading } = useSWR<ReleaseNotesResponse>(
    "/api/release-notes",
    errorHandlingFetcher
  );

  const entry = data?.entries.find((e) => e.version === version);

  // Count images in entry sections
  const imageCount =
    entry?.sections.filter((s) => s.type === "image").length ?? 0;
  const [imagesLoaded, setImagesLoaded] = useState(0);

  // Reset image load count when entry changes
  useEffect(() => {
    setImagesLoaded(0);
  }, [entry?.version]);

  const handleImageLoad = () => {
    setImagesLoaded((prev) => prev + 1);
  };

  const allImagesLoaded = imageCount === 0 || imagesLoaded >= imageCount;
  const showLoading = isLoading || (entry && !allImagesLoaded);

  return (
    <Modal open onOpenChange={onClose}>
      <Modal.Content medium>
        <Modal.Header
          icon={SvgSparkle}
          title={`Onyx ${version}`}
          description={entry?.date}
          onClose={onClose}
        />
        <Modal.Body>
          {isLoading && <SimpleLoader className="self-center" />}
          {!isLoading && entry ? (
            <>
              {entry.tags.length > 0 && (
                <Section flexDirection="row" justifyContent="start">
                  {entry.tags.map((tag) => (
                    // TODO replace this with a chip component that @raunakab will create
                    <Text
                      key={tag}
                      secondaryBody
                      text03
                      className="px-2 py-1 bg-background-tint-02 rounded-08"
                    >
                      {tag}
                    </Text>
                  ))}
                </Section>
              )}
              <Section alignItems="start">
                {entry.sections.map((section, idx) => (
                  <SectionRenderer
                    key={idx}
                    section={section}
                    onImageLoad={handleImageLoad}
                  />
                ))}
              </Section>
            </>
          ) : !isLoading ? (
            <Text as="p" secondaryBody text03>
              Check out the full release notes at{" "}
              <InlineExternalLink href="https://docs.onyx.app/changelog">
                docs.onyx.app/changelog
              </InlineExternalLink>
            </Text>
          ) : null}
        </Modal.Body>
        <Modal.Footer>
          <Button
            tertiary
            leftIcon={SvgExternalLink}
            onClick={() =>
              window.open("https://docs.onyx.app/changelog", "_blank")
            }
          >
            View Full Release Notes
          </Button>
        </Modal.Footer>
      </Modal.Content>
    </Modal>
  );
}
