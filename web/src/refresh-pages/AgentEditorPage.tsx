"use client";

import { useState, useRef } from "react";
import { useRouter } from "next/navigation";
import * as SettingsLayouts from "@/layouts/settings-layouts";
import Button from "@/refresh-components/buttons/Button";
import { FullPersona } from "@/app/admin/assistants/interfaces";
import { buildImgUrl } from "@/app/chat/components/files/images/utils";
import { cn } from "@/lib/utils";
import { Formik, Form, FieldArray } from "formik";
import * as Yup from "yup";
import InputTypeInField from "@/refresh-components/form/InputTypeInField";
import InputTextAreaField from "@/refresh-components/form/InputTextAreaField";
import InputTypeInElementField from "@/refresh-components/form/InputTypeInElementField";
import Separator from "@/refresh-components/Separator";
import * as InputLayouts from "@/layouts/input-layouts";
import { useFormikContext } from "formik";
import { CONVERSATION_STARTERS } from "@/lib/constants";
import Text from "@/refresh-components/texts/Text";
import Card from "@/refresh-components/Card";
import SimpleCollapsible from "@/refresh-components/SimpleCollapsible";
import SwitchField from "@/refresh-components/form/SwitchField";
import InputSelectField from "@/refresh-components/form/InputSelectField";
import InputSelect from "@/refresh-components/inputs/InputSelect";
import { useDocumentSets } from "@/app/admin/documents/sets/hooks";
import { useProjectsContext } from "@/app/chat/projects/ProjectsContext";
import { useCreateModal } from "@/refresh-components/contexts/ModalContext";
import { usePopup } from "@/components/admin/connectors/Popup";
import { DocumentSetSelectable } from "@/components/documentSet/DocumentSetSelectable";
import FilePickerPopover from "@/refresh-components/popovers/FilePickerPopover";
import { FileCard } from "@/app/chat/components/input/FileCard";
import UserFilesModal from "@/components/modals/UserFilesModal";
import {
  ProjectFile,
  UserFileStatus,
} from "@/app/chat/projects/projectsService";
import CreateButton from "@/refresh-components/buttons/CreateButton";
import {
  Popover,
  PopoverTrigger,
  PopoverContent,
  PopoverMenu,
} from "@/components/ui/popover";
import LineItem from "@/refresh-components/buttons/LineItem";
import { SvgImage, SvgOnyxOctagon } from "@opal/icons";
import CustomAgentAvatar, {
  agentAvatarIconMap,
} from "@/refresh-components/avatars/CustomAgentAvatar";
import InputAvatar from "@/refresh-components/inputs/InputAvatar";
import SquareButton from "@/refresh-components/buttons/SquareButton";
import { useAgents } from "@/hooks/useAgents";
import {
  createPersona,
  updatePersona,
  PersonaUpsertParameters,
} from "@/app/admin/assistants/lib";
import useMcpServers from "@/hooks/useMcpServers";
import useOpenApiTools from "@/hooks/useOpenApiTools";
import MCPActionCard from "@/sections/actions/MCPActionCard";
import OpenApiActionCard from "@/sections/actions/OpenApiActionCard";
import { getActionIcon } from "@/lib/tools/mcpUtils";
import {
  ActionStatus,
  MCPServerStatus,
  MCPServer,
  ToolSnapshot,
} from "@/lib/tools/interfaces";

interface AgentIconEditorProps {
  existingAgent?: FullPersona | null;
}

