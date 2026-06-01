import { useCallback } from "react";
import { Alert } from "react-native";

import { useDeleteProject } from "@/query/projects";
import { useProjectChatTarget } from "@/state/projectChatTarget";

// Shared "Delete Project" confirmation. On confirm, drops any pending project-chat
// launcher targeting this project (so the next draft can't be sent with a deleted
// project_id) before the optimistic delete. `onDeleted` runs after enqueue.
export function useConfirmDeleteProject() {
  const deleteProject = useDeleteProject();

  return useCallback(
    (projectId: number, onDeleted?: () => void) => {
      Alert.alert(
        "Delete Project",
        "Are you sure you want to delete this project? This action cannot be undone.",
        [
          { text: "Cancel", style: "cancel" },
          {
            text: "Delete",
            style: "destructive",
            onPress: () => {
              if (useProjectChatTarget.getState().projectId === projectId) {
                useProjectChatTarget.getState().clear();
              }
              deleteProject.mutate(projectId);
              onDeleted?.();
            },
          },
        ],
      );
    },
    [deleteProject],
  );
}
