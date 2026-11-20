"use client";

import { useState } from "react";
import { useTranslations } from "next-intl";
import { Button, MessageCard, Text } from "@opal/components";
import {
  ConfirmationModalLayout,
  Content,
  Section,
  toast,
} from "@opal/layouts";
import { IconLoader } from "@opal/loaders";
import { SvgAlertTriangle, SvgBlocks } from "@opal/icons";
import { fetchErrorDetail } from "@/lib/fetcher";
import { deleteMarketplace } from "@/lib/marketplaces/api";
import { useMarketplace } from "@/lib/marketplaces/hooks";
import type { MarketplaceSummary } from "@/lib/marketplaces/types";
import { useRefreshSkillLists } from "@/lib/skills/hooks";

interface RemoveMarketplaceModalProps {
  marketplace: MarketplaceSummary;
  onClose: () => void;
  onRemoved: () => void;
}

/** Render it inside the `Provider` of a `useCreateModal` owner. */
export default function RemoveMarketplaceModal({
  marketplace,
  onClose,
  onRemoved,
}: RemoveMarketplaceModalProps) {
  const t = useTranslations("plugins.marketplaces.remove");
  const {
    marketplace: detail,
    isLoading,
    refresh,
  } = useMarketplace(marketplace.id);
  const refreshSkillLists = useRefreshSkillLists();
  const [busy, setBusy] = useState(false);
  const plugins = detail?.plugins ?? [];

  async function remove() {
    setBusy(true);
    try {
      await deleteMarketplace(marketplace.id);
      refreshSkillLists();
      toast.success(t("done", { name: marketplace.name }));
      onRemoved();
    } catch (caught) {
      toast.error(fetchErrorDetail(caught) ?? t("failed"));
      setBusy(false);
    }
  }

  return (
    <ConfirmationModalLayout
      icon={SvgAlertTriangle}
      title={t("title", { name: marketplace.name })}
      description={t(
        marketplace.scope === "personal"
          ? "personalDescription"
          : "description",
        { count: marketplace.plugin_count }
      )}
      onClose={() => {
        if (!busy) onClose();
      }}
      submit={
        <Button
          variant="danger"
          disabled={busy || detail === undefined}
          onClick={() => void remove()}
        >
          {t("confirm")}
        </Button>
      }
    >
      {isLoading ? (
        <IconLoader />
      ) : detail === undefined ? (
        <Section alignItems="start" gap={2} height="auto">
          <MessageCard variant="error" title={t("loadFailed")} />
          <Button prominence="secondary" onClick={() => void refresh()}>
            {t("retry")}
          </Button>
        </Section>
      ) : plugins.length === 0 ? (
        <Text as="p" font="secondary-body" color="text-03">
          {t("noPlugins")}
        </Text>
      ) : (
        <Section
          role="list"
          aria-label={t("listLabel")}
          height="auto"
          alignItems="stretch"
          gap={2}
          className="max-h-60 overflow-y-auto"
        >
          {plugins.map((plugin) => (
            <Section
              key={plugin.id}
              role="listitem"
              height="auto"
              alignItems="stretch"
            >
              <Content
                font="main-ui-body"
                icon={SvgBlocks}
                title={plugin.name}
              />
            </Section>
          ))}
        </Section>
      )}
    </ConfirmationModalLayout>
  );
}
