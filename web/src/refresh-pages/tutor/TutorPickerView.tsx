"use client";

import { useCallback, useEffect, useMemo } from "react";
import { useRouter } from "next/navigation";
import useSWR from "swr";
import { Button } from "@opal/components";
import { IllustrationContent } from "@opal/layouts";
import SvgNoResult from "@opal/illustrations/no-result";
import { SvgEdit, SvgPlus, SvgUsers } from "@opal/icons";
import type { Route } from "next";
import Text from "@/refresh-components/texts/Text";
import SimpleLoader from "@/refresh-components/loaders/SimpleLoader";
import AgentAvatar from "@/refresh-components/avatars/AgentAvatar";
import { errorHandlingFetcher } from "@/lib/fetcher";
import { useUser } from "@/providers/UserProvider";
import { SEARCH_PARAM_NAMES } from "@/app/app/services/searchParams";
import type { MinimalPersonaSnapshot } from "@/app/admin/agents/interfaces";
import TutorNoAgent from "@/refresh-pages/tutor/TutorNoAgent";
import { useEmbeddedMode } from "@/hooks/useEmbeddedMode";
import TutorTabHeader from "@/refresh-pages/tutor/TutorTabHeader";

interface TutorPickerViewProps {
  ltiContextId: string;
  projectId: number | null;
  ltiCanvasCourseNodeId: string | null;
  canManageTutors: boolean;
}

