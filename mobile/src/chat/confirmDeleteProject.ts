import { useCallback } from "react";
import { Alert } from "react-native";

import { useDeleteProject } from "@/query/projects";
import { useProjectChatTarget } from "@/state/projectChatTarget";

// Shared "Delete Project" confirmation. Pops the destructive Alert and, on confirm,
// drops any pending project-chat launcher that targeted this project (so the next
// draft can't be sent with a deleted project_id) before firing the optimistic
// delete mutation. An optional `onDeleted` runs after the mutation is enqueued — the
// project screen uses it to navigate back to the chat screen; the sidebar folder row
// passes nothing (it stays put).
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
