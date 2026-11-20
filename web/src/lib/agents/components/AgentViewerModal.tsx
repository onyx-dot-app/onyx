"use client";

import { useNavigation } from "@opal/navigation";
import { useCallback } from "react";
import { useTranslations } from "next-intl";
import { FullAgent } from "@/lib/agents/types";
import { Modal } from "@opal/components";
import { Content, InputHorizontal, Section } from "@opal/layouts";
import AgentAvatar from "@/refresh-components/avatars/AgentAvatar";
import { Card, Divider, Text } from "@opal/components";
import { Collapsible } from "@opal/components";
import {
  SvgActions,
  SvgBubbleText,
  SvgOrganization,
  SvgStar,
  SvgUser,
} from "@opal/icons";
import { EmptyMessageCard } from "@opal/components";
import { InputSwitch } from "@opal/components";
import { SEARCH_PARAM_NAMES } from "@/app/app/services/searchParams";
import type { ComposedMessage } from "@/lib/chat/types";
import AppInputBar from "@/sections/input/AppInputBar";
import { useChatSessionQueue } from "@/lib/chat/hooks";
import { useLlmManager } from "@/lib/hooks";
import { useToolConfiguration } from "@/lib/tools/hooks";
import { formatMmDdYyyy } from "@/lib/dateUtils";
import { useProjectsContext } from "@/lib/projects/providers";
import { FileCard } from "@/sections/cards/FileCard";
import DocumentSetCard from "@/sections/cards/DocumentSetCard";
import { getDisplayName } from "@/lib/languageModels/utils";
import { useLanguageModelsForAgent } from "@/lib/languageModels/hooks";
import { Interactive } from "@opal/core";
import { useSettings } from "@/lib/settings/hooks";
import { useMemberIntegrations } from "@/lib/integrations/hooks";

interface ViewerIntegrationCardProps {
  name: string;
  /** False: the user has no access, so a chat runs without it. */
  usable: boolean;
}

function ViewerIntegrationCard({ name, usable }: ViewerIntegrationCardProps) {
  const t = useTranslations("agents.modals");
  return (
    <Card border="solid" rounding={4} padding={4}>
      <Content
        font="main-ui-action"
        icon={SvgActions}
        title={name}
        description={usable ? undefined : t("viewer.actions.noAccess")}
      />
    </Card>
  );
}

/**
 * Floating ChatInputBar below the AgentViewerModal.
 * On submit, navigates to the agent's chat with the message pre-filled.
 */
interface AgentChatInputProps {
  agent: FullAgent;
  onSubmit: (composed: ComposedMessage) => void;
}
function AgentChatInput({ agent, onSubmit }: AgentChatInputProps) {
  const llmManager = useLlmManager(undefined, agent);
  // Over the listing, so the URL says nothing about the chat this would
  // start; the agent is named here instead.
  const toolConfiguration = useToolConfiguration(agent.id);
  // A preview starts a new chat, so it has no pending input.
  const queue = useChatSessionQueue(false);

  // This send navigates in order to send, so the configuration is left where
  // that page will find it rather than travelling with the call. Closing the
  // viewer without sending leaves nothing behind.
  const submit = useCallback(
    (composed: ComposedMessage) => {
      toolConfiguration.handOffToNewChatWith(agent.id);
      onSubmit(composed);
    },
    [toolConfiguration, agent.id, onSubmit]
  );

  return (
    // Its own instance, so source toggles made while previewing an agent do not
    // reach the chat this modal opened over.
    <AppInputBar
      toolConfiguration={toolConfiguration}
      onSubmit={submit}
      llmManager={llmManager}
      chatState="input"
      activeAgent={agent}
      stopGenerating={() => {}}
      handleFileUpload={() => {}}
      deepResearchEnabled={false}
      toggleDeepResearch={() => {}}
      disabled={false}
      queue={queue}
    />
  );
}