function AgentIconEditor({ existingAgent }: AgentIconEditorProps) {
  const { values, setFieldValue } = useFormikContext<{
    name: string;
    icon_name: string | null;
    uploaded_image_id: string | null;
    remove_image: boolean | null;
  }>();
  const [uploadedImagePreview, setUploadedImagePreview] = useState<
    string | null
  >(null);
  const [popoverOpen, setPopoverOpen] = useState(false);
  const fileInputRef = useRef<HTMLInputElement | null>(null);

  async function handleImageUpload(e: React.ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0];
    if (!file) return;

    // Clear previous preview to free memory
    setUploadedImagePreview(null);

    // Clear selected icon and remove_image flag when uploading an image
    setFieldValue("icon_name", null);
    setFieldValue("remove_image", false);

    // Show preview immediately
    const reader = new FileReader();
    reader.onloadend = () => {
      setUploadedImagePreview(reader.result as string);
    };
    reader.readAsDataURL(file);

    // Upload the file
    try {
      const formData = new FormData();
      formData.append("file", file);
      const response = await fetch("/api/admin/persona/upload-image", {
        method: "POST",
        body: formData,
      });

      if (!response.ok) {
        console.error("Failed to upload image");
        setUploadedImagePreview(null);
        return;
      }

      const { file_id } = await response.json();
      setFieldValue("uploaded_image_id", file_id);
      setPopoverOpen(false);
    } catch (error) {
      console.error("Upload error:", error);
      setUploadedImagePreview(null);
    }
  }

  const imageSrc = uploadedImagePreview
    ? uploadedImagePreview
    : values.uploaded_image_id
      ? buildImgUrl(values.uploaded_image_id)
      : values.icon_name
        ? undefined
        : values.remove_image
          ? undefined
          : existingAgent?.uploaded_image_id
            ? buildImgUrl(existingAgent.uploaded_image_id)
            : undefined;

  function handleIconClick(iconName: string | null) {
    setFieldValue("icon_name", iconName);
    setFieldValue("uploaded_image_id", null);
    setFieldValue("remove_image", true);
    setUploadedImagePreview(null);
    setPopoverOpen(false);

    // Reset the file input so the same file can be uploaded again later
    if (fileInputRef.current) {
      fileInputRef.current.value = "";
    }
  }

  return (
    <>
      <input
        ref={fileInputRef}
        type="file"
        accept="image/*"
        onChange={handleImageUpload}
        className="hidden"
      />

      <Popover open={popoverOpen} onOpenChange={setPopoverOpen}>
        <PopoverTrigger asChild>
          <InputAvatar className="group/InputAvatar relative flex flex-col items-center justify-center h-[7.5rem] w-[7.5rem]">
            {/* We take the `InputAvatar`'s height/width (in REM) and multiply it by 16 (the REM -> px conversion factor). */}
            <CustomAgentAvatar
              size={imageSrc ? 7.5 * 16 : 40}
              src={imageSrc}
              iconName={values.icon_name ?? undefined}
              name={values.name}
            />
            <Button
              className="absolute bottom-0 left-1/2 -translate-x-1/2 h-[1.75rem] mb-2 invisible group-hover/InputAvatar:visible"
              secondary
            >
              Edit
            </Button>
          </InputAvatar>
        </PopoverTrigger>
        <PopoverContent>
          <PopoverMenu medium>
            {[
              <LineItem
                key="upload-image"
                icon={SvgImage}
                onClick={() => fileInputRef.current?.click()}
                emphasized
              >
                Upload Image
              </LineItem>,
              null,
              <div className="grid grid-cols-4 gap-1">
                <SquareButton
                  key="default-icon"
                  icon={() => (
                    <CustomAgentAvatar name={values.name} size={30} />
                  )}
                  onClick={() => handleIconClick(null)}
                  transient={!imageSrc && values.icon_name === null}
                />
                {Object.keys(agentAvatarIconMap).map((iconName) => (
                  <SquareButton
                    key={iconName}
                    onClick={() => handleIconClick(iconName)}
                    icon={() => (
                      <CustomAgentAvatar iconName={iconName} size={30} />
                    )}
                    transient={values.icon_name === iconName}
                  />
                ))}
              </div>,
            ]}
          </PopoverMenu>
        </PopoverContent>
      </Popover>
    </>
  );
}

