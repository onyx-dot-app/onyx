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
import type { CategorizedFiles, Project, ProjectFile } from "./projectsService";
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
} from "./projectsService";

export type { Project, ProjectFile } from "./projectsService";

interface ProjectsContextType {
  projects: Project[];
  recentFiles: ProjectFile[];
  currentProjectDetails: ProjectDetails | null;
  currentProjectId: number | null;
  isLoading: boolean;
  error: string | null;
  currentMessageFiles: ProjectFile[];
  setCurrentMessageFiles: Dispatch<SetStateAction<ProjectFile[]>>;
  setCurrentProjectId: (projectId: number | null) => void;
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
  deleteUserFile: (fileId: string) => Promise<void>;
  unlinkFileFromProject: (projectId: number, fileId: string) => Promise<void>;
  linkFileToProject?: (
    projectId: number,
    fileId: string
  ) => Promise<ProjectFile>;
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
  const [currentProjectId, setCurrentProjectId] = useState<number | null>(null);
  const [isLoading, setIsLoading] = useState<boolean>(false);
  const [error, setError] = useState<string | null>(null);
  const [currentMessageFiles, setCurrentMessageFiles] = useState<ProjectFile[]>(
    []
  );
  const pollIntervalRef = useRef<number | null>(null);
  const isPollingRef = useRef<boolean>(false);
  const [lastFailedFiles, setLastFailedFiles] = useState<ProjectFile[]>([]);
  const [trackedUploadIds, setTrackedUploadIds] = useState<Set<string>>(
    new Set()
  );

  const fetchProjects = useCallback(async (): Promise<Project[]> => {
    setError(null);
    try {
      const data: Project[] = await svcFetchProjects();
      setProjects(data);
      return data;
    } catch (err) {
      const message =
        err instanceof Error ? err.message : "Failed to fetch projects";
      setError(message);
      return [];
    }
  }, []);

