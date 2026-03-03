import { SlackChannelConfigCreationForm } from "../SlackChannelConfigCreationForm";
import { fetchSS } from "@/lib/utilsSS";
import { ErrorCallout } from "@/components/ErrorCallout";
import { DocumentSetSummary } from "@/lib/types";
import { fetchAgentsSS } from "@/lib/agentsSS";
import { getStandardAnswerCategoriesIfEE } from "@/components/standardAnswers/getStandardAnswerCategoriesIfEE";
import { redirect } from "next/navigation";
import * as SettingsLayouts from "@/layouts/settings-layouts";
import { SvgSlack } from "@opal/icons";

async function NewChannelConfigPage(props: {
  params: Promise<{ "bot-id": string }>;
}) {
  const unwrappedParams = await props.params;
  const slack_bot_id_raw = unwrappedParams?.["bot-id"] || null;
  const slack_bot_id = slack_bot_id_raw
    ? parseInt(slack_bot_id_raw as string, 10)
    : null;
  if (!slack_bot_id || isNaN(slack_bot_id)) {
    redirect("/admin/bots");
    return null;
  }

  const [documentSetsResponse, agentsResponse, standardAnswerCategoryResponse] =
    await Promise.all([
      fetchSS("/manage/document-set") as Promise<Response>,
      fetchAgentsSS(),
      getStandardAnswerCategoriesIfEE(),
    ]);

  if (!documentSetsResponse.ok) {
    return (
      <ErrorCallout
        errorTitle="Something went wrong :("
        errorMsg={`Failed to fetch document sets - ${await documentSetsResponse.text()}`}
      />
    );
  }
  const documentSets =
    (await documentSetsResponse.json()) as DocumentSetSummary[];

  if (agentsResponse[1]) {
    return (
      <ErrorCallout
        errorTitle="Something went wrong :("
        errorMsg={`Failed to fetch agents - ${agentsResponse[1]}`}
      />
    );
  }

  return (
    <SettingsLayouts.Root>
      <SettingsLayouts.Header
        icon={SvgSlack}
        title="Configure OnyxBot for Slack Channel"
        separator
        backButton
      />
      <SettingsLayouts.Body>
        <SlackChannelConfigCreationForm
          slack_bot_id={slack_bot_id}
          documentSets={documentSets}
          personas={agentsResponse[0]}
          standardAnswerCategoryResponse={standardAnswerCategoryResponse}
        />
      </SettingsLayouts.Body>
    </SettingsLayouts.Root>
  );
}

export default NewChannelConfigPage;
