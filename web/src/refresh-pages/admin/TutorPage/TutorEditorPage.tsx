"use client";

import { useCallback } from "react";
import { useRouter } from "next/navigation";
import * as SettingsLayouts from "@/layouts/settings-layouts";
import * as GeneralLayouts from "@/layouts/general-layouts";
import * as InputLayouts from "@/layouts/input-layouts";
import { Button } from "@opal/components";
import { Disabled } from "@opal/core";
import { Formik, Form, FieldArray } from "formik";
import * as Yup from "yup";
import InputTypeInField from "@/refresh-components/form/InputTypeInField";
import InputTextAreaField from "@/refresh-components/form/InputTextAreaField";
import InputTypeInElementField from "@/refresh-components/form/InputTypeInElementField";
import Separator from "@/refresh-components/Separator";
import SimpleCollapsible from "@/refresh-components/SimpleCollapsible";
import SimpleTooltip from "@/refresh-components/SimpleTooltip";
import Text from "@/refresh-components/texts/Text";
import { SvgBookOpen, SvgTrash } from "@opal/icons";
import { toast } from "@/hooks/useToast";
import {
  createPersona,
  updatePersona,
  PersonaUpsertParameters,
} from "@/app/admin/agents/lib";
import { useAvailableTools } from "@/hooks/useAvailableTools";
import { SEARCH_TOOL_ID } from "@/app/app/components/tools/constants";
import AgentKnowledgePane from "@/sections/knowledge/AgentKnowledgePane";
import { ValidSources } from "@/lib/types";
import { useVectorDbEnabled } from "@/providers/SettingsProvider";
import { useDocumentSets } from "@/app/admin/documents/sets/hooks";
import { useProjectsContext } from "@/providers/ProjectsContext";
import {
  ProjectFile,
  UserFileStatus,
} from "@/app/app/projects/projectsService";
import { useAgents } from "@/hooks/useAgents";
import { useLabels } from "@/lib/hooks";
import { FullPersona } from "@/app/admin/agents/interfaces";
import ConfirmationModalLayout from "@/refresh-components/layouts/ConfirmationModalLayout";
import { useCreateModal } from "@/refresh-components/contexts/ModalContext";
import { deleteAgent } from "@/refresh-pages/admin/AgentsPage/svc";
import { useFormikContext } from "formik";
import {
  TEACHING_STYLES,
  VIRTUAL_TUTOR_LABEL_NAME,
  DEFAULT_STARTER_MESSAGES,
  getSystemPromptForStyle,
  detectTeachingStyle,
  type TeachingStyle,
} from "./constants";
import {
  MAX_CHARACTERS_STARTER_MESSAGE,
  MAX_CHARACTERS_AGENT_DESCRIPTION,
} from "@/lib/constants";

// ---------------------------------------------------------------------------
// Teaching Style Toggle (inside Formik context)
// ---------------------------------------------------------------------------

function TeachingStyleToggle() {
  const { values, setFieldValue } = useFormikContext<{
    teaching_style: TeachingStyle;
    system_prompt: string;
    prompt_manually_edited: boolean;
  }>();

  function handleStyleChange(style: TeachingStyle) {
    setFieldValue("teaching_style", style);
    if (!values.prompt_manually_edited) {
      setFieldValue("system_prompt", getSystemPromptForStyle(style));
    }
  }

  return (
    <GeneralLayouts.Section gap={0.5}>
      <div className="flex gap-2">
        <Button
          prominence={
            values.teaching_style === TEACHING_STYLES.socratic
              ? "primary"
              : "secondary"
          }
          type="button"
          onClick={() => handleStyleChange(TEACHING_STYLES.socratic)}
        >
          Socratic (Guided)
        </Button>
        <Button
          prominence={
            values.teaching_style === TEACHING_STYLES.direct
              ? "primary"
              : "secondary"
          }
          type="button"
          onClick={() => handleStyleChange(TEACHING_STYLES.direct)}
        >
          Direct Answers
        </Button>
      </div>
      <Text as="p" secondaryBody text03>
        {values.teaching_style === TEACHING_STYLES.socratic
          ? "The tutor will guide students through reasoning with questions and hints rather than giving direct answers."
          : "The tutor will provide clear, thorough explanations and direct answers to student questions."}
      </Text>
    </GeneralLayouts.Section>
  );
}

