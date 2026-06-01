// Mirrors web's ProjectsContext + projectsService.ts. All endpoints under
// /user/projects/* take no /api prefix (see endpoints.ts).
import {
  useQuery,
  useMutation,
  useQueryClient,
} from "@tanstack/react-query";

import {
  errorHandlingFetcher,
  errorHandlingFetcherVoid,
  uploadChatFiles,
  type UploadableFile,
} from "@/lib/api";
import {
  UserFileStatus,
  type CategorizedFiles,
  type Project,
  type ProjectDetails,
  type ProjectFile,
} from "@/lib/types";
import { queryKeys } from "./keys";
import { clientConfig } from "./client";

export function useProjects() {
  return useQuery({
    queryKey: [queryKeys.userProjects],
    queryFn: () =>
      errorHandlingFetcher<Project[]>(queryKeys.userProjects, clientConfig),
  });
}

function hasPendingFile(details: ProjectDetails | undefined): boolean {
  const files = details?.files ?? [];
  return files.some(
    (f) =>
      f.status === UserFileStatus.UPLOADING ||
      f.status === UserFileStatus.PROCESSING ||
      f.status === UserFileStatus.DELETING,
  );
}

// Poll every 3s while any linked file is still resolving (web's targeted poller).
export function useProjectDetails(projectId: number | null) {
  return useQuery({
    queryKey: [queryKeys.projectDetails(projectId ?? 0)],
    queryFn: () =>
      errorHandlingFetcher<ProjectDetails>(
        queryKeys.projectDetails(projectId as number),
        clientConfig,
      ),
    enabled: projectId !== null,
    refetchInterval: (query) =>
      hasPendingFile(query.state.data as ProjectDetails | undefined)
        ? 3000
        : false,
  });
}

export function useCreateProject() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (name: string) =>
      errorHandlingFetcher<Project>(
        queryKeys.createProject(name.trim()),
        clientConfig,
        { method: "POST" },
      ),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: [queryKeys.userProjects] });
    },
  });
}

interface RenameProjectArgs {
  projectId: number;
  name: string;
}

interface RenameProjectContext {
  previousList?: Project[];
  previousDetails?: ProjectDetails;
}

export function useRenameProject() {
  const queryClient = useQueryClient();
  return useMutation<Project, Error, RenameProjectArgs, RenameProjectContext>({
    mutationFn: ({ projectId, name }) =>
      errorHandlingFetcher<Project>(
        queryKeys.userProject(projectId),
        clientConfig,
        {
          method: "PATCH",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ name }),
        },
      ),
    onMutate: async ({ projectId, name }) => {
      const listKey = [queryKeys.userProjects];
      const detailsKey = [queryKeys.projectDetails(projectId)];
      await queryClient.cancelQueries({ queryKey: listKey });
      await queryClient.cancelQueries({ queryKey: detailsKey });
      const previousList = queryClient.getQueryData<Project[]>(listKey);
      const previousDetails =
        queryClient.getQueryData<ProjectDetails>(detailsKey);
      if (previousList) {
        queryClient.setQueryData<Project[]>(
          listKey,
          previousList.map((p) => (p.id === projectId ? { ...p, name } : p)),
        );
      }
      if (previousDetails) {
        queryClient.setQueryData<ProjectDetails>(detailsKey, {
          ...previousDetails,
          project: { ...previousDetails.project, name },
        });
      }
      return { previousList, previousDetails };
    },
    onError: (_err, { projectId }, context) => {
      if (context?.previousList) {
        queryClient.setQueryData(
          [queryKeys.userProjects],
          context.previousList,
        );
      }
      if (context?.previousDetails) {
        queryClient.setQueryData(
          [queryKeys.projectDetails(projectId)],
          context.previousDetails,
        );
      }
    },
    onSettled: (_data, _err, { projectId }) => {
      queryClient.invalidateQueries({ queryKey: [queryKeys.userProjects] });
      queryClient.invalidateQueries({
        queryKey: [queryKeys.projectDetails(projectId)],
      });
    },
  });
}

interface DeleteProjectContext {
  previousList?: Project[];
}

