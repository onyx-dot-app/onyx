"use client";
import React, {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
  ReactNode,
  Dispatch,
  SetStateAction,
} from "react";
import type { Project, ProjectFile } from "./projectsService";
import {
  fetchProjects as svcFetchProjects,
  createProject as svcCreateProject,
  uploadFiles as svcUploadFiles,
  getRecentFiles as svcGetRecentFiles,
  getFilesInProject as svcGetFilesInProject,
} from "./projectsService";
import { FileDescriptor } from "../interfaces";

export type { Project, ProjectFile } from "./projectsService";

interface ProjectsContextType {
  projects: Project[];
  recentFiles: ProjectFile[];
  projectFiles: Record<string, ProjectFile[]>; // keyed by project id
  currentProjectId: string | null;
  isLoading: boolean;
  error: string | null;
  currentMessageFiles: FileDescriptor[];
  setCurrentMessageFiles: Dispatch<SetStateAction<FileDescriptor[]>>;
  setCurrentProjectId: (projectId: string | null) => void;

  fetchProjects: () => Promise<Project[]>;
  createProject: (name: string) => Promise<Project>;
  uploadFiles: (
    files: File[],
    projectId?: string | number | null
  ) => Promise<ProjectFile[]>;
  getRecentFiles: () => Promise<ProjectFile[]>;
  getFilesInProject: (projectId: string) => Promise<ProjectFile[]>;
  refreshProjectFiles: (projectId: string) => Promise<void>;
  refreshRecentFiles: () => Promise<void>;
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
  const [projectFiles, setProjectFiles] = useState<
    Record<string, ProjectFile[]>
  >({});
  const [currentProjectId, setCurrentProjectId] = useState<string | null>(null);
  const [isLoading, setIsLoading] = useState<boolean>(false);
  const [error, setError] = useState<string | null>(null);
  const [currentMessageFiles, setCurrentMessageFiles] = useState<
    FileDescriptor[]
  >([]);

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

  const uploadFiles = useCallback(
    async (
      files: File[],
      projectId?: string | number | null
    ): Promise<ProjectFile[]> => {
      setIsLoading(true);
      setError(null);
      try {
        const uploaded: ProjectFile[] = await svcUploadFiles(files, projectId);

        // If we uploaded into a specific project, refresh that project's files
        if (projectId) {
          await refreshProjectFiles(String(projectId));
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
    async (projectId: string): Promise<ProjectFile[]> => {
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

  const refreshProjectFiles = useCallback(
    async (projectId: string) => {
      const files = await getFilesInProject(projectId);
      setProjectFiles((prev) => ({ ...prev, [projectId]: files }));
    },
    [getFilesInProject]
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
      refreshProjectFiles(currentProjectId);
    }
  }, [currentProjectId, refreshProjectFiles]);

  const value: ProjectsContextType = useMemo(
    () => ({
      projects,
      recentFiles,
      projectFiles,
      currentProjectId,
      isLoading,
      error,
      currentMessageFiles,
      setCurrentMessageFiles,
      setCurrentProjectId,
      fetchProjects,
      createProject,
      uploadFiles,
      getRecentFiles,
      getFilesInProject,
      refreshProjectFiles,
      refreshRecentFiles,
    }),
    [
      projects,
      recentFiles,
      projectFiles,
      currentProjectId,
      isLoading,
      error,
      currentMessageFiles,
      setCurrentMessageFiles,
      fetchProjects,
      createProject,
      uploadFiles,
      getRecentFiles,
      getFilesInProject,
      refreshProjectFiles,
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
