"use client";

import { use } from "react";
import { SlackChannelConfigCreationForm } from "../SlackChannelConfigCreationForm";
import { ErrorCallout } from "@/components/ErrorCallout";
import { ThreeDotsLoader } from "@/components/Loading";
import { InstantSSRAutoRefresh } from "@/components/SSRAutoRefresh";
import * as SettingsLayouts from "@/layouts/settings-layouts";
import { SvgSlack } from "@opal/icons";
import { useSlackChannelConfigs } from "../../hooks";
import { useDocumentSets } from "@/app/admin/documents/sets/hooks";
import { useAgents } from "@/hooks/useAgents";
import { useStandardAnswerCategories } from "@/app/ee/admin/standard-answer/hooks";
import { usePaidEnterpriseFeaturesEnabled } from "@/components/settings/usePaidEnterpriseFeaturesEnabled";
import type { StandardAnswerCategoryResponse } from "@/components/standardAnswers/getStandardAnswerCategoriesIfEE";

function EditSlackChannelConfigContent({ id }: { id: number }) {
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

  if (
    isChannelsLoading ||
    isDocSetsLoading ||
    isAgentsLoading ||
    (isPaidEnterprise && isStdAnswerLoading)
  ) {
    return <ThreeDotsLoader />;
  }

  if (channelsError || !slackChannelConfigs) {
    return (
      <ErrorCallout
        errorTitle="Something went wrong :("
        errorMsg={`Failed to fetch Slack Channels - ${
          channelsError?.message ?? "unknown error"
        }`}
      />
    );
  }

  const slackChannelConfig = slackChannelConfigs.find(
    (config) => config.id === id
  );

  if (!slackChannelConfig) {
    return (
      <ErrorCallout
        errorTitle="Something went wrong :("
        errorMsg={`Did not find Slack Channel config with ID: ${id}`}
      />
    );
  }

  if (docSetsError || !documentSets) {
    return (
      <ErrorCallout
        errorTitle="Something went wrong :("
        errorMsg={`Failed to fetch document sets - ${
          docSetsError?.message ?? "unknown error"
        }`}
      />
    );
  }

  if (agentsError) {
    return (
      <ErrorCallout
        errorTitle="Something went wrong :("
        errorMsg={`Failed to fetch personas - ${
          agentsError?.message ?? "unknown error"
        }`}
      />
    );
  }

  const standardAnswerCategoryResponse: StandardAnswerCategoryResponse =
    isPaidEnterprise
      ? {
          paidEnterpriseFeaturesEnabled: true,
          categories: standardAnswerCategories ?? [],
          ...(stdAnswerError
            ? { error: { message: String(stdAnswerError) } }
            : {}),
        }
      : { paidEnterpriseFeaturesEnabled: false };

  return (
    <SlackChannelConfigCreationForm
      slack_bot_id={slackChannelConfig.slack_bot_id}
      documentSets={documentSets}
      personas={agents}
      standardAnswerCategoryResponse={standardAnswerCategoryResponse}
      existingSlackChannelConfig={slackChannelConfig}
    />
  );
}

export default function Page(props: { params: Promise<{ id: number }> }) {
  const params = use(props.params);

  return (
    <SettingsLayouts.Root>
      <InstantSSRAutoRefresh />
      <SettingsLayouts.Header
        icon={SvgSlack}
        title="Edit Slack Channel Config"
        separator
        backButton
      />
      <SettingsLayouts.Body>
        <EditSlackChannelConfigContent id={Number(params.id)} />
      </SettingsLayouts.Body>
    </SettingsLayouts.Root>
  );
}
