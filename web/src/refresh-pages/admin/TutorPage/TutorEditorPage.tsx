"use client";

import { useCallback } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { SEARCH_PARAM_NAMES } from "@/app/app/services/searchParams";
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
import TutorKnowledgePane from "./TutorKnowledgePane";
import { useVectorDbEnabled } from "@/providers/SettingsProvider";
import { useAgents } from "@/hooks/useAgents";
import { useLabels } from "@/lib/hooks";
import { FullPersona } from "@/app/admin/agents/interfaces";
import ConfirmationModalLayout from "@/refresh-components/layouts/ConfirmationModalLayout";
import { useCreateModal } from "@/refresh-components/contexts/ModalContext";
import { deleteAgent } from "@/refresh-pages/admin/AgentsPage/svc";
import { useFormikContext } from "formik";
import {
  TEACHING_STYLES,
  TEACHING_STYLE_OPTIONS,
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
// Teaching Style Selector (inside Formik context)
// ---------------------------------------------------------------------------

function TeachingStyleSelector() {
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

  const selectedOption = TEACHING_STYLE_OPTIONS.find(
    (o) => o.value === values.teaching_style
  );

  return (
    <GeneralLayouts.Section gap={0.5}>
      <div className="flex gap-1">
        {TEACHING_STYLE_OPTIONS.map((option) => (
          <Button
            key={option.value}
            prominence={
              values.teaching_style === option.value ? "primary" : "secondary"
            }
            size="sm"
            type="button"
            onClick={() => handleStyleChange(option.value)}
          >
            {option.label}
          </Button>
        ))}
      </div>
      <Text as="p" secondaryBody text03>
        {selectedOption?.description ?? ""}
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
  const searchParams = useSearchParams();
  const { refresh: refreshAgents } = useAgents();
  const vectorDbEnabled = useVectorDbEnabled();
  const deleteModal = useCreateModal();

  const { labels, createLabel } = useLabels();

  // The course this tutor is being created/edited for, sourced from the live
  // LTI launch via a URL param. Required for new tutors — the editor refuses
  // to create a tutor that isn't bound to a course. Existing tutors keep
  // whatever course label they already carry.
  const ltiContextId =
    searchParams?.get(SEARCH_PARAM_NAMES.LTI_CONTEXT_ID) ?? null;
  const ltiCanvasCourseNodeIdRaw = searchParams?.get(
    SEARCH_PARAM_NAMES.LTI_CANVAS_COURSE_NODE_ID
  );
  const ltiCanvasCourseNodeId = ltiCanvasCourseNodeIdRaw
    ? parseInt(ltiCanvasCourseNodeIdRaw)
    : null;
  const isCreating = !existingTutor;
  const missingLtiContextOnCreate = isCreating && !ltiContextId;

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

  // Resolve or create the label whose name is the LTI `context.id`. That
  // label is what `find_tutor_personas_for_course` matches on at launch
  // time; we never let the admin type it.
  const getOrCreateCourseLabelId = useCallback(
    async (contextId: string): Promise<number | null> => {
      const trimmed = contextId.trim();
      if (!trimmed) return null;
      const existing = labels?.find((l) => l.name === trimmed);
      if (existing) return existing.id;
      const created = await createLabel(trimmed);
      return created?.id ?? null;
    },
    [labels, createLabel]
  );

  // The existing course label on a tutor being edited is whatever label
  // isn't the Virtual Tutor marker. It is preserved untouched on edit —
  // the editor never strips a course label.
  const existingCourseLabel = existingTutor?.labels?.find(
    (l) => l.name !== VIRTUAL_TUTOR_LABEL_NAME
  );

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
      getSystemPromptForStyle(TEACHING_STYLES.balanced),
    prompt_manually_edited: false,

    // Starter messages
    starter_messages: Array.from(
      { length: DEFAULT_STARTER_MESSAGES.length },
      (_, i) =>
        existingTutor?.starter_messages?.[i]?.message ??
        DEFAULT_STARTER_MESSAGES[i]?.message ??
        ""
    ),

    // Canvas knowledge — always enabled for tutors. The user picks which
    // folders / documents to scope the tutor to (none means "all of Canvas").
    document_ids: existingTutor?.attached_documents?.map((doc) => doc.id) ?? [],
    hierarchy_node_ids:
      existingTutor?.hierarchy_nodes?.map((node) => node.id) ?? [],
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
    document_ids: Yup.array().of(Yup.string()),
    hierarchy_node_ids: Yup.array().of(Yup.number()),
  });

  async function handleSubmit(values: typeof initialValues) {
    try {
      const starterMessages = values.starter_messages
        .filter((message: string) => message.trim() !== "")
        .map((message: string) => ({ message, name: message }));

      const finalStarterMessages =
        starterMessages.length > 0 ? starterMessages : null;

      const toolIds: number[] = [];
      if (vectorDbEnabled && searchTool) {
        toolIds.push(searchTool.id);
      }

      // Resolve labels to attach. The Virtual Tutor marker is always added.
      // For new tutors, the course label is the LTI context.id from the URL.
      // For existing tutors, we preserve every label as-is — the editor
      // never re-binds a tutor to a different course.
      const tutorLabelId = await getOrCreateTutorLabelId();
      const labelIdSet = new Set<number>();
      if (tutorLabelId !== null) labelIdSet.add(tutorLabelId);

      if (existingTutor) {
        for (const label of existingTutor.labels ?? []) {
          labelIdSet.add(label.id);
        }
      } else {
        if (!ltiContextId) {
          toast.error(
            "Cannot create a tutor without a course context. Launch the Onyx tool from the Canvas course you want to bind it to."
          );
          return;
        }
        const courseLabelId = await getOrCreateCourseLabelId(ltiContextId);
        if (courseLabelId === null) {
          toast.error("Failed to create the course label for this tutor.");
          return;
        }
        labelIdSet.add(courseLabelId);
      }
      const labelIds = labelIdSet.size > 0 ? Array.from(labelIdSet) : null;

      const submissionData: PersonaUpsertParameters = {
        name: values.name,
        description: values.description,
        system_prompt: values.system_prompt,
        replace_base_system_prompt: true,
        task_prompt: "",
        datetime_aware: false,
        document_set_ids: [],
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
        user_file_ids: [],
        hierarchy_node_ids: values.hierarchy_node_ids,
        document_ids: values.document_ids,
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

      // Send the user back where the editor was opened from. The editor is
      // launched from two places: from the in-app picker on `/tutor` (with
      // an `lti_context_id` URL param) and from the admin tutor list.
      const courseLabelName = existingTutor
        ? existingCourseLabel?.name
        : ltiContextId;
      if (courseLabelName) {
        const params = new URLSearchParams({
          [SEARCH_PARAM_NAMES.LTI_CONTEXT_ID]: courseLabelName,
        });
        if (ltiCanvasCourseNodeIdRaw) {
          params.set(
            SEARCH_PARAM_NAMES.LTI_CANVAS_COURSE_NODE_ID,
            ltiCanvasCourseNodeIdRaw
          );
        }
        router.push(`/tutor?${params.toString()}`);
      } else {
        router.push("/admin/tutor");
      }
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
      const courseLabelName = existingCourseLabel?.name;
      if (courseLabelName) {
        const params = new URLSearchParams({
          [SEARCH_PARAM_NAMES.LTI_CONTEXT_ID]: courseLabelName,
        });
        if (ltiCanvasCourseNodeIdRaw) {
          params.set(
            SEARCH_PARAM_NAMES.LTI_CANVAS_COURSE_NODE_ID,
            ltiCanvasCourseNodeIdRaw
          );
        }
        router.push(`/tutor?${params.toString()}`);
      } else {
        router.push("/admin/tutor");
      }
    } catch (err) {
      toast.error(
        err instanceof Error ? err.message : "Failed to delete tutor"
      );
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
                                : missingLtiContextOnCreate
                                  ? "Launch the Onyx tool from Canvas to bind this tutor to a course."
                                  : !isValid
                                    ? "Please fix the errors before saving."
                                    : !dirty
                                      ? "No changes have been made."
                                      : undefined
                            }
                            side="bottom"
                          >
                            <Disabled
                              disabled={
                                isSubmitting ||
                                !isValid ||
                                !dirty ||
                                missingLtiContextOnCreate
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
                      {missingLtiContextOnCreate && (
                        <div className="rounded-12 border border-status-warning-02 bg-status-warning-00 p-4">
                          <Text as="p" mainUiAction text05>
                            Launch the Onyx tool from Canvas to create a tutor
                          </Text>
                          <Text as="p" secondaryBody text03>
                            New tutors are bound to a Canvas course at creation.
                            To create one, open the Onyx tool from inside the
                            Canvas course you want to bind it to — the binding
                            is captured automatically from the launch.
                          </Text>
                        </div>
                      )}

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
                          description="Choose how the tutor interacts with students. More Socratic styles guide through questions; more direct styles provide explanations upfront."
                        >
                          <TeachingStyleSelector />
                        </InputLayouts.Vertical>
                      </GeneralLayouts.Section>

                      <Separator noPadding />

                      {/* Section 3: Canvas course materials */}
                      <TutorKnowledgePane
                        selectedDocumentIds={values.document_ids}
                        onDocumentIdsChange={(ids) =>
                          setFieldValue("document_ids", ids)
                        }
                        selectedFolderIds={values.hierarchy_node_ids}
                        onFolderIdsChange={(ids) =>
                          setFieldValue("hierarchy_node_ids", ids)
                        }
                        initialAttachedDocuments={
                          existingTutor?.attached_documents
                        }
                        canvasCourseNodeId={ltiCanvasCourseNodeId}
                        courseId={
                          existingTutor
                            ? existingCourseLabel?.name ?? null
                            : ltiContextId
                        }
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
                      <SimpleCollapsible defaultOpen={false}>
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