// ---------------------------------------------------------------------------
// Starter Messages (inside Formik context)
// ---------------------------------------------------------------------------

const STARTER_PLACEHOLDERS = DEFAULT_STARTER_MESSAGES.map((s) => s.message);

function StarterMessages() {
  const { values } = useFormikContext<{ starter_messages: string[] }>();
  const starters = values.starter_messages || [];
  const maxStarters = STARTER_PLACEHOLDERS.length;
  const filledStarters = starters.filter((m: string) => m.trim() !== "").length;
  const canAddMore = filledStarters < maxStarters;

  const visibleCount = Math.min(
    maxStarters,
    Math.max(
      1,
      filledStarters === 0 ? 1 : filledStarters + (canAddMore ? 1 : 0)
    )
  );

  return (
    <FieldArray name="starter_messages">
      {(arrayHelpers) => (
        <GeneralLayouts.Section gap={0.5}>
          {Array.from({ length: visibleCount }, (_, i) => (
            <InputTypeInElementField
              key={`starter_messages.${i}`}
              name={`starter_messages.${i}`}
              placeholder={
                STARTER_PLACEHOLDERS[i] || "Enter a conversation starter..."
              }
              onRemove={() => arrayHelpers.remove(i)}
            />
          ))}
        </GeneralLayouts.Section>
      )}
    </FieldArray>
  );
}

// ---------------------------------------------------------------------------
// Main Component
// ---------------------------------------------------------------------------

export interface TutorEditorPageProps {
  tutor?: FullPersona;
  refreshTutor?: () => void;
}

