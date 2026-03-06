import React, { PropsWithChildren } from "react";
import { act, renderHook } from "@testing-library/react";
import {
  ProjectsProvider,
  useProjectsContext,
} from "@/providers/ProjectsContext";
import { SettingsContext } from "@/providers/SettingsProvider";
import { CombinedSettings } from "@/interfaces/settings";

const mockUploadFiles = jest.fn();
const mockGetRecentFiles = jest.fn();
const mockToastWarning = jest.fn();

jest.mock("next/navigation", () => ({
  useSearchParams: () => ({
    get: () => null,
  }),
}));

jest.mock("@/hooks/appNavigation", () => ({
  useAppRouter: () => jest.fn(),
}));

jest.mock("@/lib/hooks/useProjects", () => ({
  useProjects: () => ({
    projects: [],
    refreshProjects: jest.fn().mockResolvedValue([]),
  }),
}));

jest.mock("@/hooks/useToast", () => ({
  toast: {
    warning: (...args: unknown[]) => mockToastWarning(...args),
    error: jest.fn(),
    success: jest.fn(),
  },
}));

jest.mock("@/app/app/projects/projectsService", () => {
  const actual = jest.requireActual("@/app/app/projects/projectsService");
  return {
    ...actual,
    fetchProjects: jest.fn().mockResolvedValue([]),
    createProject: jest.fn(),
    uploadFiles: (...args: unknown[]) => mockUploadFiles(...args),
    getRecentFiles: (...args: unknown[]) => mockGetRecentFiles(...args),
    getFilesInProject: jest.fn().mockResolvedValue([]),
    getProject: jest.fn(),
    getProjectInstructions: jest.fn(),
    upsertProjectInstructions: jest.fn(),
    getProjectDetails: jest.fn(),
    renameProject: jest.fn(),
    deleteProject: jest.fn(),
    deleteUserFile: jest.fn(),
    getUserFileStatuses: jest.fn().mockResolvedValue([]),
    unlinkFileFromProject: jest.fn(),
    linkFileToProject: jest.fn(),
  };
});

const settingsValue: CombinedSettings = {
  settings: {
    user_file_max_upload_size_mb: 1,
  } as CombinedSettings["settings"],
  enterpriseSettings: null,
  customAnalyticsScript: null,
  webVersion: null,
  webDomain: null,
  isSearchModeAvailable: true,
};

const wrapper = ({ children }: PropsWithChildren) => (
  <SettingsContext.Provider value={settingsValue}>
    <ProjectsProvider>{children}</ProjectsProvider>
  </SettingsContext.Provider>
);

describe("ProjectsContext beginUpload size precheck", () => {
  beforeEach(() => {
    mockUploadFiles.mockReset();
    mockGetRecentFiles.mockReset();
    mockToastWarning.mockReset();

    mockUploadFiles.mockResolvedValue({
      user_files: [],
      rejected_files: [],
    });
    mockGetRecentFiles.mockResolvedValue([]);
  });

  it("only sends valid files to the upload API when oversized files are present", async () => {
    const { result } = renderHook(() => useProjectsContext(), { wrapper });

    const valid = new File(["small"], "small.txt", { type: "text/plain" });
    const oversized = new File([new Uint8Array(2 * 1024 * 1024)], "big.txt", {
      type: "text/plain",
    });

    let optimisticFiles: { name: string }[] = [];
    await act(async () => {
      optimisticFiles = await result.current.beginUpload(
        [valid, oversized],
        null
      );
    });

    expect(mockUploadFiles).toHaveBeenCalledTimes(1);
    const [uploadedFiles] = mockUploadFiles.mock.calls[0];
    expect((uploadedFiles as File[]).map((f) => f.name)).toEqual(["small.txt"]);
    expect(optimisticFiles.map((f) => f.name)).toEqual(["small.txt"]);
    expect(mockToastWarning).toHaveBeenCalledTimes(1);
  });

  it("does not call upload API when all files are oversized", async () => {
    const { result } = renderHook(() => useProjectsContext(), { wrapper });

    const oversized = new File(
      [new Uint8Array(2 * 1024 * 1024)],
      "too-big.txt",
      { type: "text/plain" }
    );

    let optimisticFiles: { name: string }[] = [];
    await act(async () => {
      optimisticFiles = await result.current.beginUpload([oversized], null);
    });

    expect(mockUploadFiles).not.toHaveBeenCalled();
    expect(optimisticFiles).toEqual([]);
    expect(mockToastWarning).toHaveBeenCalledTimes(1);
  });
});
