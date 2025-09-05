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
} from "./projectsService";
import { Prompt } from "@/app/admin/assistants/interfaces";

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
}

const ProjectsContext = createContext<ProjectsContextType | undefined>(
  undefined
);

interface ProjectsProviderProps {
  children: ReactNode;
}

export const ProjectsProvider: React.FC<ProjectsProviderProps> = ({
  children,
}) => {
  const [projects, setProjects] = useState<Project[]>([]);
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
      console.log("refreshing current project details", currentProjectId);
      const details = await svcGetProjectDetails(currentProjectId);
      setCurrentProjectDetails(details);
    }
  }, [currentProjectId, setCurrentProjectDetails]);

  const upsertInstructions = useCallback(
    async (instructions: string) => {
      if (!currentProjectId) {
        throw new Error("No project selected");
      }
      console.log("upserting instructions", instructions);
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

        // If we uploaded into a specific project, refresh that project's files
        if (projectId) {
          await refreshCurrentProjectDetails();
        }
        // Refresh recent files as well
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
    []
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

  const refreshRecentFiles = useCallback(async () => {
    const files = await getRecentFiles();
    setRecentFiles(files);
  }, [getRecentFiles]);

  useEffect(() => {
    // Initial load
    setIsLoading(true);
    Promise.all([fetchProjects(), getRecentFiles()])
      .then(([, recent]) => {
        setRecentFiles(recent);
      })
      .catch(() => {
        // errors captured in individual calls
      })
      .finally(() => setIsLoading(false));
  }, [fetchProjects, getRecentFiles]);

  useEffect(() => {
    if (currentProjectId) {
      refreshCurrentProjectDetails();
    }
  }, [currentProjectId, refreshCurrentProjectDetails]);

  // Keep currentMessageFiles in sync with latest file statuses from backend (key by id only)
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
    const reconciled = currentMessageFiles.map((f) => {
      const key = f.id;
      const latest = latestById.get(key);
      if (latest) {
        // Only mark changed if status or other fields differ
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

    if (changed) {
      setCurrentMessageFiles(reconciled);
    }
  }, [recentFiles, currentProjectDetails?.files]);

  // Poll every second while any file is processing
  useEffect(() => {
    const hasProcessingInProject = Boolean(
      currentProjectDetails?.files?.some(
        (f) => f.status.toLowerCase() === "processing"
      )
    );
    const hasProcessingInRecent = recentFiles.some(
      (f) => String(f.status).toLowerCase() === "processing"
    );
    const shouldPoll = hasProcessingInProject || hasProcessingInRecent;

    const runRefresh = async () => {
      if (isPollingRef.current) return;
      isPollingRef.current = true;
      try {
        if (currentProjectId) {
          await refreshCurrentProjectDetails();
        }
        await refreshRecentFiles();
      } finally {
        isPollingRef.current = false;
      }
    };

    if (shouldPoll && pollIntervalRef.current === null) {
      // Kick once immediately, then start interval
      runRefresh();
      pollIntervalRef.current = window.setInterval(runRefresh, 3000);
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
    recentFiles,
    currentProjectDetails,
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
      deleteUserFile: async (fileId: string) => {
        await svcDeleteUserFile(fileId);
        // Refresh current project details and recent files to reflect deletion
        if (currentProjectId) {
          await refreshCurrentProjectDetails();
        }
        await refreshRecentFiles();
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