export default function TutorEditorPage({
  tutor: existingTutor,
  refreshTutor,
}: TutorEditorPageProps) {
  const router = useRouter();
  const { refresh: refreshAgents } = useAgents();
  const vectorDbEnabled = useVectorDbEnabled();
  const deleteModal = useCreateModal();

  const { allRecentFiles, beginUpload } = useProjectsContext();
  const { data: documentSets } = useDocumentSets();
  const { labels, createLabel } = useLabels();

  const { tools: availableTools, isLoading: isToolsLoading } =
    useAvailableTools();
  const searchTool = availableTools?.find(
    (t) => t.in_code_tool_id === SEARCH_TOOL_ID
  );

  // Resolve or create the Virtual Tutor label
  const getOrCreateTutorLabelId = useCallback(async (): Promise<
    number | null
  > => {
    const existing = labels?.find((l) => l.name === VIRTUAL_TUTOR_LABEL_NAME);
    if (existing) return existing.id;
    const created = await createLabel(VIRTUAL_TUTOR_LABEL_NAME);
    return created?.id ?? null;
  }, [labels, createLabel]);

  const detectedStyle = detectTeachingStyle(
    existingTutor?.system_prompt ?? null
  );

  const initialValues = {
    name: existingTutor?.name ?? "",
    description: existingTutor?.description ?? "",

    // Teaching style
    teaching_style: detectedStyle as TeachingStyle,
    system_prompt:
      existingTutor?.system_prompt ??
      getSystemPromptForStyle(TEACHING_STYLES.socratic),
    prompt_manually_edited: false,

    // Starter messages
    starter_messages: Array.from(
      { length: DEFAULT_STARTER_MESSAGES.length },
      (_, i) =>
        existingTutor?.starter_messages?.[i]?.message ??
        DEFAULT_STARTER_MESSAGES[i]?.message ??
        ""
    ),

    // Knowledge
    enable_knowledge:
      (existingTutor?.document_sets?.length ?? 0) > 0 ||
      (existingTutor?.hierarchy_nodes?.length ?? 0) > 0 ||
      (existingTutor?.attached_documents?.length ?? 0) > 0 ||
      (existingTutor?.user_file_ids?.length ?? 0) > 0,
    document_set_ids: existingTutor?.document_sets?.map((ds) => ds.id) ?? [],
    document_ids: existingTutor?.attached_documents?.map((doc) => doc.id) ?? [],
    hierarchy_node_ids:
      existingTutor?.hierarchy_nodes?.map((node) => node.id) ?? [],
    user_file_ids: existingTutor?.user_file_ids ?? [],
    selected_sources: [] as ValidSources[],
  };

  const validationSchema = Yup.object().shape({
    name: Yup.string().required("Tutor name is required."),
    description: Yup.string()
      .max(
        MAX_CHARACTERS_AGENT_DESCRIPTION,
        `Description must be ${MAX_CHARACTERS_AGENT_DESCRIPTION} characters or less`
      )
      .optional(),
    system_prompt: Yup.string().optional(),
    starter_messages: Yup.array().of(
      Yup.string().max(
        MAX_CHARACTERS_STARTER_MESSAGE,
        `Conversation starter must be ${MAX_CHARACTERS_STARTER_MESSAGE} characters or less`
      )
    ),
    enable_knowledge: Yup.boolean(),
    document_set_ids: Yup.array().of(Yup.number()),
    document_ids: Yup.array().of(Yup.string()),
    hierarchy_node_ids: Yup.array().of(Yup.number()),
    user_file_ids: Yup.array().of(Yup.string()),
    selected_sources: Yup.array().of(Yup.string()),
  });

  async function handleSubmit(values: typeof initialValues) {
    try {
      const starterMessages = values.starter_messages
        .filter((message: string) => message.trim() !== "")
        .map((message: string) => ({ message, name: message }));

      const finalStarterMessages =
        starterMessages.length > 0 ? starterMessages : null;

      const toolIds: number[] = [];
      if (values.enable_knowledge && vectorDbEnabled && searchTool) {
        toolIds.push(searchTool.id);
      }

      // Get or create the Virtual Tutor label
      const tutorLabelId = await getOrCreateTutorLabelId();
      const existingLabelIds = existingTutor?.labels?.map((l) => l.id) ?? [];
      const labelIds = tutorLabelId
        ? Array.from(new Set([...existingLabelIds, tutorLabelId]))
        : existingLabelIds.length > 0
          ? existingLabelIds
          : null;

      const submissionData: PersonaUpsertParameters = {
        name: values.name,
        description: values.description,
        system_prompt: values.system_prompt,
        replace_base_system_prompt: true,
        task_prompt: "",
        datetime_aware: false,
        document_set_ids: values.enable_knowledge
          ? values.document_set_ids
          : [],
        is_public: true,
        llm_model_provider_override: null,
        llm_model_version_override: null,
        starter_messages: finalStarterMessages,
        groups: [],
        tool_ids: toolIds,
        search_start_date: null,
        uploaded_image_id: null,
        icon_name: null,
        is_featured: false,
        label_ids: labelIds,
        user_file_ids: values.enable_knowledge ? values.user_file_ids : [],
        hierarchy_node_ids: values.enable_knowledge
          ? values.hierarchy_node_ids
          : [],
        document_ids: values.enable_knowledge ? values.document_ids : [],
      };

      let personaResponse;
      if (existingTutor) {
        personaResponse = await updatePersona(existingTutor.id, submissionData);
      } else {
        personaResponse = await createPersona(submissionData);
      }

      if (!personaResponse || !personaResponse.ok) {
        const error = personaResponse
          ? await personaResponse.text()
          : "No response received";
        toast.error(
          `Failed to ${existingTutor ? "update" : "create"} tutor - ${error}`
        );
        return;
      }

      const agent = await personaResponse.json();
      toast.success(
        `Tutor "${agent.name}" ${
          existingTutor ? "updated" : "created"
        } successfully`
      );

      await refreshAgents();
      if (refreshTutor) {
        refreshTutor();
      }

      router.push("/admin/tutor");
    } catch (error) {
      console.error("Submit error:", error);
      toast.error(`An error occurred: ${error}`);
    }
  }

  async function handleDeleteTutor() {
    if (!existingTutor) return;

    try {
      await deleteAgent(existingTutor.id);
      toast.success("Tutor deleted successfully");
      deleteModal.toggle(false);
      await refreshAgents();
      router.push("/admin/tutor");
    } catch (err) {
      toast.error(
        err instanceof Error ? err.message : "Failed to delete tutor"
      );
    }
  }

  function handleFileClick(_file: ProjectFile) {
    // File preview is not used in tutor editor
  }

  async function handleUploadChange(
    e: React.ChangeEvent<HTMLInputElement>,
    currentFileIds: string[],
    setFieldValue: (field: string, value: unknown) => void
  ) {
    const files = e.target.files;
    if (!files || files.length === 0) return;
    try {
      let selectedIds = [...(currentFileIds || [])];
      const optimistic = await beginUpload(
        Array.from(files),
        null,
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

  if (isToolsLoading) {
    return null;
  }

  return (
    <>
      <div className="h-full w-full">
        <Formik
          initialValues={initialValues}
          validationSchema={validationSchema}
          onSubmit={handleSubmit}
          validateOnChange
          validateOnBlur
          validateOnMount
        >
          {({ isSubmitting, isValid, dirty, values, setFieldValue }) => {
            const fileStatusMap = new Map(
              allRecentFiles.map((f) => [f.id, f.status])
            );

            const hasUploadingFiles = values.user_file_ids.some(
              (fileId: string) => {
                const status = fileStatusMap.get(fileId);
                if (status === undefined) {
                  return fileId.startsWith("temp_");
                }
                return status === UserFileStatus.UPLOADING;
              }
            );

            const hasProcessingFiles = values.user_file_ids.some(
              (fileId: string) =>
                fileStatusMap.get(fileId) === UserFileStatus.PROCESSING
            );

            return (
              <>
                <deleteModal.Provider>
                  {deleteModal.isOpen && (
                    <ConfirmationModalLayout
                      icon={SvgTrash}
                      title="Delete Virtual Tutor"
                      submit={
                        <Button variant="danger" onClick={handleDeleteTutor}>
                          Delete Tutor
                        </Button>
                      }
                      onClose={() => deleteModal.toggle(false)}
                    >
                      <GeneralLayouts.Section alignItems="start" gap={0.5}>
                        <Text>
                          Students will no longer be able to access this tutor.
                          Deletion cannot be undone.
                        </Text>
                        <Text>Are you sure you want to delete this tutor?</Text>
                      </GeneralLayouts.Section>
                    </ConfirmationModalLayout>
                  )}
                </deleteModal.Provider>

                <Form className="h-full w-full">
                  <SettingsLayouts.Root>
                    <SettingsLayouts.Header
                      icon={SvgBookOpen}
                      title={
                        existingTutor
                          ? "Edit Virtual Tutor"
                          : "Create Virtual Tutor"
                      }
                      rightChildren={
                        <div className="flex gap-2">
                          <Button
                            prominence="secondary"
                            type="button"
                            onClick={() => router.back()}
                          >
                            Cancel
                          </Button>
                          <SimpleTooltip
                            tooltip={
                              isSubmitting
                                ? "Saving..."
                                : !isValid
                                  ? "Please fix the errors before saving."
                                  : !dirty
                                    ? "No changes have been made."
                                    : hasUploadingFiles
                                      ? "Please wait for files to finish uploading."
                                      : undefined
                            }
                            side="bottom"
                          >
                            <Disabled
                              disabled={
                                isSubmitting ||
                                !isValid ||
                                !dirty ||
                                hasUploadingFiles
                              }
                            >
                              <Button type="submit">
                                {existingTutor ? "Save" : "Deploy"}
                              </Button>
                            </Disabled>
                          </SimpleTooltip>
                        </div>
                      }
                      backButton
                      separator
                    />

                    <SettingsLayouts.Body>
                      {/* Section 1: Basics */}
                      <GeneralLayouts.Section>
                        <InputLayouts.Vertical name="name" title="Tutor Name">
                          <InputTypeInField
                            name="name"
                            placeholder="e.g. CS 101 Virtual Tutor"
                          />
                        </InputLayouts.Vertical>

                        <InputLayouts.Vertical
                          name="description"
                          title="Description"
                          suffix="optional"
                        >
                          <InputTextAreaField
                            name="description"
                            placeholder="Describe what this tutor helps students with"
                          />
                        </InputLayouts.Vertical>
                      </GeneralLayouts.Section>

                      <Separator noPadding />

                      {/* Section 2: Teaching Style */}
                      <GeneralLayouts.Section>
                        <InputLayouts.Vertical
                          name="teaching_style"
                          title="Teaching Style"
                          description="Choose how the tutor interacts with students."
                        >
                          <TeachingStyleToggle />
                        </InputLayouts.Vertical>
                      </GeneralLayouts.Section>

                      <Separator noPadding />

                      {/* Section 3: Knowledge Sources */}
                      <AgentKnowledgePane
                        enableKnowledge={values.enable_knowledge}
                        onEnableKnowledgeChange={(enabled) =>
                          setFieldValue("enable_knowledge", enabled)
                        }
                        selectedSources={values.selected_sources}
                        onSourcesChange={(sources) =>
                          setFieldValue("selected_sources", sources)
                        }
                        documentSets={documentSets ?? []}
                        selectedDocumentSetIds={values.document_set_ids}
                        onDocumentSetIdsChange={(ids) =>
                          setFieldValue("document_set_ids", ids)
                        }
                        selectedDocumentIds={values.document_ids}
                        onDocumentIdsChange={(ids) =>
                          setFieldValue("document_ids", ids)
                        }
                        selectedFolderIds={values.hierarchy_node_ids}
                        onFolderIdsChange={(ids) =>
                          setFieldValue("hierarchy_node_ids", ids)
                        }
                        selectedFileIds={values.user_file_ids}
                        onFileIdsChange={(ids) =>
                          setFieldValue("user_file_ids", ids)
                        }
                        allRecentFiles={allRecentFiles}
                        onFileClick={handleFileClick}
                        onUploadChange={(e) =>
                          handleUploadChange(
                            e,
                            values.user_file_ids,
                            setFieldValue
                          )
                        }
                        hasProcessingFiles={hasProcessingFiles}
                        initialAttachedDocuments={
                          existingTutor?.attached_documents
                        }
                        initialHierarchyNodes={existingTutor?.hierarchy_nodes}
                        vectorDbEnabled={vectorDbEnabled}
                      />

                      <Separator noPadding />

                      {/* Section 4: Starter Messages */}
                      <GeneralLayouts.Section>
                        <InputLayouts.Vertical
                          name="starter_messages"
                          title="Starter Messages"
                          description="Suggested prompts shown to students when they start a conversation."
                          suffix="optional"
                        >
                          <StarterMessages />
                        </InputLayouts.Vertical>
                      </GeneralLayouts.Section>

                      {/* Section 5: Advanced */}
                      <SimpleCollapsible>
                        <SimpleCollapsible.Header
                          title="Advanced"
                          description="Manually customize the system prompt given to the tutor."
                        />
                        <SimpleCollapsible.Content>
                          <GeneralLayouts.Section gap={0.5}>
                            <InputTextAreaField
                              name="system_prompt"
                              placeholder="Enter custom system prompt..."
                              onChange={() => {
                                setFieldValue("prompt_manually_edited", true);
                              }}
                            />
                            <Button
                              prominence="tertiary"
                              type="button"
                              onClick={() => {
                                setFieldValue("prompt_manually_edited", false);
                                setFieldValue(
                                  "system_prompt",
                                  getSystemPromptForStyle(values.teaching_style)
                                );
                              }}
                            >
                              Reset to Default
                            </Button>
                          </GeneralLayouts.Section>
                        </SimpleCollapsible.Content>
                      </SimpleCollapsible>

                      {/* Delete button for existing tutors */}
                      {existingTutor && (
                        <>
                          <Separator noPadding />
                          <Button
                            variant="danger"
                            prominence="tertiary"
                            icon={SvgTrash}
                            type="button"
                            onClick={() => deleteModal.toggle(true)}
                          >
                            Delete Tutor
                          </Button>
                        </>
                      )}
                    </SettingsLayouts.Body>
                  </SettingsLayouts.Root>
                </Form>
              </>
            );
          }}
        </Formik>
      </div>
    </>
  );
}