function Section({
  className,
  ...rest
}: React.HtmlHTMLAttributes<HTMLDivElement>) {
  return (
    <div className={cn("flex flex-col gap-4 w-full", className)} {...rest} />
  );
}

function ConversationStarters() {
  const max_starters = CONVERSATION_STARTERS.length;

  const { values } = useFormikContext<{
    conversation_starters: string[];
  }>();

  const starters = values.conversation_starters || [];

  // Count how many non-empty starters we have
  const filledStarters = starters.filter((s) => s).length;
  const canAddMore = filledStarters < max_starters;

  // Show at least 1, or all filled ones, or filled + 1 empty (up to max)
  const visibleCount = Math.min(
    max_starters,
    Math.max(
      1,
      filledStarters === 0 ? 1 : filledStarters + (canAddMore ? 1 : 0)
    )
  );

  return (
    <FieldArray name="conversation_starters">
      {(arrayHelpers) => (
        <div className="flex flex-col gap-2">
          {Array.from({ length: visibleCount }, (_, i) => (
            <InputTypeInElementField
              key={`conversation_starters.${i}`}
              name={`conversation_starters.${i}`}
              placeholder={
                CONVERSATION_STARTERS[i] || "Enter a conversation starter..."
              }
              onRemove={() => arrayHelpers.remove(i)}
            />
          ))}
        </div>
      )}
    </FieldArray>
  );
}

export interface AgentEditorPageProps {
  agent?: FullPersona;
  refreshAgent?: () => void;
}

