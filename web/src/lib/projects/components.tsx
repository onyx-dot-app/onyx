"use client";

import { Text, TextColor } from "@opal/components";
import { useActiveProject } from "@/lib/projects/hooks";
import { SvgChevronRight } from "@opal/icons";

interface BreadcrumbWrapperProps {
  children: string;
  color?: TextColor;
}

function BreadcrumbWrapper({ children, color }: BreadcrumbWrapperProps) {
  return (
    <div className="p-1">
      <div className="py-0.5 px-1">
        <Text font="secondary-action" color={color} as="p" nowrap>
          {children}
        </Text>
      </div>
    </div>
  );
}

/**
 * "Projects / <name>" for the app header, so a chat inside a project says which
 * one. Nothing else surfaces this — `projectId` is dropped from the URL once a
 * chat opens (see `PARAMS_TO_SKIP` in `app/app/services/lib.tsx`).
 *
 * Resolves the active project itself and renders nothing when there is none, so
 * callers can mount it unconditionally.
 *
 * Deliberately a one-off rather than a general breadcrumb primitive — it is a
 * label, not navigation.
 */
export function ActiveProjectBreadcrumb() {
  const project = useActiveProject();

  if (!project) return null;

  return (
    <div className="p-1">
      <div className="pl-0.5 flex flex-row items-center gap-0.5">
        <BreadcrumbWrapper color="text-03">Projects</BreadcrumbWrapper>

        <div className="p-0.5">
          <SvgChevronRight className="text-text-02" size={12} />
        </div>

        <BreadcrumbWrapper>{project.name}</BreadcrumbWrapper>
      </div>
    </div>
  );
}