/**
 * AgentViewerModal - A read-only view of an agent's configuration
 *
 * This modal is the view-only counterpart to `AgentEditorPage.tsx`. While
 * AgentEditorPage allows creating and editing agents with forms and inputs,
 * AgentViewerModal displays the same information in a read-only format.
 *
 * Key differences from AgentEditorPage:
 * - Modal presentation instead of full page
 * - Read-only display (no form inputs, switches, or editable fields)
 * - Static text/badges instead of form controls
 * - Designed to be opened from AgentCard when clicking on the card body
 *
 * Sections displayed (mirroring AgentEditorPage):
 * - Agent info: name, description, avatar
 * - Instructions (system prompt)
 * - Conversation starters
 * - Knowledge configuration
 * - Actions/tools
 * - Advanced options (model, sharing status)
 */
export interface AgentViewerModalProps {
  agent: FullAgent;
  /** Removes this agent from the URL, which is what closes the modal. */
  onClose: () => void;
}
export function AgentViewerModal({ agent, onClose }: AgentViewerModalProps) {
  const t = useTranslations("agents.modals");
  const navigation = useNavigation();
  const { allRecentFiles } = useProjectsContext();
  const { llmProviders } = useLanguageModelsForAgent(agent.id);
  const { appName } = useSettings();
  const { data: memberIntegrations } = useMemberIntegrations();

  const handleStartChat = useCallback(
    ({ message, mentions }: ComposedMessage) => {
      const params = new URLSearchParams({
        [SEARCH_PARAM_NAMES.AGENT_ID]: String(agent.id),
        [SEARCH_PARAM_NAMES.USER_PROMPT]: message,
        [SEARCH_PARAM_NAMES.SEND_ON_LOAD]: "true",
      });
      // Skill mentions travel as skill names.
      const skills = mentions
        .filter((mention) => mention.type === "skill")
        .map((mention) => mention.name);
      if (skills.length > 0)
        params.set(SEARCH_PARAM_NAMES.SKILLS, skills.join(","));
      navigation.go(`/app?${params.toString()}`);
    },
    [agent.id, navigation]
  );

  const hasKnowledge =
    (agent.document_sets && agent.document_sets.length > 0) ||
    (agent.hierarchy_nodes && agent.hierarchy_nodes.length > 0) ||
    (agent.user_file_ids && agent.user_file_ids.length > 0);

  const integrations = agent.integrations ?? [];
  const hasActions = integrations.length > 0;
  const usableIds = new Set(
    (memberIntegrations ?? [])
      .filter((integration) => integration.access.state !== "no_access")
      .map((integration) => integration.id)
  );
  const defaultModel = getDisplayName(agent, llmProviders ?? []);

  return (
    <Modal
      open
      onOpenChange={(open) => {
        if (!open) onClose();
      }}
    >
      <Modal.Content
        width="lg"
        height="lg"
        bottomSlot={<AgentChatInput agent={agent} onSubmit={handleStartChat} />}
      >
        <Modal.Header
          icon={(props) => <AgentAvatar agent={agent} {...props} size={24} />}
          title={agent.name}
          onClose={onClose}
        />

        <Modal.Body>
          {/* Metadata */}
          <Section flexDirection="row" justifyContent="start">
            {agent.is_featured && (
              <Content
                font="main-ui-body"
                icon={SvgStar}
                title={t("viewer.featured.label")}
                width="fit"
              />
            )}
            <Content
              font="main-ui-body"
              icon={SvgUser}
              title={agent.owner?.email ?? "Onyx"}
              titleColor="text-03"
              width="fit"
            />
            {agent.is_public && (
              <Content
                font="main-ui-body"
                icon={SvgOrganization}
                title={t("viewer.public.label")}
                titleColor="text-03"
                width="fit"
              />
            )}
          </Section>

          {/* Description */}
          {agent.description && (
            <Text color="text-03">{agent.description}</Text>
          )}

          {/* Knowledge */}
          <Divider paddingParallel={0} paddingPerpendicular={0} />
          <Section gap={2} alignItems="start">
            <Content
              font="main-content-emphasis"
              title={t("viewer.knowledge.title")}
            />
            {hasKnowledge ? (
              <Section
                gap={2}
                flexDirection="row"
                justifyContent="start"
                wrap
                alignItems="start"
              >
                {agent.document_sets?.map((docSet) => (
                  <DocumentSetCard key={docSet.id} documentSet={docSet} />
                ))}
                {agent.user_file_ids?.map((fileId) => {
                  const file = allRecentFiles.find((f) => f.id === fileId);
                  if (!file) return null;
                  return <FileCard key={fileId} file={file} />;
                })}
              </Section>
            ) : (
              <EmptyMessageCard
                sizePreset="main-ui"
                title={t("viewer.knowledge.empty.title")}
              />
            )}
          </Section>

          {/* Actions & Tools */}
          <Collapsible title={t("viewer.actions.title")}>
            {hasActions ? (
              <Section gap={2} alignItems="start">
                {integrations.map((integration) => (
                  <ViewerIntegrationCard
                    key={integration.integration_id}
                    name={integration.integration_name}
                    usable={
                      memberIntegrations === undefined ||
                      usableIds.has(integration.integration_id)
                    }
                  />
                ))}
              </Section>
            ) : (
              <EmptyMessageCard
                sizePreset="main-ui"
                title={t("viewer.actions.empty.title")}
              />
            )}
          </Collapsible>

          {/* More Info (Collapsible) */}
          <Divider paddingParallel={0} paddingPerpendicular={0} />
          <Collapsible title={t("viewer.moreInfo.title")}>
            <Section gap={2} alignItems="start">
              {agent.system_prompt && (
                <Content
                  font="main-ui-action"
                  title={t("viewer.instructions.title")}
                  description={agent.system_prompt}
                />
              )}
              {defaultModel && (
                <InputHorizontal
                  title={t("viewer.defaultModel.title")}
                  description={t("viewer.defaultModel.description", {
                    appName,
                  })}
                >
                  <Text color="text-05">{defaultModel}</Text>
                </InputHorizontal>
              )}
              {agent.search_start_date && (
                <InputHorizontal
                  title={t("viewer.knowledgeCutoff.title")}
                  description={t("viewer.knowledgeCutoff.description")}
                >
                  <Text font="main-ui-mono" color="text-05">
                    {formatMmDdYyyy(agent.search_start_date)}
                  </Text>
                </InputHorizontal>
              )}
              <InputHorizontal
                title={t("viewer.overwritePrompts.title")}
                description={t("viewer.overwritePrompts.description")}
              >
                <InputSwitch
                  disabled
                  checked={agent.replace_base_system_prompt}
                />
              </InputHorizontal>
            </Section>
          </Collapsible>

          {/* Prompt Reminders */}
          {agent.task_prompt && (
            <>
              <Divider paddingParallel={0} paddingPerpendicular={0} />
              <Content
                font="main-content-emphasis"
                title={t("viewer.promptReminders.title")}
                description={agent.task_prompt}
              />
            </>
          )}

          {/* Conversation Starters */}
          {agent.starter_messages && agent.starter_messages.length > 0 && (
            <>
              <Divider paddingParallel={0} paddingPerpendicular={0} />
              <Content
                font="main-content-emphasis"
                title={t("viewer.conversationStarters.title")}
              />
              <div className="grid grid-cols-2 gap-1 w-full">
                {agent.starter_messages.map((starter, index) => (
                  <Interactive.Stateless
                    key={index}
                    onClick={() =>
                      handleStartChat({
                        message: starter.message,
                        mentions: [],
                      })
                    }
                    prominence="tertiary"
                  >
                    <Interactive.Container>
                      <Content
                        font="main-ui-body"
                        icon={SvgBubbleText}
                        title={starter.message}
                        titleColor="text-03"
                        width="full"
                      />
                    </Interactive.Container>
                  </Interactive.Stateless>
                ))}
              </div>
            </>
          )}
        </Modal.Body>
      </Modal.Content>
    </Modal>
  );
}
