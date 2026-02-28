import { AdminPageTitle } from "@/components/admin/Title";
import { SourceIcon } from "@/components/SourceIcon";
import { SlackChannelConfigCreationForm } from "../SlackChannelConfigCreationForm";
import { fetchSS } from "@/lib/utilsSS";
import { ErrorCallout } from "@/components/ErrorCallout";
import {
  DocumentSetSummary,
  SlackChannelConfig,
  ValidSources,
} from "@/lib/types";
import BackButton from "@/refresh-components/buttons/BackButton";
import { InstantSSRAutoRefresh } from "@/components/SSRAutoRefresh";
import { FetchAgentsResponse, fetchAgentsSS } from "@/lib/agentsSS";
import { getStandardAnswerCategoriesIfEE } from "@/components/standardAnswers/getStandardAnswerCategoriesIfEE";

async function EditslackChannelConfigPage(props: {
  params: Promise<{ id: number }>;
}) {
  const params = await props.params;
  const tasks = [
    fetchSS("/manage/admin/slack-app/channel"),
    fetchSS("/manage/document-set"),
    fetchAgentsSS(),
  ];

  const [
    slackChannelsResponse,
    documentSetsResponse,
    [assistants, agentsFetchError],
  ] = (await Promise.all(tasks)) as [Response, Response, FetchAgentsResponse];

  const eeStandardAnswerCategoryResponse =
    await getStandardAnswerCategoriesIfEE();

  if (!slackChannelsResponse.ok) {
    return (
      <ErrorCallout
        errorTitle="Something went wrong :("
        errorMsg={`Failed to fetch Slack Channels - ${await slackChannelsResponse.text()}`}
      />
    );
  }
  const allslackChannelConfigs =
    (await slackChannelsResponse.json()) as SlackChannelConfig[];

  const slackChannelConfig = allslackChannelConfigs.find(
    (config) => config.id === Number(params.id)
  );

  if (!slackChannelConfig) {
    return (
      <ErrorCallout
        errorTitle="Something went wrong :("
        errorMsg={`Did not find Slack Channel config with ID: ${params.id}`}
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
  const documentSets = response as DocumentSetSummary[];

  if (agentsFetchError) {
    return (
      <ErrorCallout
        errorTitle="Something went wrong :("
        errorMsg={`Failed to fetch personas - ${agentsFetchError}`}
      />
    );
  }

  return (
    <div className="max-w-4xl container">
      <InstantSSRAutoRefresh />

      <BackButton />
      <AdminPageTitle
        icon={<SourceIcon sourceType={ValidSources.Slack} iconSize={32} />}
        title={
          slackChannelConfig.is_default
            ? "Edit Default Slack Config"
            : "Edit Slack Channel Config"
        }
      />

      <SlackChannelConfigCreationForm
        slack_bot_id={slackChannelConfig.slack_bot_id}
        documentSets={documentSets}
        personas={assistants}
        standardAnswerCategoryResponse={eeStandardAnswerCategoryResponse}
        existingSlackChannelConfig={slackChannelConfig}
      />
    </div>
  );
}

export default EditslackChannelConfigPage;
