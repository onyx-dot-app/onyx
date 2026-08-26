"use client";

import { use, useEffect } from "react";
import { useTranslations } from "next-intl";
import { SlackChannelConfigCreationForm } from "@/app/admin/bots/[bot-id]/channels/SlackChannelConfigCreationForm";
import { ErrorCallout } from "@/components/ErrorCallout";
import { SvgSimpleLoader } from "@opal/icons";
import { SettingsLayouts } from "@opal/layouts";
import { SvgSlack } from "@opal/logos";
import { useDocumentSets } from "@/app/admin/documents/sets/hooks";
import { useAgents } from "@/lib/agents/hooks";
import { useStandardAnswerCategories } from "@/app/ee/admin/standard-answer/hooks";
import { useTierAtLeast } from "@/hooks/useTierAtLeast";
import { Tier } from "@/lib/settings/types";
import type { StandardAnswerCategoryResponse } from "@/components/standardAnswers/getStandardAnswerCategoriesIfEE";
import { useRouter } from "next/navigation";

function NewChannelConfigContent({ slackBotId }: { slackBotId: number }) {
  const t = useTranslations("admin.slackBots");
  const enterpriseTier = useTierAtLeast(Tier.ENTERPRISE);

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
    (enterpriseTier && isStdAnswerLoading)
  ) {
    return <SvgSimpleLoader />;
  }

  if (docSetsError || !documentSets) {
    return (
      <ErrorCallout
        errorTitle={t("error.generic.title")}
        errorMsg={t("error.fetchDocumentSets.message", {
          error: docSetsError?.message ?? t("error.unknown.message"),
        })}
      />
    );
  }

  if (agentsError) {
    return (
      <ErrorCallout
        errorTitle={t("error.generic.title")}
        errorMsg={t("error.fetchAgents.message", {
          error: agentsError?.message ?? t("error.unknown.message"),
        })}
      />
    );
  }

  const standardAnswerCategoryResponse: StandardAnswerCategoryResponse =
    enterpriseTier
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
  const t = useTranslations("admin.slackBots");
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
        title={t("newChannel.header.title")}
        divider
        backButton
      />
      <SettingsLayouts.Body>
        <NewChannelConfigContent slackBotId={slack_bot_id} />
      </SettingsLayouts.Body>
    </SettingsLayouts.Root>
  );
}
