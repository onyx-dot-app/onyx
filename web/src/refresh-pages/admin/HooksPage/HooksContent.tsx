"use client";

import { useState, useEffect } from "react";
import { toast } from "@/hooks/useToast";
import { useHookSpecs } from "@/hooks/useHookSpecs";
import SimpleLoader from "@/refresh-components/loaders/SimpleLoader";
import { ContentAction } from "@opal/layouts";
import { Button } from "@opal/components";
import InputSearch from "@/refresh-components/inputs/InputSearch";
import Card from "@/refresh-components/cards/Card";
import Text from "@/refresh-components/texts/Text";
import {
  SvgArrowExchange,
  SvgBubbleText,
  SvgExternalLink,
  SvgFileBroadcast,
  SvgHookNodes,
} from "@opal/icons";
import { IconFunctionComponent } from "@opal/types";

const HOOK_POINT_ICONS: Record<string, IconFunctionComponent> = {
  document_ingestion: SvgFileBroadcast,
  query_processing: SvgBubbleText,
};

function getHookPointIcon(hookPoint: string): IconFunctionComponent {
  return HOOK_POINT_ICONS[hookPoint] ?? SvgHookNodes;
}

export default function HooksContent() {
  const [search, setSearch] = useState("");

  const { specs, isLoading, error } = useHookSpecs();

  useEffect(() => {
    if (error) {
      console.error("Failed to load hook specs", error);
      toast.error("Failed to load hook specs");
    }
  }, [error]);

  if (isLoading) {
    return <SimpleLoader />;
  }

  if (error) {
    return (
      <Text text03 secondaryBody>
        Failed to load hook specifications. Please refresh the page.
      </Text>
    );
  }

  const filtered = (specs ?? []).filter(
    (spec) =>
      spec.display_name.toLowerCase().includes(search.toLowerCase()) ||
      spec.description.toLowerCase().includes(search.toLowerCase())
  );

  return (
    <div className="flex flex-col gap-6">
      <InputSearch
        placeholder="Search hooks..."
        value={search}
        onChange={(e) => setSearch(e.target.value)}
      />

      <div className="flex flex-col gap-2">
        {filtered.length === 0 ? (
          <Text text03 secondaryBody>
            {search
              ? "No hooks match your search."
              : "No hook points are available."}
          </Text>
        ) : (
          filtered.map((spec) => (
            <Card
              key={spec.hook_point}
              variant="secondary"
              padding={0.5}
              gap={0}
            >
              <ContentAction
                icon={getHookPointIcon(spec.hook_point)}
                title={spec.display_name}
                description={spec.description}
                sizePreset="main-content"
                variant="section"
                paddingVariant="fit"
                rightChildren={
                  // TODO(Bo-Onyx): wire up Connect — open modal to create/edit hook
                  <Button prominence="tertiary" rightIcon={SvgArrowExchange}>
                    Connect
                  </Button>
                }
              />
              {spec.docs_url && (
                <div className="pl-7 pt-1">
                  <a
                    href={spec.docs_url}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="flex items-center gap-1 w-fit text-text-03"
                  >
                    <Text as="span" secondaryBody text03 className="underline">
                      Documentation
                    </Text>
                    <SvgExternalLink size={16} className="text-text-02" />
                  </a>
                </div>
              )}
            </Card>
          ))
        )}
      </div>
    </div>
  );
}
