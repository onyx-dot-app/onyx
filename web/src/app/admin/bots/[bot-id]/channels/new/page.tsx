"use client";

import { use, useEffect } from "react";
import { SlackChannelConfigCreationForm } from "@/app/admin/bots/[bot-id]/channels/SlackChannelConfigCreationForm";
import { ErrorCallout } from "@/components/ErrorCallout";
import SimpleLoader from "@/refresh-components/loaders/SimpleLoader";
import * as SettingsLayouts from "@/layouts/settings-layouts";
import { SvgSlack } from "@opal/icons";
import { useDocumentSets } from "@/app/admin/documents/sets/hooks";
import { useAgents } from "@/hooks/useAgents";
import { useStandardAnswerCategories } from "@/app/ee/admin/standard-answer/hooks";
import { usePaidEnterpriseFeaturesEnabled } from "@/components/settings/usePaidEnterpriseFeaturesEnabled";
import type { StandardAnswerCategoryResponse } from "@/components/standardAnswers/getStandardAnswerCategoriesIfEE";
import { useRouter } from "next/navigation";

function NewChannelConfigContent({ slackBotId }: { slackBotId: number }) {
  const isPaidEnterprise = usePaidEnterpriseFeaturesEnabled();

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
    isDocSetsLoading ||
    isAgentsLoading ||
    (isPaidEnterprise && isStdAnswerLoading)
  ) {
    return <SimpleLoader />;
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
        errorMsg={`Failed to fetch agents - ${
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
      slack_bot_id={slackBotId}
      documentSets={documentSets}
      personas={agents}
      standardAnswerCategoryResponse={standardAnswerCategoryResponse}
    />
  );
}

export default function Page(props: { params: Promise<{ "bot-id": string }> }) {
  const unwrappedParams = use(props.params);
  const router = useRouter();

  const slack_bot_id_raw = unwrappedParams?.["bot-id"] || null;
  const slack_bot_id = slack_bot_id_raw
    ? parseInt(slack_bot_id_raw as string, 10)
    : null;

  useEffect(() => {
    if (!slack_bot_id || isNaN(slack_bot_id)) {
      router.replace("/admin/bots");
    }
  }, [slack_bot_id, router]);

  if (!slack_bot_id || isNaN(slack_bot_id)) {
    return null;
  }

  return (
    <SettingsLayouts.Root>
      <SettingsLayouts.Header
        icon={SvgSlack}
        title="Configure PrivateGPTBot for Slack Channel"
        separator
        backButton
      />
      <SettingsLayouts.Body>
        <NewChannelConfigContent slackBotId={slack_bot_id} />
      </SettingsLayouts.Body>
    </SettingsLayouts.Root>
  );
}
