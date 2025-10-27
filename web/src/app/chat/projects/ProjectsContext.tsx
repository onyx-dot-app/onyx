"use client";

import React, {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
  useRef,
  ReactNode,
  Dispatch,
  SetStateAction,
} from "react";
import type {
  CategorizedFiles,
  Project,
  ProjectFile,
  UserFileDeleteResult,
} from "./projectsService";
import {
  fetchProjects as svcFetchProjects,
  createProject as svcCreateProject,
  uploadFiles as svcUploadFiles,
  getRecentFiles as svcGetRecentFiles,
  getFilesInProject as svcGetFilesInProject,
  getProject as svcGetProject,
  getProjectInstructions as svcGetProjectInstructions,
  upsertProjectInstructions as svcUpsertProjectInstructions,
  getProjectDetails as svcGetProjectDetails,
  ProjectDetails,
  renameProject as svcRenameProject,
  deleteProject as svcDeleteProject,
  deleteUserFile as svcDeleteUserFile,
  getUserFileStatuses as svcGetUserFileStatuses,
  unlinkFileFromProject as svcUnlinkFileFromProject,
  linkFileToProject as svcLinkFileToProject,
  UserFileStatus,
} from "./projectsService";
import { useSearchParams } from "next/navigation";
import { SEARCH_PARAM_NAMES } from "@/app/chat/services/searchParams";
import { useAppRouter } from "@/hooks/appNavigation";
import { ChatFileType } from "../interfaces";
import { PopupSpec } from "@/components/admin/connectors/Popup";

export type { Project, ProjectFile } from "./projectsService";

// Helper to generate unique temp IDs
const generateTempId = () => {
  try {
    return `temp_${crypto.randomUUID()}`;
  } catch {
    // Extremely unlikely fallback
    return `temp_${Date.now()}_${Math.random().toString(36).slice(2, 11)}`;
  }
};

// Create optimistic file from File object
const createOptimisticFile = (
  file: File,
  projectId: number | null = null
): ProjectFile => {
  const tempId = generateTempId();
  return {
    id: tempId, // Use temp ID as the actual ID initially
    file_id: tempId,
    name: file.name,
    project_id: projectId,
    user_id: null,
    created_at: new Date().toISOString(),
    status: UserFileStatus.UPLOADING,
    file_type: file.type,
    last_accessed_at: new Date().toISOString(),
    chat_file_type: ChatFileType.DOCUMENT,
    token_count: null,
    chunk_count: null,
    temp_id: tempId, // Store temp_id for mapping later
  };
};

function buildFileKey(file: File): string {
  const namePrefix = (file.name ?? "").slice(0, 50);
  return `${file.size}|${namePrefix}`;
}

interface ProjectsContextType {
  projects: Project[];
  recentFiles: ProjectFile[];
  currentProjectDetails: ProjectDetails | null;
  currentProjectId: number | null;
  currentMessageFiles: ProjectFile[];
  beginUpload: (
    files: File[],
    projectId?: number | null,
    setPopup?: (popup: PopupSpec) => void,
    onSuccess?: (uploaded: CategorizedFiles) => void,
    onFailure?: (failedTempIds: string[]) => void
  ) => Promise<ProjectFile[]>;
  allRecentFiles: ProjectFile[];
  allCurrentProjectFiles: ProjectFile[];
  setCurrentMessageFiles: Dispatch<SetStateAction<ProjectFile[]>>;
  upsertInstructions: (instructions: string) => Promise<void>;
  fetchProjects: () => Promise<Project[]>;
  createProject: (name: string) => Promise<Project>;
  renameProject: (projectId: number, name: string) => Promise<Project>;
  deleteProject: (projectId: number) => Promise<void>;
  uploadFiles: (
    files: File[],
    projectId?: number | null
  ) => Promise<CategorizedFiles>;
  getRecentFiles: () => Promise<ProjectFile[]>;
  getFilesInProject: (projectId: number) => Promise<ProjectFile[]>;
  refreshCurrentProjectDetails: () => Promise<void>;
  refreshRecentFiles: () => Promise<void>;
  deleteUserFile: (fileId: string) => Promise<UserFileDeleteResult>;
  unlinkFileFromProject: (projectId: number, fileId: string) => Promise<void>;
  linkFileToProject?: (projectId: number, file: ProjectFile) => void;
  lastFailedFiles: ProjectFile[];
  clearLastFailedFiles: () => void;
}