export function useDeleteProject() {
  const queryClient = useQueryClient();
  return useMutation<void, Error, number, DeleteProjectContext>({
    mutationFn: (projectId: number) =>
      errorHandlingFetcherVoid(
        queryKeys.userProject(projectId),
        clientConfig,
        { method: "DELETE" },
      ),
    onMutate: async (projectId) => {
      const listKey = [queryKeys.userProjects];
      await queryClient.cancelQueries({ queryKey: listKey });
      const previousList = queryClient.getQueryData<Project[]>(listKey);
      if (previousList) {
        queryClient.setQueryData<Project[]>(
          listKey,
          previousList.filter((p) => p.id !== projectId),
        );
      }
      return { previousList };
    },
    onError: (_err, _projectId, context) => {
      if (context?.previousList) {
        queryClient.setQueryData(
          [queryKeys.userProjects],
          context.previousList,
        );
      }
    },
    onSettled: () => {
      queryClient.invalidateQueries({ queryKey: [queryKeys.userProjects] });
    },
  });
}

interface ProjectInstructionsResponse {
  instructions: string | null;
}

export function useUpsertProjectInstructions(projectId: number) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (instructions: string) =>
      errorHandlingFetcher<ProjectInstructionsResponse>(
        queryKeys.projectInstructions(projectId),
        clientConfig,
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ instructions }),
        },
      ),
    onSuccess: () => {
      queryClient.invalidateQueries({
        queryKey: [queryKeys.projectDetails(projectId)],
      });
    },
  });
}

// Link/unlink optimistically patch the details `files` array.
function setDetailsFiles(
  queryClient: ReturnType<typeof useQueryClient>,
  projectId: number,
  updater: (files: ProjectFile[]) => ProjectFile[],
): ProjectDetails | undefined {
  const key = [queryKeys.projectDetails(projectId)];
  const previous = queryClient.getQueryData<ProjectDetails>(key);
  if (previous) {
    queryClient.setQueryData<ProjectDetails>(key, {
      ...previous,
      files: updater(previous.files ?? []),
    });
  }
  return previous;
}

interface LinkFileContext {
  previous?: ProjectDetails;
}

export function useLinkFileToProject(projectId: number) {
  const queryClient = useQueryClient();
  return useMutation<unknown, Error, ProjectFile, LinkFileContext>({
    mutationFn: (file: ProjectFile) =>
      errorHandlingFetcher(
        queryKeys.projectFileLink(projectId, file.id),
        clientConfig,
        { method: "POST" },
      ),
    onMutate: async (file) => {
      const key = [queryKeys.projectDetails(projectId)];
      await queryClient.cancelQueries({ queryKey: key });
      const previous = setDetailsFiles(queryClient, projectId, (files) =>
        files.some((f) => f.id === file.id) ? files : [file, ...files],
      );
      return { previous };
    },
    onError: (_err, _file, context) => {
      if (context?.previous) {
        queryClient.setQueryData(
          [queryKeys.projectDetails(projectId)],
          context.previous,
        );
      }
    },
    onSettled: () => {
      queryClient.invalidateQueries({
        queryKey: [queryKeys.projectDetails(projectId)],
      });
      queryClient.invalidateQueries({ queryKey: [queryKeys.recentFiles] });
    },
  });
}

interface UnlinkFileContext {
  previous?: ProjectDetails;
}

export function useUnlinkFileFromProject(projectId: number) {
  const queryClient = useQueryClient();
  return useMutation<void, Error, string, UnlinkFileContext>({
    mutationFn: (fileId: string) =>
      errorHandlingFetcherVoid(
        queryKeys.projectFileLink(projectId, fileId),
        clientConfig,
        { method: "DELETE" },
      ),
    onMutate: async (fileId) => {
      const key = [queryKeys.projectDetails(projectId)];
      await queryClient.cancelQueries({ queryKey: key });
      const previous = setDetailsFiles(queryClient, projectId, (files) =>
        files.filter((f) => f.id !== fileId),
      );
      return { previous };
    },
    onError: (_err, _fileId, context) => {
      if (context?.previous) {
        queryClient.setQueryData(
          [queryKeys.projectDetails(projectId)],
          context.previous,
        );
      }
    },
    onSettled: () => {
      queryClient.invalidateQueries({
        queryKey: [queryKeys.projectDetails(projectId)],
      });
      queryClient.invalidateQueries({ queryKey: [queryKeys.recentFiles] });
    },
  });
}

export function useUploadProjectFiles(projectId: number) {
  const queryClient = useQueryClient();
  return useMutation<CategorizedFiles, Error, UploadableFile[]>({
    mutationFn: (files: UploadableFile[]) =>
      uploadChatFiles(files, clientConfig, projectId),
    onSettled: () => {
      queryClient.invalidateQueries({
        queryKey: [queryKeys.projectDetails(projectId)],
      });
      queryClient.invalidateQueries({ queryKey: [queryKeys.recentFiles] });
    },
  });
}