export default function AgentEditorPage({
  agent: existingAgent,
  refreshAgent,
}: AgentEditorPageProps) {
  const router = useRouter();
  const { popup, setPopup } = usePopup();
  const { refresh: refreshAgents } = useAgents();

  // Hooks for Knowledge section
  const { allRecentFiles, beginUpload } = useProjectsContext();
  const { data: documentSets } = useDocumentSets();
  const userFilesModal = useCreateModal();
  const [presentingDocument, setPresentingDocument] = useState<{
    document_id: string;
    semantic_identifier: string;
  } | null>(null);

  const { mcpData } = useMcpServers();
  const { openApiTools, mutateOpenApiTools } = useOpenApiTools();

  // Helper to determine action status from server status
  const getActionStatusForServer = (server: MCPServer): ActionStatus => {
    if (server.status === MCPServerStatus.CONNECTED) {
      return ActionStatus.CONNECTED;
    } else if (
      server.status === MCPServerStatus.AWAITING_AUTH ||
      server.status === MCPServerStatus.CREATED
    ) {
      return ActionStatus.PENDING;
    } else if (server.status === MCPServerStatus.FETCHING_TOOLS) {
      return ActionStatus.FETCHING;
    }
    return ActionStatus.DISCONNECTED;
  };

  const initialValues = {
    // General
    icon_name: existingAgent?.icon_name ?? null,
    uploaded_image_id: existingAgent?.uploaded_image_id ?? null,
    remove_image: false,
    name: existingAgent?.name ?? "",
    description: existingAgent?.description ?? "",

    // Prompts
    instructions: existingAgent?.system_prompt ?? "",
    conversation_starters: Array.from(
      { length: CONVERSATION_STARTERS.length },
      (_, i) => existingAgent?.starter_messages?.[i]?.message ?? ""
    ),

    // Knowledge - enabled if there are doc sets, user files, OR num_chunks is set
    enable_knowledge: (() => {
      const hasDocSets = (existingAgent?.document_sets?.length ?? 0) > 0;
      const hasUserFiles = (existingAgent?.user_file_ids?.length ?? 0) > 0;
      const hasNumChunks =
        existingAgent?.num_chunks !== null &&
        existingAgent?.num_chunks !== undefined;
      return hasDocSets || hasUserFiles || hasNumChunks;
    })(),
    knowledge_source:
      existingAgent?.user_file_ids && existingAgent.user_file_ids.length > 0
        ? "user_knowledge"
        : ("team_knowledge" as "team_knowledge" | "user_knowledge"),
    document_set_ids: existingAgent?.document_sets?.map((ds) => ds.id) ?? [],
    user_file_ids: existingAgent?.user_file_ids ?? [],
    num_chunks: existingAgent?.num_chunks ?? null,

    // Access
    general_access:
      existingAgent?.is_public === false ? "restricted" : "public",
    feature_this_agent: false,

    // Advanced
    knowledge_cutoff_date: new Date(),
    current_datetime_aware: false,
    overwrite_system_prompts: false,
    reminders: "",
    image_generation: false,
    web_search: false,
    code_interpreter: false,
  };

  const validationSchema = Yup.object().shape({
    // General
    icon_name: Yup.string().nullable(),
    remove_image: Yup.boolean().optional(),
    uploaded_image_id: Yup.string().nullable(),
    name: Yup.string().required("Agent name is required."),
    description: Yup.string().required("Description is required."),

    // Prompts
    instructions: Yup.string().optional(),
    conversation_starters: Yup.array().of(Yup.string()),

    // Knowledge
    enable_knowledge: Yup.boolean(),
    knowledge_source: Yup.string().oneOf(["team_knowledge", "user_knowledge"]),
    document_set_ids: Yup.array().of(Yup.number()),
    user_file_ids: Yup.array().of(Yup.string()),
    num_chunks: Yup.number().nullable().positive().integer(),

    // Access
    general_access: Yup.string().oneOf(["restricted", "public"]).required(),
    feature_this_agent: Yup.boolean(),

    // Advanced
    knowledge_cutoff_date: Yup.date().optional(),
    current_datetime_aware: Yup.boolean(),
    overwrite_system_prompts: Yup.boolean(),
    reminders: Yup.string().optional(),
    image_generation: Yup.boolean(),
    web_search: Yup.boolean(),
    code_interpreter: Yup.boolean(),
  });

  const handleSubmit = async (values: typeof initialValues) => {
    try {
      // Map conversation starters
      const starterMessages = values.conversation_starters
        .filter((message: string) => message.trim() !== "")
        .map((message: string) => ({
          message: message,
          name: message,
        }));

      // Send null instead of empty array if no starter messages
      const finalStarterMessages =
        starterMessages.length > 0 ? starterMessages : null;

      // Determine knowledge settings
      const teamKnowledge = values.knowledge_source === "team_knowledge";
      const numChunks = values.enable_knowledge ? values.num_chunks || 25 : 0;

      // Build submission data
      const submissionData: PersonaUpsertParameters = {
        name: values.name,
        description: values.description,
        system_prompt: values.instructions,
        task_prompt: "",
        datetime_aware: values.current_datetime_aware,
        document_set_ids:
          teamKnowledge && values.enable_knowledge
            ? values.document_set_ids
            : [],
        user_file_ids:
          !teamKnowledge && values.enable_knowledge ? values.user_file_ids : [],
        num_chunks: numChunks,
        is_public: values.general_access === "public",
        llm_relevance_filter: false,
        llm_model_provider_override: null,
        llm_model_version_override: null,
        starter_messages: finalStarterMessages,
        users: undefined, // TODO: Handle restricted access users
        groups: [], // TODO: Handle groups
        tool_ids: [], // Temporarily empty - will add back later
        remove_image: values.remove_image ?? false,
        search_start_date: null,
        uploaded_image: null, // Already uploaded separately
        uploaded_image_id: values.uploaded_image_id,
        icon_name: values.icon_name,
        is_default_persona: false,
        label_ids: null,
      };

      // Call API
      let personaResponse;
      if (existingAgent) {
        personaResponse = await updatePersona(existingAgent.id, submissionData);
      } else {
        personaResponse = await createPersona(submissionData);
      }

      // Handle response
      if (!personaResponse || !personaResponse.ok) {
        const error = personaResponse
          ? await personaResponse.text()
          : "No response received";
        setPopup({
          type: "error",
          message: `Failed to ${
            existingAgent ? "update" : "create"
          } agent - ${error}`,
        });
        return;
      }

      // Success
      const agent = await personaResponse.json();
      setPopup({
        type: "success",
        message: `Agent "${agent.name}" ${
          existingAgent ? "updated" : "created"
        } successfully`,
      });

      // Refresh agents list and the specific agent
      await refreshAgents();
      if (refreshAgent) {
        await refreshAgent();
      }

      // Navigate back
      router.push("/chat/agents");
    } catch (error) {
      console.error("Submit error:", error);
      setPopup({
        type: "error",
        message: `An error occurred: ${error}`,
      });
    }
  };

  // FilePickerPopover callbacks - defined outside render to avoid inline functions
  function handlePickRecentFile(
    file: ProjectFile,
    currentFileIds: string[],
    setFieldValue: (field: string, value: any) => void
  ) {
    if (!currentFileIds.includes(file.id)) {
      setFieldValue("user_file_ids", [...currentFileIds, file.id]);
    }
  }

  function handleUnpickRecentFile(
    file: ProjectFile,
    currentFileIds: string[],
    setFieldValue: (field: string, value: any) => void
  ) {
    setFieldValue(
      "user_file_ids",
      currentFileIds.filter((id) => id !== file.id)
    );
  }

  function handleFileClick(file: ProjectFile) {
    setPresentingDocument({
      document_id: `project_file__${file.file_id}`,
      semantic_identifier: file.name,
    });
  }

  async function handleUploadChange(
    e: React.ChangeEvent<HTMLInputElement>,
    currentFileIds: string[],
    setFieldValue: (field: string, value: any) => void
  ) {
    const files = e.target.files;
    if (!files || files.length === 0) return;
    try {
      let selectedIds = [...(currentFileIds || [])];
      const optimistic = await beginUpload(
        Array.from(files),
        null,
        setPopup,
        (result) => {
          const uploadedFiles = result.user_files || [];
          if (uploadedFiles.length === 0) return;
          const tempToFinal = new Map(
            uploadedFiles
              .filter((f) => f.temp_id)
              .map((f) => [f.temp_id as string, f.id])
          );
          const replaced = (selectedIds || []).map(
            (id: string) => tempToFinal.get(id) ?? id
          );
          selectedIds = replaced;
          setFieldValue("user_file_ids", replaced);
        }
      );
      if (optimistic) {
        const optimisticIds = optimistic.map((f) => f.id);
        selectedIds = [...selectedIds, ...optimisticIds];
        setFieldValue("user_file_ids", selectedIds);
      }
    } catch (error) {
      console.error("Upload error:", error);
    }
  }

  return (
    <>
      {popup}

      <div
        data-testid="AgentsEditorPage/container"
        aria-label="Agents Editor Page"
        className="h-full w-full"
      >
        <Formik
          initialValues={initialValues}
          validationSchema={validationSchema}
          onSubmit={handleSubmit}
          validateOnChange={true}
          validateOnBlur={true}
          validateOnMount={true}
        >
          {({ isSubmitting, isValid, dirty, values, setFieldValue }) => (
            <>
              <userFilesModal.Provider>
                <UserFilesModal
                  title="User Files"
                  description="All files selected for this agent"
                  recentFiles={values.user_file_ids
                    .map((userFileId: string) => {
                      const rf = allRecentFiles.find(
                        (f) => f.id === userFileId
                      );
                      if (rf) return rf;
                      return {
                        id: userFileId,
                        name: `File ${userFileId.slice(0, 8)}`,
                        status: UserFileStatus.COMPLETED,
                        file_id: userFileId,
                        created_at: new Date().toISOString(),
                        project_id: null,
                        user_id: null,
                        file_type: "",
                        last_accessed_at: new Date().toISOString(),
                        chat_file_type: "file" as const,
                      } as unknown as ProjectFile;
                    })
                    .filter((f): f is ProjectFile => f !== null)}
                  selectedFileIds={values.user_file_ids}
                  onPickRecent={(file: ProjectFile) => {
                    if (!values.user_file_ids.includes(file.id)) {
                      setFieldValue("user_file_ids", [
                        ...values.user_file_ids,
                        file.id,
                      ]);
                    }
                  }}
                  onUnpickRecent={(file: ProjectFile) => {
                    setFieldValue(
                      "user_file_ids",
                      values.user_file_ids.filter((id) => id !== file.id)
                    );
                  }}
                  onView={(file: ProjectFile) => {
                    setPresentingDocument({
                      document_id: `project_file__${file.file_id}`,
                      semantic_identifier: file.name,
                    });
                  }}
                />
              </userFilesModal.Provider>

              <Form className="h-full w-full">
                <SettingsLayouts.Root>
                  <SettingsLayouts.Header
                    icon={SvgOnyxOctagon}
                    title={existingAgent ? "Edit Agent" : "Create Agent"}
                    rightChildren={
                      <div className="flex gap-2">
                        <Button
                          type="button"
                          secondary
                          onClick={() => router.back()}
                        >
                          Cancel
                        </Button>
                        <Button
                          type="submit"
                          disabled={isSubmitting || !isValid || !dirty}
                        >
                          {existingAgent ? "Save" : "Create"}
                        </Button>
                      </div>
                    }
                    backButton
                    separator
                  />

                  {/* Agent Form Content */}
                  <SettingsLayouts.Body>
                    <div className="flex flex-row gap-10 justify-between items-start w-full">
                      <Section>
                        <InputLayouts.Vertical name="name" label="Name">
                          <InputTypeInField
                            name="name"
                            placeholder="Name your agent"
                          />
                        </InputLayouts.Vertical>

                        <InputLayouts.Vertical
                          name="description"
                          label="Description"
                        >
                          <InputTextAreaField
                            name="description"
                            placeholder="What does this agent do?"
                          />
                        </InputLayouts.Vertical>
                      </Section>

                      <Section className="flex flex-col items-center w-fit gap-1">
                        <InputLayouts.Label
                          name="agent_avatar"
                          label="Agent Avatar"
                          className="w-fit"
                        />
                        <AgentIconEditor existingAgent={existingAgent} />
                      </Section>
                    </div>

                    <Separator noPadding />

                    <Section>
                      <InputLayouts.Vertical
                        name="instructions"
                        label="Instructions"
                        optional
                        description="Add instructions to tailor the response for this agent."
                      >
                        <InputTextAreaField
                          name="instructions"
                          placeholder="Think step by step and show reasoning for complex problems. Use specific examples. Emphasize action items, and leave blanks for the human to fill in when you have unknown. Use a polite enthusiastic tone."
                        />
                      </InputLayouts.Vertical>

                      <InputLayouts.Vertical
                        name="conversation_starters"
                        label="Conversation Starters"
                        description="Example messages that help users understand what this agent can do and how to interact with it effectively."
                        optional
                      >
                        <ConversationStarters />
                      </InputLayouts.Vertical>
                    </Section>

                    <Separator noPadding />

                    <Section>
                      <div className="flex flex-col gap-4">
                        <InputLayouts.Label
                          name="knowledge"
                          label="Knowledge"
                          description="Add specific connectors and documents for this agent should use to inform its responses."
                        />

                        <Card>
                          <InputLayouts.Horizontal
                            name="enable_knowledge"
                            label="Enable Knowledge"
                          >
                            <SwitchField name="enable_knowledge" />
                          </InputLayouts.Horizontal>

                          {values.enable_knowledge && (
                            <InputLayouts.Horizontal
                              name="knowledge_source"
                              label="Knowledge Source"
                              description="Choose the sources of truth this agent refers to."
                            >
                              <InputSelectField
                                name="knowledge_source"
                                className="w-full"
                              >
                                <InputSelect.Trigger />
                                <InputSelect.Content>
                                  <InputSelect.Item value="team_knowledge">
                                    Team Knowledge
                                  </InputSelect.Item>
                                  <InputSelect.Item value="user_knowledge">
                                    User Knowledge
                                  </InputSelect.Item>
                                </InputSelect.Content>
                              </InputSelectField>
                            </InputLayouts.Horizontal>
                          )}

                          {values.enable_knowledge &&
                            values.knowledge_source === "team_knowledge" &&
                            documentSets &&
                            (documentSets?.length ?? 0) > 0 && (
                              <div className="flex gap-2 flex-wrap">
                                {documentSets!.map((documentSet) => (
                                  <DocumentSetSelectable
                                    key={documentSet.id}
                                    documentSet={documentSet}
                                    isSelected={values.document_set_ids.includes(
                                      documentSet.id
                                    )}
                                    onSelect={() => {
                                      const index =
                                        values.document_set_ids.indexOf(
                                          documentSet.id
                                        );
                                      if (index !== -1) {
                                        const newIds = [
                                          ...values.document_set_ids,
                                        ];
                                        newIds.splice(index, 1);
                                        setFieldValue(
                                          "document_set_ids",
                                          newIds
                                        );
                                      } else {
                                        setFieldValue("document_set_ids", [
                                          ...values.document_set_ids,
                                          documentSet.id,
                                        ]);
                                      }
                                    }}
                                  />
                                ))}
                              </div>
                            )}

                          {values.enable_knowledge &&
                            values.knowledge_source === "user_knowledge" && (
                              <div className="flex flex-col gap-2">
                                <FilePickerPopover
                                  trigger={(open) => (
                                    <CreateButton transient={open}>
                                      Add User Files
                                    </CreateButton>
                                  )}
                                  selectedFileIds={values.user_file_ids}
                                  onPickRecent={(file) =>
                                    handlePickRecentFile(
                                      file,
                                      values.user_file_ids,
                                      setFieldValue
                                    )
                                  }
                                  onUnpickRecent={(file) =>
                                    handleUnpickRecentFile(
                                      file,
                                      values.user_file_ids,
                                      setFieldValue
                                    )
                                  }
                                  onFileClick={handleFileClick}
                                  handleUploadChange={(e) =>
                                    handleUploadChange(
                                      e,
                                      values.user_file_ids,
                                      setFieldValue
                                    )
                                  }
                                />

                                {values.user_file_ids.length > 0 && (
                                  <div className="flex flex-wrap gap-2">
                                    {values.user_file_ids.map((fileId) => {
                                      const file = allRecentFiles.find(
                                        (f) => f.id === fileId
                                      );
                                      if (!file) return null;

                                      return (
                                        <FileCard
                                          key={fileId}
                                          file={file}
                                          removeFile={(id: string) => {
                                            setFieldValue(
                                              "user_file_ids",
                                              values.user_file_ids.filter(
                                                (fid) => fid !== id
                                              )
                                            );
                                          }}
                                          onFileClick={(f: ProjectFile) => {
                                            setPresentingDocument({
                                              document_id: `project_file__${f.file_id}`,
                                              semantic_identifier: f.name,
                                            });
                                          }}
                                        />
                                      );
                                    })}
                                  </div>
                                )}
                              </div>
                            )}
                        </Card>
                      </div>
                    </Section>

                    <Separator noPadding />

                    <SimpleCollapsible
                      trigger={
                        <SimpleCollapsible.Header
                          title="Actions"
                          description="Tools and capabilities available for this agent to use."
                        />
                      }
                    >
                      <Section className="gap-2">
                        <Card>
                          <InputLayouts.Horizontal
                            name="image_generation"
                            label="Image Generation"
                            description="Generate and manipulate images using AI-powered tools."
                          >
                            <SwitchField name="image_generation" />
                          </InputLayouts.Horizontal>
                        </Card>

                        <Card>
                          <InputLayouts.Horizontal
                            name="web_search"
                            label="Web Search"
                            description="Search the web for real-time information and up-to-date results."
                          >
                            <SwitchField name="web_search" />
                          </InputLayouts.Horizontal>
                        </Card>

                        <Card>
                          <InputLayouts.Horizontal
                            name="code_interpreter"
                            label="Code Interpreter"
                            description="Generate and run code."
                          >
                            <SwitchField name="code_interpreter" />
                          </InputLayouts.Horizontal>
                        </Card>

                        <Separator noPadding className="py-1" />

                        {/* MCP tools */}
                        {mcpData &&
                          mcpData.mcp_servers &&
                          mcpData.mcp_servers.length > 0 && (
                            <div className="flex flex-col gap-2">
                              {mcpData.mcp_servers.map((server) => {
                                const status = getActionStatusForServer(server);
                                return (
                                  <MCPActionCard
                                    key={server.id}
                                    serverId={server.id}
                                    server={server}
                                    title={server.name}
                                    description={
                                      server.description || server.server_url
                                    }
                                    logo={getActionIcon(
                                      server.server_url,
                                      server.name
                                    )}
                                    status={status}
                                    toolCount={server.tool_count}
                                    initialExpanded={false}
                                  />
                                );
                              })}
                            </div>
                          )}

                        {/* OpenAPI tools */}
                        {openApiTools && openApiTools.length > 0 && (
                          <div className="flex flex-col gap-2">
                            {openApiTools.map((tool) => (
                              <OpenApiActionCard
                                key={tool.id}
                                tool={tool}
                                onAuthenticate={() => {}}
                                mutateOpenApiTools={mutateOpenApiTools}
                                setPopup={setPopup}
                              />
                            ))}
                          </div>
                        )}
                      </Section>
                    </SimpleCollapsible>

                    <Separator noPadding />

                    <SimpleCollapsible
                      trigger={
                        <SimpleCollapsible.Header
                          title="Advanced Options"
                          description="Fine-tune agent prompts and knowledge."
                        />
                      }
                    >
                      <Section>
                        <Card>
                          <InputLayouts.Horizontal
                            name="current_datetime_aware"
                            label="Current Datetime Aware"
                            description='Include the current date and time explicitly in the agent prompt (formatted as "Thursday Jan 1, 1970 00:01"). To inject it in a specific place in the prompt, use the pattern [[CURRENT_DATETIME]].'
                          >
                            <SwitchField name="current_datetime_aware" />
                          </InputLayouts.Horizontal>
                          <InputLayouts.Horizontal
                            name="overwrite_system_prompts"
                            label="Overwrite System Prompts"
                            description='Completely replace the base system prompt. This might affect response quality since it will also overwrite useful system instructions (e.g. "You (the LLM) can provide markdown and it will be rendered").'
                          >
                            <SwitchField name="overwrite_system_prompts" />
                          </InputLayouts.Horizontal>
                        </Card>

                        <div className="flex flex-col gap-1">
                          <InputLayouts.Vertical
                            name="reminders"
                            label="Reminders"
                          >
                            <InputTextAreaField
                              name="reminders"
                              placeholder="Remember, I want you to always format your response as a numbered list."
                            />
                          </InputLayouts.Vertical>
                          <Text text03 secondaryBody>
                            Append a brief reminder to the prompt messages. Use
                            this to remind the agent if you find that it tends
                            to forget certain instructions as the chat
                            progresses. This should be brief and not interfere
                            with the user messages.
                          </Text>
                        </div>
                      </Section>
                    </SimpleCollapsible>
                  </SettingsLayouts.Body>
                </SettingsLayouts.Root>
              </Form>
            </>
          )}
        </Formik>
      </div>
    </>
  );
}
