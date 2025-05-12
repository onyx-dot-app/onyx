import { AdminPageTitle } from "@/components/admin/Title";
import { SourceIcon } from "@/components/SourceIcon";
import { SlackShortcutConfigCreationForm } from "../SlackShortcutConfigCreationForm";
import { fetchSS } from "@/lib/utilsSS";
import { ErrorCallout } from "@/components/ErrorCallout";
import { DocumentSet, SlackShortcutConfig, ValidSources } from "@/lib/types";
import { BackButton } from "@/components/BackButton";
import { InstantSSRAutoRefresh } from "@/components/SSRAutoRefresh";
import {
  FetchAssistantsResponse,
  fetchAssistantsSS,
} from "@/lib/assistants/fetchAssistantsSS";
import { getStandardAnswerCategoriesIfEE } from "@/components/standardAnswers/getStandardAnswerCategoriesIfEE";

async function EditSlackShortcutConfigPage(props: {
  params: Promise<{ id: number }>;
}) {
  const params = await props.params;
  const tasks = [
    fetchSS("/manage/admin/slack-app/shortcut"),
    fetchSS("/manage/document-set"),
    fetchAssistantsSS(),
  ];

  const [
    slackShortcutsResponse,
    documentSetsResponse,
    [assistants, assistantsFetchError],
  ] = (await Promise.all(tasks)) as [
    Response,
    Response,
    FetchAssistantsResponse,
  ];

  const eeStandardAnswerCategoryResponse =
    await getStandardAnswerCategoriesIfEE();

  if (!slackShortcutsResponse.ok) {
    return (
      <ErrorCallout
        errorTitle="Something went wrong :("
        errorMsg={`Failed to fetch Slack Shortcuts - ${await slackShortcutsResponse.text()}`}
      />
    );
  }
  const allSlackShortcutConfigs =
    (await slackShortcutsResponse.json()) as SlackShortcutConfig[];

  const slackShortcutConfig = allSlackShortcutConfigs.find(
    (config) => config.id === Number(params.id)
  );

  if (!slackShortcutConfig) {
    return (
      <ErrorCallout
        errorTitle="Something went wrong :("
        errorMsg={`Did not find Slack Shortcut config with ID: ${params.id}`}
      />
    );
  }

  if (!documentSetsResponse.ok) {
    return (
      <ErrorCallout
        errorTitle="Something went wrong :("
        errorMsg={`Failed to fetch document sets - ${await documentSetsResponse.text()}`}
      />
    );
  }
  const response = await documentSetsResponse.json();
  const documentSets = response as DocumentSet[];

  if (assistantsFetchError) {
    return (
      <ErrorCallout
        errorTitle="Something went wrong :("
        errorMsg={`Failed to fetch personas - ${assistantsFetchError}`}
      />
    );
  }

  return (
    <div className="max-w-4xl container mx-auto">
      <InstantSSRAutoRefresh />

      <BackButton />
      <AdminPageTitle
        icon={<SourceIcon sourceType={ValidSources.Slack} iconSize={32} />}
        title="Edit Slack Shortcut Config"
      />

      <SlackShortcutConfigCreationForm
        slack_bot_id={slackShortcutConfig.slack_bot_id}
        documentSets={documentSets}
        personas={assistants}
        standardAnswerCategoryResponse={eeStandardAnswerCategoryResponse}
        existingSlackShortcutConfig={slackShortcutConfig}
      />
    </div>
  );
}

export default EditSlackShortcutConfigPage;