"use client";

import { use } from "react";
import { SlackChannelConfigCreationForm } from "@/app/admin/bots/[bot-id]/channels/SlackChannelConfigCreationForm";
import { ErrorCallout } from "@/components/ErrorCallout";
import SimpleLoader from "@/refresh-components/loaders/SimpleLoader";
import * as SettingsLayouts from "@/layouts/settings-layouts";
import { SvgSlack } from "@opal/logos";
import { useSlackChannelConfigs } from "@/app/admin/bots/[bot-id]/hooks";
import { useDocumentSets } from "@/app/admin/documents/sets/hooks";
import { useAgents } from "@/hooks/useAgents";
import { useStandardAnswerCategories } from "@/app/ee/admin/standard-answer/hooks";
import { usePaidEnterpriseFeaturesEnabled } from "@/components/settings/usePaidEnterpriseFeaturesEnabled";
import type { StandardAnswerCategoryResponse } from "@/components/standardAnswers/getStandardAnswerCategoriesIfEE";

function EditSlackChannelConfigContent({ id }: { id: string }) {
  const isPaidEnterprise = usePaidEnterpriseFeaturesEnabled();

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
    (isPaidEnterprise && isStdAnswerLoading);

  const slackChannelConfig = slackChannelConfigs?.find(
    (config) => config.id === Number(id)
  );

  const title = slackChannelConfig?.is_default
    ? "Edit Default Slack Config"
    : "Edit Slack Channel Config";

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
          <SimpleLoader />
        ) : channelsError || !slackChannelConfigs ? (
          <ErrorCallout
            errorTitle="Something went wrong :("
            errorMsg={`Failed to fetch Slack Channels - ${
              channelsError?.message ?? "unknown error"
            }`}
          />
        ) : !slackChannelConfig ? (
          <ErrorCallout
            errorTitle="Something went wrong :("
            errorMsg={`Did not find Slack Channel config with ID: ${id}`}
          />
        ) : docSetsError || !documentSets ? (
          <ErrorCallout
            errorTitle="Something went wrong :("
            errorMsg={`Failed to fetch document sets - ${
              docSetsError?.message ?? "unknown error"
            }`}
          />
        ) : agentsError ? (
          <ErrorCallout
            errorTitle="Something went wrong :("
            errorMsg={`Failed to fetch agents - ${
              agentsError?.message ?? "unknown error"
            }`}
          />
        ) : (
          <SlackChannelConfigCreationForm
            slack_bot_id={slackChannelConfig.slack_bot_id}
            documentSets={documentSets}
            personas={agents}
            standardAnswerCategoryResponse={
              isPaidEnterprise
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
