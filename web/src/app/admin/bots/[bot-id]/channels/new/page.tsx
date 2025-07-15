import { AdminPageTitle } from "@/components/admin/Title";
import { SlackChannelConfigCreationForm } from "../SlackChannelConfigCreationForm";
import { fetchSS } from "@/lib/utilsSS";
import { ErrorCallout } from "@/components/ErrorCallout";
import { DocumentSetSummary, ValidSources } from "@/lib/types";
import { BackButton } from "@/components/BackButton";
import { fetchAssistantsSS } from "@/lib/assistants/fetchAssistantsSS";
import { getStandardAnswerCategoriesIfEE } from "@/components/standardAnswers/getStandardAnswerCategoriesIfEE";
import { redirect } from "next/navigation";
import { SourceIcon } from "@/components/SourceIcon";

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

  const [
    documentSetsResponse,
    assistantsResponse,
    standardAnswerCategoryResponse,
  ] = await Promise.all([
    fetchSS("/manage/document-set") as Promise<Response>,
    fetchAssistantsSS(),
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

  if (assistantsResponse[1]) {
    return (
      <ErrorCallout
        errorTitle="Something went wrong :("
        errorMsg={`Failed to fetch assistants - ${assistantsResponse[1]}`}
      />
    );
  }

  return (
    <div className="container max-w-4xl mx-auto">
      <BackButton />
      <AdminPageTitle
        icon={<SourceIcon iconSize={32} sourceType={ValidSources.Slack} />}
        title="Configure OnyxBot for Slack Channel"
      />

      <SlackChannelConfigCreationForm
        slack_bot_id={slack_bot_id}
        documentSets={documentSets}
        personas={assistantsResponse[0]}
        standardAnswerCategoryResponse={standardAnswerCategoryResponse}
      />
    </div>
  );
}

export default NewChannelConfigPage;
