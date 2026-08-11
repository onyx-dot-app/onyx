"use client";

import { Text } from "@opal/components";
import { useActiveProject } from "@/lib/projects/hooks";
import useAppFocus from "@/hooks/useAppFocus";
import { SvgFolder } from "@opal/icons";

/**
 * The active project's name for the app header, so a chat inside a project says
 * which one. Nothing else surfaces this — `projectId` is dropped from the URL
 * once a chat opens (see `PARAMS_TO_SKIP` in `app/app/services/lib.tsx`).
 *
 * Chats only. The project page already names itself in `ProjectContextPanel`,
 * so repeating it in the header would be noise.
 *
 * Resolves the active project itself and renders nothing when there is none, so
 * callers can mount it unconditionally.
 *
 * A label, not navigation — the header states where you are and nothing more.
 */
export function ActiveProjectBreadcrumb() {
  const appFocus = useAppFocus();
  const project = useActiveProject();

  if (!appFocus.isChat() || !project) return null;

  return (
    <div className="p-2 flex flex-row items-center gap-0.5">
      <div className="p-0.5">
        <SvgFolder className="text-text-03" size={16} />
      </div>

      <div className="px-1">
        <Text nowrap as="p">
          {project.name}
        </Text>
      </div>
    </div>
  );
}
