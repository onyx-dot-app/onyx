"use client";

import { use } from "react";
import { useTranslations } from "next-intl";
import { SlackChannelConfigCreationForm } from "@/app/admin/bots/[bot-id]/channels/SlackChannelConfigCreationForm";
import { ErrorCallout } from "@/components/ErrorCallout";
import { SvgSimpleLoader } from "@opal/icons";
import { SettingsLayouts } from "@opal/layouts";
import { SvgSlack } from "@opal/logos";
import { useSlackChannelConfigs } from "@/app/admin/bots/[bot-id]/hooks";
import { useDocumentSets } from "@/app/admin/documents/sets/hooks";
import { useAgents } from "@/lib/agents/hooks";
import { useStandardAnswerCategories } from "@/app/ee/admin/standard-answer/hooks";
import { useTierAtLeast } from "@/hooks/useTierAtLeast";
import { Tier } from "@/lib/settings/types";
import type { StandardAnswerCategoryResponse } from "@/components/standardAnswers/getStandardAnswerCategoriesIfEE";

function EditSlackChannelConfigContent({ id }: { id: string }) {
  const t = useTranslations("admin.slackBots");
  const enterpriseTier = useTierAtLeast(Tier.ENTERPRISE);

  const {
    data: slackChannelConfigs,
    isLoading: isChannelsLoading,
    error: channelsError,
  } = useSlackChannelConfigs();

  const {
    data: documentSets,
    isLoading: isDocSetsLoading,
    error: docSetsError,
  } = useDocumentSets();

  const {
    agents,
    isLoading: isAgentsLoading,
    error: agentsError,
  } = useAgents();

  const {
    data: standardAnswerCategories,
    isLoading: isStdAnswerLoading,
    error: stdAnswerError,
  } = useStandardAnswerCategories();

  const isLoading =
    isChannelsLoading ||
    isDocSetsLoading ||
    isAgentsLoading ||
    (enterpriseTier && isStdAnswerLoading);

  const slackChannelConfig = slackChannelConfigs?.find(
    (config) => config.id === Number(id)
  );

  const title = slackChannelConfig?.is_default
    ? t("editChannel.default.header.title")
    : t("editChannel.channel.header.title");

  return (
    <SettingsLayouts.Root>
      <SettingsLayouts.Header
        icon={SvgSlack}
        title={title}
        divider
        backButton
      />
      <SettingsLayouts.Body>
        {isLoading ? (
          <SvgSimpleLoader />
        ) : channelsError || !slackChannelConfigs ? (
          <ErrorCallout
            errorTitle={t("error.generic.title")}
            errorMsg={t("error.fetchChannels.message", {
              error: channelsError?.message ?? t("error.unknown.message"),
            })}
          />
        ) : !slackChannelConfig ? (
          <ErrorCallout
            errorTitle={t("error.generic.title")}
            errorMsg={t("error.channelConfigNotFound.message", { id })}
          />
        ) : docSetsError || !documentSets ? (
          <ErrorCallout
            errorTitle={t("error.generic.title")}
            errorMsg={t("error.fetchDocumentSets.message", {
              error: docSetsError?.message ?? t("error.unknown.message"),
            })}
          />
        ) : agentsError ? (
          <ErrorCallout
            errorTitle={t("error.generic.title")}
            errorMsg={t("error.fetchAgents.message", {
              error: agentsError?.message ?? t("error.unknown.message"),
            })}
          />
        ) : (
          <SlackChannelConfigCreationForm
            slack_bot_id={slackChannelConfig.slack_bot_id}
            documentSets={documentSets}
            personas={agents}
            standardAnswerCategoryResponse={
              enterpriseTier
                ? {
                    paidEnterpriseFeaturesEnabled: true,
                    categories: standardAnswerCategories ?? [],
                    ...(stdAnswerError
                      ? { error: { message: String(stdAnswerError) } }
                      : {}),
                  }
                : { paidEnterpriseFeaturesEnabled: false }
            }
            existingSlackChannelConfig={slackChannelConfig}
          />
        )}
      </SettingsLayouts.Body>
    </SettingsLayouts.Root>
  );
}

export default function Page(props: { params: Promise<{ id: string }> }) {
  const params = use(props.params);

  return <EditSlackChannelConfigContent id={params.id} />;
}