const ProjectsContext = createContext<ProjectsContextType | undefined>(
  undefined
);

interface ProjectsProviderProps {
  children: ReactNode;
  initialProjects?: Project[];
}

export const ProjectsProvider: React.FC<ProjectsProviderProps> = ({
  children,
  initialProjects = [],
}) => {
  const [projects, setProjects] = useState<Project[]>(initialProjects);
  const [recentFiles, setRecentFiles] = useState<ProjectFile[]>([]);
  const [currentProjectDetails, setCurrentProjectDetails] =
    useState<ProjectDetails | null>(null);
  const searchParams = useSearchParams();
  const currentProjectIdRaw = searchParams.get(SEARCH_PARAM_NAMES.PROJECT_ID);
  const currentProjectId = currentProjectIdRaw
    ? Number.parseInt(currentProjectIdRaw)
    : null;
  const [currentMessageFiles, setCurrentMessageFiles] = useState<ProjectFile[]>(
    []
  );
  const pollIntervalRef = useRef<number | null>(null);
  const isPollingRef = useRef<boolean>(false);
  const [lastFailedFiles, setLastFailedFiles] = useState<ProjectFile[]>([]);
  const [trackedUploadIds, setTrackedUploadIds] = useState<Set<string>>(
    new Set()
  );
  const [allRecentFiles, setAllRecentFiles] = useState<ProjectFile[]>([]);
  const [allCurrentProjectFiles, setAllCurrentProjectFiles] = useState<
    ProjectFile[]
  >([]);
  const projectToUploadFilesMapRef = useRef<Map<number, ProjectFile[]>>(
    new Map()
  );
  const route = useAppRouter();

  const fetchProjects = useCallback(async (): Promise<Project[]> => {
    try {
      const data: Project[] = await svcFetchProjects();
      setProjects(data);
      return data;
    } catch (err) {
      const message =
        err instanceof Error ? err.message : "Failed to fetch projects";
      return [];
    }
  }, []);

  // Load full details for current project
  const refreshCurrentProjectDetails = useCallback(async () => {
    if (currentProjectId) {
      const details = await svcGetProjectDetails(currentProjectId);
      await fetchProjects();
      setCurrentProjectDetails(details);
      setAllCurrentProjectFiles(details.files || []);
      if (projectToUploadFilesMapRef.current.has(currentProjectId)) {
        setAllCurrentProjectFiles((prev) => [
          ...prev,
          ...(projectToUploadFilesMapRef.current.get(currentProjectId) || []),
        ]);
      }
    }
  }, [
    fetchProjects,
    currentProjectId,
    setCurrentProjectDetails,
    projectToUploadFilesMapRef,
  ]);

  const upsertInstructions = useCallback(
    async (instructions: string) => {
      if (!currentProjectId) {
        throw new Error("No project selected");
      }
      await svcUpsertProjectInstructions(currentProjectId, instructions);
      await refreshCurrentProjectDetails();
    },
    [currentProjectId, refreshCurrentProjectDetails]
  );

  const createProject = useCallback(
    async (name: string): Promise<Project> => {
      try {
        const project: Project = await svcCreateProject(name);
        // Navigate to the newly created project's page
        route({ projectId: project.id });
        // Refresh list to keep order consistent with backend
        await fetchProjects();
        return project;
      } catch (err) {
        const message =
          err instanceof Error ? err.message : "Failed to create project";
        throw err;
      }
    },
    [fetchProjects, route]
  );

  const renameProject = useCallback(
    async (projectId: number, name: string): Promise<Project> => {
      // Optimistically update the UI immediately
      setProjects((prev) =>
        prev.map((p) => (p.id === projectId ? { ...p, name } : p))
      );

      if (currentProjectId === projectId) {
        setCurrentProjectDetails((prev) =>
          prev ? { ...prev, project: { ...prev.project, name } } : prev
        );
      }

      try {
        const updated = await svcRenameProject(projectId, name);
        // Refresh to get canonical state from server
        await fetchProjects();
        if (currentProjectId === projectId) {
          await refreshCurrentProjectDetails();
        }
        return updated;
      } catch (err) {
        // Rollback optimistic update on failure
        await fetchProjects();
        if (currentProjectId === projectId) {
          await refreshCurrentProjectDetails();
        }
        const message =
          err instanceof Error ? err.message : "Failed to rename project";
        throw err;
      }
    },
    [fetchProjects, currentProjectId, refreshCurrentProjectDetails]
  );

  const deleteProject = useCallback(
    async (projectId: number): Promise<void> => {
      try {
        await svcDeleteProject(projectId);
        await fetchProjects();
        if (currentProjectId === projectId) {
          setCurrentProjectDetails(null);
          setAllCurrentProjectFiles([]);
          projectToUploadFilesMapRef.current.delete(projectId);
          route();
        }
      } catch (err) {
        throw err;
      }
    },
    [fetchProjects, currentProjectId, projectToUploadFilesMapRef, route]
  );

  const getRecentFiles = useCallback(async (): Promise<ProjectFile[]> => {
    try {
      const data: ProjectFile[] = await svcGetRecentFiles();
      return data;
    } catch (err) {
      const message =
        err instanceof Error ? err.message : "Failed to fetch recent files";
      return [];
    }
  }, []);

  const refreshRecentFiles = useCallback(async () => {
    const files = await getRecentFiles();
    setRecentFiles(files);
  }, [getRecentFiles]);

  const getTempIdMap = (files: File[], optimisticFiles: ProjectFile[]) => {
    const tempIdMap = new Map<string, string>();
    for (const f of files) {
      const tempId = optimisticFiles.find((o) => o.name === f.name)?.temp_id;
      if (tempId) {
        tempIdMap.set(buildFileKey(f), tempId);
      }
    }
    return tempIdMap;
  };

  const beginUpload = useCallback(
    async (
      files: File[],
      projectId?: number | null,
      setPopup?: (popup: PopupSpec) => void,
      onSuccess?: (uploaded: CategorizedFiles) => void,
      onFailure?: (failedTempIds: string[]) => void
    ): Promise<ProjectFile[]> => {
      const optimisticFiles = files.map((f) =>
        createOptimisticFile(f, projectId)
      );
      const tempIdMap = getTempIdMap(files, optimisticFiles);
      setAllRecentFiles((prev) => [...optimisticFiles, ...prev]);
      if (projectId) {
        setAllCurrentProjectFiles((prev) => [...optimisticFiles, ...prev]);
        projectToUploadFilesMapRef.current.set(projectId, optimisticFiles);
      }
      svcUploadFiles(files, projectId, tempIdMap)
        .then((uploaded) => {
          const uploadedFiles = uploaded.user_files || [];
          const tempIdToUploadedFileMap = new Map(
            uploadedFiles.map((f) => [f.temp_id, f])
          );

          setAllRecentFiles((prev) =>
            prev.map((f) => {
              if (f.temp_id) {
                const u = tempIdToUploadedFileMap.get(f.temp_id);
                return u ? { ...f, ...u } : f;
              }
              return f;
            })
          );
          setCurrentMessageFiles((prev) =>
            prev.map((f) => {
              if (f.temp_id) {
                const u = tempIdToUploadedFileMap.get(f.temp_id);
                return u ? { ...f, ...u } : f;
              }
              return f;
            })
          );
          if (projectId) {
            setAllCurrentProjectFiles((prev) =>
              prev.map((f) => {
                if (f.temp_id) {
                  const u = tempIdToUploadedFileMap.get(f.temp_id);
                  return u ? { ...f, ...u } : f;
                }
                return f;
              })
            );
            projectToUploadFilesMapRef.current.set(projectId, []);
          }
          const unsupported = uploaded.unsupported_files || [];
          const nonAccepted = uploaded.non_accepted_files || [];
          if (unsupported.length > 0 || nonAccepted.length > 0) {
            const detailsParts: string[] = [];
            if (unsupported.length > 0) {
              detailsParts.push(`Unsupported: ${unsupported.join(", ")}`);
            }
            if (nonAccepted.length > 0) {
              detailsParts.push(`Not accepted: ${nonAccepted.join(", ")}`);
            }
            setPopup?.({
              type: "warning",
              message: `Some files were not uploaded. ${detailsParts.join(
                " | "
              )}`,
            });

            const failedNameSet = new Set<string>([
              ...unsupported,
              ...nonAccepted,
            ]);
            const failedTempIds = Array.from(
              new Set(
                optimisticFiles
                  .filter((f) => f.temp_id && failedNameSet.has(f.name))
                  .map((f) => f.temp_id as string)
              )
            );
            if (failedTempIds.length > 0) {
              onFailure?.(failedTempIds);
            }
          }
          if (uploadedFiles.length > 0) {
            setTrackedUploadIds((prev) => {
              const next = new Set(prev);
              for (const f of uploadedFiles) next.add(f.id);
              return next;
            });
          }
          onSuccess?.(uploaded);
        })
        .catch((err) => {
          // Roll back optimistic inserts on failure
          const optimisticTempIds = new Set(
            optimisticFiles
              .map((f) => f.temp_id)
              .filter((id): id is string => Boolean(id))
          );

          // Remove from recent optimistic list
          setAllRecentFiles((prev) =>
            prev.filter((f) => !f.temp_id || !optimisticTempIds.has(f.temp_id))
          );

          // Remove from current message files if present
          setCurrentMessageFiles((prev) =>
            prev.filter((f) => !f.temp_id || !optimisticTempIds.has(f.temp_id))
          );

          // Remove from project optimistic list
          if (projectId) {
            setAllCurrentProjectFiles((prev) =>
              prev.filter(
                (f) => !f.temp_id || !optimisticTempIds.has(f.temp_id)
              )
            );
            // Clear the tracked optimistic files for this project
            projectToUploadFilesMapRef.current.delete(projectId);
          }

          setPopup?.({
            type: "error",
            message: "Failed to upload files",
          });

          onFailure?.(Array.from(optimisticTempIds));
        })
        .finally(() => {
          if (projectId && currentProjectId === projectId) {
            refreshCurrentProjectDetails();
          }
          refreshRecentFiles();
        });
      return optimisticFiles;
    },
    [currentProjectId, refreshCurrentProjectDetails, refreshRecentFiles]
  );

  const uploadFiles = useCallback(
    async (
      files: File[],
      projectId?: number | null
    ): Promise<CategorizedFiles> => {
      try {
        const uploaded: CategorizedFiles = await svcUploadFiles(
          files,
          projectId
        );
        const uploadedFiles = uploaded.user_files || [];
        // Track these uploaded file IDs for targeted polling
        if (uploadedFiles.length > 0) {
          setTrackedUploadIds((prev) => {
            const next = new Set(prev);
            for (const f of uploadedFiles) next.add(f.id);
            return next;
          });
        }

        // Refresh canonical sources instead of manual merges
        if (projectId && currentProjectId === projectId) {
          await refreshCurrentProjectDetails();
        }
        await refreshRecentFiles();
        return uploaded;
      } catch (err) {
        throw err;
      }
    },
    [currentProjectId, refreshCurrentProjectDetails, refreshRecentFiles]
  );

  const getFilesInProject = useCallback(
    async (projectId: number): Promise<ProjectFile[]> => {
      try {
        const data: ProjectFile[] = await svcGetFilesInProject(projectId);
        return data;
      } catch (err) {
        const message =
          err instanceof Error ? err.message : "Failed to fetch project files";
        return [];
      }
    },
    []
  );

  useEffect(() => {
    // Initial load - only fetch recent files since projects come from props
    getRecentFiles().then((recent) => {
      setRecentFiles(recent);
      setAllRecentFiles(recent);
    });
  }, [getRecentFiles]);

  useEffect(() => {
    setAllRecentFiles((prev) =>
      prev.map((f) => {
        const newFile = recentFiles.find((f2) => f2.id === f.id);
        return newFile ? { ...f, ...newFile } : f;
      })
    );
  }, [recentFiles]);

  useEffect(() => {
    if (currentProjectId) {
      refreshCurrentProjectDetails();
    }
  }, [currentProjectId, refreshCurrentProjectDetails]);

  // Targeted polling for tracked uploaded files only
  useEffect(() => {
    const ids = Array.from(trackedUploadIds);
    const shouldPoll = ids.length > 0;

    const poll = async () => {
      if (isPollingRef.current) return;
      isPollingRef.current = true;
      try {
        const statuses = await svcGetUserFileStatuses(ids);
        if (!statuses || statuses.length === 0) return;

        // Build maps for quick lookup
        const statusById = new Map(statuses.map((f) => [f.id, f]));

        // Update currentMessageFiles inline based on polled statuses
        setCurrentMessageFiles((prev) => {
          let changed = false;
          const next: ProjectFile[] = [];
          const newlyFailedLocal: ProjectFile[] = [];
          for (const f of prev) {
            const latest = statusById.get(f.id);
            if (latest) {
              const latestStatus = String(latest.status).toLowerCase();
              if (latestStatus === "failed") {
                if (String(f.status).toLowerCase() !== "failed") {
                  newlyFailedLocal.push(latest);
                }
                changed = true;
                continue;
              }
              if (
                latest.status !== f.status ||
                latest.name !== f.name ||
                latest.file_type !== f.file_type
              ) {
                next.push({ ...f, ...latest } as ProjectFile);
                changed = true;
                continue;
              }
            }
            next.push(f);
          }
          if (newlyFailedLocal.length > 0) {
            setLastFailedFiles(newlyFailedLocal);
          }
          return changed || next.length !== prev.length ? next : prev;
        });

        // Update currentProjectDetails.files with latest statuses
        setCurrentProjectDetails((prev) => {
          if (!prev || !prev.files || prev.files.length === 0) return prev;
          let changed = false;
          const nextFiles = prev.files.map((f) => {
            const latest = statusById.get(f.id);
            if (latest) {
              if (
                latest.status !== f.status ||
                latest.name !== f.name ||
                latest.file_type !== f.file_type
              ) {
                changed = true;
                return { ...f, ...latest } as ProjectFile;
              }
            }
            return f;
          });
          return changed
            ? ({ ...prev, files: nextFiles } as ProjectDetails)
            : prev;
        });

        // Update recent files list inline as well
        setRecentFiles((prev) => {
          if (prev.length === 0) return prev;
          let changed = false;
          const map = new Map(prev.map((f) => [f.id, f]));
          for (const latest of statuses) {
            const id = latest.id;
            if (map.has(id)) {
              const prevVal = map.get(id)!;
              if (
                latest.status !== prevVal.status ||
                latest.name !== prevVal.name ||
                latest.file_type !== prevVal.file_type
              ) {
                map.set(id, latest);
                changed = true;
              }
            }
          }
          return changed ? Array.from(map.values()) : prev;
        });

        // Remove completed/failed from tracking
        const remaining = new Set(trackedUploadIds);
        const newlyFailed: ProjectFile[] = [];
        for (const f of statuses) {
          const s = String(f.status).toLowerCase();
          if (s === "completed") {
            remaining.delete(f.id);
          } else if (s === "failed") {
            remaining.delete(f.id);
            newlyFailed.push(f);
          }
        }
        if (newlyFailed.length > 0) {
          setLastFailedFiles(newlyFailed);
        }
        const trackingChanged = remaining.size !== trackedUploadIds.size;
        if (trackingChanged) {
          setTrackedUploadIds(remaining);
        }

        // If all tracked uploads finished (completed or failed), do a single refresh
        if (remaining.size === 0) {
          if (currentProjectId) {
            await refreshCurrentProjectDetails();
          }
          await refreshRecentFiles();
        }
      } finally {
        isPollingRef.current = false;
      }
    };

    if (shouldPoll && pollIntervalRef.current === null) {
      // Kick once immediately, then start interval
      poll();
      pollIntervalRef.current = window.setInterval(poll, 3000);
    }

    if (!shouldPoll && pollIntervalRef.current !== null) {
      window.clearInterval(pollIntervalRef.current);
      pollIntervalRef.current = null;
    }

    return () => {
      if (pollIntervalRef.current !== null) {
        window.clearInterval(pollIntervalRef.current);
        pollIntervalRef.current = null;
      }
    };
  }, [
    trackedUploadIds,
    currentProjectId,
    refreshCurrentProjectDetails,
    refreshRecentFiles,
  ]);

  const value: ProjectsContextType = useMemo(
    () => ({
      projects,
      recentFiles,
      currentProjectDetails,
      currentProjectId,
      currentMessageFiles,
      allRecentFiles,
      allCurrentProjectFiles,
      beginUpload,
      setCurrentMessageFiles,
      upsertInstructions,
      fetchProjects,
      createProject,
      renameProject,
      deleteProject,
      uploadFiles,
      getRecentFiles,
      getFilesInProject,
      refreshCurrentProjectDetails,
      refreshRecentFiles,
      lastFailedFiles,
      clearLastFailedFiles: () => setLastFailedFiles([]),
      deleteUserFile: async (fileId: string) => {
        const result = await svcDeleteUserFile(fileId);
        // If no associations, backend enqueues deletion and status moves to DELETING; refresh lists
        if (!result.has_associations) {
          if (currentProjectId) {
            await refreshCurrentProjectDetails();
          }
          await refreshRecentFiles();
        }
        return result;
      },
      unlinkFileFromProject: async (projectId: number, fileId: string) => {
        const file = allCurrentProjectFiles.find((f) => f.id === fileId);
        if (!file) return;
        setAllCurrentProjectFiles((prev) =>
          prev.filter((f) => f.id !== file.id)
        );
        svcUnlinkFileFromProject(projectId, file.id).then(async (result) => {
          if (result.ok) {
            if (currentProjectId === projectId) {
              await refreshCurrentProjectDetails();
            }
            await refreshRecentFiles();
          } else {
            if (currentProjectId === projectId) {
              setAllCurrentProjectFiles((prev) => [file, ...prev]);
            }
          }
        });
      },
      linkFileToProject: async (projectId: number, file: ProjectFile) => {
        const existing = allCurrentProjectFiles.find((f) => f.id === file.id);
        if (existing) return;
        setAllCurrentProjectFiles((prev) => [file, ...prev]);
        svcLinkFileToProject(projectId, file.id).then(async (result) => {
          if (result.ok) {
            if (currentProjectId === projectId) {
              await refreshCurrentProjectDetails();
            }
            await refreshRecentFiles();
          } else {
            if (currentProjectId === projectId) {
              setAllCurrentProjectFiles((prev) =>
                prev.filter((f) => f.id !== file.id)
              );
            }
          }
        });
      },
    }),
    [
      projects,
      recentFiles,
      currentProjectDetails,
      currentProjectId,
      currentMessageFiles,
      allRecentFiles,
      allCurrentProjectFiles,
      beginUpload,
      setCurrentMessageFiles,
      upsertInstructions,
      fetchProjects,
      createProject,
      renameProject,
      deleteProject,
      uploadFiles,
      getRecentFiles,
      getFilesInProject,
      refreshCurrentProjectDetails,
      refreshRecentFiles,
      lastFailedFiles,
    ]
  );

  return (
    <ProjectsContext.Provider value={value}>
      {children}
    </ProjectsContext.Provider>
  );
};

export const useProjectsContext = (): ProjectsContextType => {
  const ctx = useContext(ProjectsContext);
  if (!ctx) {
    throw new Error(
      "useProjectsContext must be used within a ProjectsProvider"
    );
  }
  return ctx;
};