export default function TutorPickerView({
  ltiContextId,
  projectId,
  ltiCanvasCourseNodeId,
  canManageTutors,
}: TutorPickerViewProps) {
  const router = useRouter();
  const { isAdmin, isCurator } = useUser();
  const isEmbedded = useEmbeddedMode();
  const canManageCourseTutors = canManageTutors || isAdmin || isCurator;

  const swrKey = `/api/auth/lti/tutors-for-course?context_id=${encodeURIComponent(
    ltiContextId
  )}`;
  const { data, error, isLoading } = useSWR<MinimalPersonaSnapshot[]>(
    swrKey,
    errorHandlingFetcher
  );

  const tutors = useMemo(() => data ?? [], [data]);

  const buildTutorChatUrl = useCallback(
    (agentId: number) => {
      const params = new URLSearchParams();
      if (isEmbedded) params.set(SEARCH_PARAM_NAMES.EMBEDDED, "true");
      params.set(SEARCH_PARAM_NAMES.PERSONA_ID, String(agentId));
      params.set(SEARCH_PARAM_NAMES.LTI_CONTEXT_ID, ltiContextId);
      if (projectId !== null) {
        params.set(SEARCH_PARAM_NAMES.PROJECT_ID, String(projectId));
      }
      if (ltiCanvasCourseNodeId) {
        params.set(
          SEARCH_PARAM_NAMES.LTI_CANVAS_COURSE_NODE_ID,
          ltiCanvasCourseNodeId
        );
      }
      return `/tutor?${params.toString()}`;
    },
    [isEmbedded, ltiContextId, projectId, ltiCanvasCourseNodeId]
  );

  const buildEditTutorUrl = useCallback(
    (agentId: number) => {
      const params = new URLSearchParams();
      if (isEmbedded) params.set(SEARCH_PARAM_NAMES.EMBEDDED, "true");
      params.set(SEARCH_PARAM_NAMES.LTI_CONTEXT_ID, ltiContextId);
      if (ltiCanvasCourseNodeId) {
        params.set(
          SEARCH_PARAM_NAMES.LTI_CANVAS_COURSE_NODE_ID,
          ltiCanvasCourseNodeId
        );
      }
      if (projectId !== null) {
        params.set(SEARCH_PARAM_NAMES.PROJECT_ID, String(projectId));
      }
      return `/tutor/edit/${agentId}?${params.toString()}`;
    },
    [isEmbedded, ltiContextId, ltiCanvasCourseNodeId, projectId]
  );

  const buildCreateTutorUrl = useCallback(() => {
    const params = new URLSearchParams();
    if (isEmbedded) params.set(SEARCH_PARAM_NAMES.EMBEDDED, "true");
    params.set(SEARCH_PARAM_NAMES.LTI_CONTEXT_ID, ltiContextId);
    if (ltiCanvasCourseNodeId) {
      params.set(
        SEARCH_PARAM_NAMES.LTI_CANVAS_COURSE_NODE_ID,
        ltiCanvasCourseNodeId
      );
    }
    if (projectId !== null) {
      params.set(SEARCH_PARAM_NAMES.PROJECT_ID, String(projectId));
    }
    return `/tutor/create?${params.toString()}`;
  }, [isEmbedded, ltiContextId, ltiCanvasCourseNodeId, projectId]);

  const handleSelect = useCallback(
    (agentId: number) => {
      router.push(buildTutorChatUrl(agentId) as Route);
    },
    [router, buildTutorChatUrl]
  );

  // Students with exactly one tutor skip the picker and jump straight in.
  // Instructors always see the picker so they can manage their tutors.
  const soleStudentTutorId =
    !canManageCourseTutors && tutors.length === 1 ? tutors[0]!.id : null;
  useEffect(() => {
    if (soleStudentTutorId === null) return;
    router.replace(buildTutorChatUrl(soleStudentTutorId) as Route);
  }, [router, soleStudentTutorId, buildTutorChatUrl]);

  if (isLoading || soleStudentTutorId !== null) {
    return (
      <div className="h-full w-full flex items-center justify-center">
        <SimpleLoader className="h-6 w-6" />
      </div>
    );
  }

  if (error) {
    return (
      <div className="h-full w-full flex items-center justify-center p-8">
        <IllustrationContent
          illustration={SvgNoResult}
          title="Couldn't load tutors"
          description="Something went wrong loading the tutors for this course. Please refresh the page."
        />
      </div>
    );
  }

  // 0 tutors: instructors get a CTA, students see the no-agent state.
  if (tutors.length === 0) {
    if (!canManageCourseTutors) {
      return <TutorNoAgent />;
    }
    return (
      <div className="h-full w-full flex items-center justify-center p-8">
        <div className="flex flex-col items-center gap-4 max-w-[24rem] text-center">
          <IllustrationContent
            illustration={SvgNoResult}
            title="No tutors yet for this course"
            description="Create your first virtual tutor for this Canvas course. Students who launch from Canvas will land in the tutor automatically."
          />
          <Button
            icon={SvgPlus}
            onClick={() => router.push(buildCreateTutorUrl() as Route)}
          >
            Create your first tutor
          </Button>
        </div>
      </div>
    );
  }

  return (
    <div className="flex h-full min-h-0 w-full flex-col bg-background-tint-01">
      <TutorTabHeader
        icon={SvgUsers}
        title="Choose a tutor"
        description="Pick a virtual tutor to start a conversation. Multiple tutors may use different teaching styles."
        rightChildren={
          canManageCourseTutors ? (
            <Button
              icon={SvgPlus}
              onClick={() => router.push(buildCreateTutorUrl() as Route)}
            >
              New Tutor
            </Button>
          ) : undefined
        }
      />
      <div className="min-h-0 flex-1 overflow-y-auto">
        <div className="mx-auto w-full max-w-7xl p-4 md:p-6">
          <div className="grid grid-cols-1 gap-3 md:grid-cols-2">
            {tutors.map((tutor) => (
              <TutorPickerCard
                key={tutor.id}
                tutor={tutor}
                showInstructorActions={canManageCourseTutors}
                onSelect={() => handleSelect(tutor.id)}
                onEdit={() => router.push(buildEditTutorUrl(tutor.id) as Route)}
              />
            ))}
          </div>
        </div>
      </div>
    </div>
  );
}

interface TutorPickerCardProps {
  tutor: MinimalPersonaSnapshot;
  showInstructorActions: boolean;
  onSelect: () => void;
  onEdit: () => void;
}

function TutorPickerCard({
  tutor,
  showInstructorActions,
  onSelect,
  onEdit,
}: TutorPickerCardProps) {
  return (
    <button
      type="button"
      onClick={onSelect}
      className="group flex items-start gap-3 p-4 rounded-12 border border-border-01 bg-background-neutral-00 text-left hover:border-border-03 transition-colors"
    >
      <AgentAvatar agent={tutor} size={40} />
      <div className="flex-1 min-w-0 flex flex-col gap-1">
        <Text as="span" mainUiAction text05>
          {tutor.name}
        </Text>
        {tutor.description && (
          <Text as="span" secondaryBody text03>
            {tutor.description}
          </Text>
        )}
      </div>
      {showInstructorActions && (
        <Button
          prominence="tertiary"
          icon={SvgEdit}
          size="sm"
          tooltip="Edit tutor"
          onClick={(e) => {
            e.stopPropagation();
            onEdit();
          }}
        />
      )}
    </button>
  );
}