  // Load full details for current project
  const refreshCurrentProjectDetails = useCallback(async () => {
    if (currentProjectId) {
      const details = await svcGetProjectDetails(currentProjectId);
      setCurrentProjectDetails(details);
    }
  }, [currentProjectId, setCurrentProjectDetails]);

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
      setError(null);
      try {
        const project: Project = await svcCreateProject(name);
        // Refresh list to keep order consistent with backend
        await fetchProjects();
        return project;
      } catch (err) {
        const message =
          err instanceof Error ? err.message : "Failed to create project";
        setError(message);
        throw err;
      }
    },
    [fetchProjects]
  );

  const renameProject = useCallback(
    async (projectId: number, name: string): Promise<Project> => {
      setError(null);
      try {
        const updated = await svcRenameProject(projectId, name);
        await fetchProjects();
        if (currentProjectId === projectId) {
          await refreshCurrentProjectDetails();
        }
        return updated;
      } catch (err) {
        const message =
          err instanceof Error ? err.message : "Failed to rename project";
        setError(message);
        throw err;
      }
    },
    [fetchProjects, currentProjectId, refreshCurrentProjectDetails]
  );

  const deleteProject = useCallback(
    async (projectId: number): Promise<void> => {
      setError(null);
      try {
        await svcDeleteProject(projectId);
        await fetchProjects();
        if (currentProjectId === projectId) {
          setCurrentProjectDetails(null);
          setCurrentProjectId(null);
        }
      } catch (err) {
        const message =
          err instanceof Error ? err.message : "Failed to delete project";
        setError(message);
        throw err;
      }
    },
    [fetchProjects, currentProjectId]
  );

  const getRecentFiles = useCallback(async (): Promise<ProjectFile[]> => {
    setError(null);
    try {
      const data: ProjectFile[] = await svcGetRecentFiles();
      return data;
    } catch (err) {
      const message =
        err instanceof Error ? err.message : "Failed to fetch recent files";
      setError(message);
      return [];
    }
  }, []);

  const refreshRecentFiles = useCallback(async () => {
    const files = await getRecentFiles();
    setRecentFiles(files);
  }, [getRecentFiles]);

  const uploadFiles = useCallback(
    async (
      files: File[],
      projectId?: number | null
    ): Promise<CategorizedFiles> => {
      setIsLoading(true);
      setError(null);
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
        const message =
          err instanceof Error ? err.message : "Failed to upload files";
        setError(message);
        throw err;
      } finally {
        setIsLoading(false);
      }
    },
    [currentProjectId, refreshCurrentProjectDetails, refreshRecentFiles]
  );

  const getFilesInProject = useCallback(
    async (projectId: number): Promise<ProjectFile[]> => {
      setError(null);
      try {
        const data: ProjectFile[] = await svcGetFilesInProject(projectId);
        return data;
      } catch (err) {
        const message =
          err instanceof Error ? err.message : "Failed to fetch project files";
        setError(message);
        return [];
      }
    },
    []
  );

  useEffect(() => {
    // Initial load - only fetch recent files since projects come from props
    setIsLoading(true);
    getRecentFiles()
      .then((recent) => {
        setRecentFiles(recent);
      })
      .catch(() => {
        // errors captured in individual calls
      })
      .finally(() => setIsLoading(false));
  }, [getRecentFiles]);

  useEffect(() => {
    if (currentProjectId) {
      refreshCurrentProjectDetails();
    }
  }, [currentProjectId, refreshCurrentProjectDetails]);

  // Keep currentMessageFiles in sync with latest file statuses from backend (key by id)
  useEffect(() => {
    if (currentMessageFiles.length === 0) return;

    const latestById = new Map<string, ProjectFile>();
    // Prefer project files first, then recent files as fallback
    (currentProjectDetails?.files || []).forEach((f) => {
      latestById.set(f.id, f);
    });
    recentFiles.forEach((f) => {
      const key = f.id;
      if (!latestById.has(key)) {
        latestById.set(key, f);
      }
    });

    let changed = false;
    const reconciled: ProjectFile[] = [];
    const newlyFailed: ProjectFile[] = [];
    for (const f of currentMessageFiles) {
      const key = f.id;
      const latest = latestById.get(key);
      if (latest) {
        const latestStatus = String(latest.status).toLowerCase();
        // Drop files that have transitioned to failed
        if (latestStatus === "failed") {
          if (String(f.status).toLowerCase() !== "failed") {
            newlyFailed.push(latest);
          }
          changed = true;
          continue;
        }
        // Only mark changed if status or other fields differ
        if (
          latest.status !== f.status ||
          latest.name !== f.name ||
          latest.file_type !== f.file_type
        ) {
          changed = true;
          reconciled.push({ ...f, ...latest } as ProjectFile);
          continue;
        }
      }
      reconciled.push(f);
    }

    if (newlyFailed.length > 0) {
      setLastFailedFiles(newlyFailed);
    }

    if (changed || reconciled.length !== currentMessageFiles.length) {
      setCurrentMessageFiles(reconciled);
    }
  }, [recentFiles, currentProjectDetails?.files]);

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
      isLoading,
      error,
      currentMessageFiles,
      setCurrentMessageFiles,
      setCurrentProjectId,
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
        await svcDeleteUserFile(fileId);
        // Refresh current project details and recent files to reflect deletion
        if (currentProjectId) {
          await refreshCurrentProjectDetails();
        }
        await refreshRecentFiles();
      },
      unlinkFileFromProject: async (projectId: number, fileId: string) => {
        await svcUnlinkFileFromProject(projectId, fileId);
        if (currentProjectId === projectId) {
          await refreshCurrentProjectDetails();
        }
        await refreshRecentFiles();
      },
      linkFileToProject: async (projectId: number, fileId: string) => {
        const file = await svcLinkFileToProject(projectId, fileId);
        if (currentProjectId === projectId) {
          await refreshCurrentProjectDetails();
        }
        await refreshRecentFiles();
        return file;
      },
    }),
    [
      projects,
      recentFiles,
      currentProjectDetails,
      currentProjectId,
      isLoading,
      error,
      currentMessageFiles,
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
