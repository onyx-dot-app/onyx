import {
  afterEach,
  beforeEach,
  describe,
  expect,
  it,
  jest,
} from "@jest/globals";
import type { Mock } from "jest-mock";
import { act, render } from "@testing-library/react-native";

import { getUserFileStatuses } from "@/api/files/files";
import { UserFileStatus, type ProjectFile } from "@/chat/contracts/projects";
import { makeProjectFile } from "@/chat/__tests__/fixtures";
import { UploadReconciler } from "@/components/chat/UploadReconciler";
import { useUserFileStore } from "@/state/userFileStore";

jest.mock("@/api/files/files", () => ({ getUserFileStatuses: jest.fn() }));

const statusesMock = getUserFileStatuses as unknown as Mock<
  (ids: string[]) => Promise<ProjectFile[]>
>;

function resetStore(filesById: Record<string, unknown> = {}) {
  useUserFileStore.setState({
    filesById: filesById as never,
    serverIdToClientId: {},
    tasksById: {},
    progressById: {},
    epochCounter: 0,
  });
}

describe("UploadReconciler", () => {
  beforeEach(() => {
    jest.useFakeTimers();
    jest.clearAllMocks();
    resetStore();
  });
  afterEach(() => {
    jest.useRealTimers();
  });

  it("polls processing files every 3s and reconciles their status", async () => {
    resetStore({
      f1: {
        clientId: "f1",
        file: makeProjectFile({ id: "f1", status: UserFileStatus.INDEXING }),
        source: "upload",
      },
    });
    statusesMock.mockResolvedValue([
      makeProjectFile({ id: "f1", status: UserFileStatus.COMPLETED }),
    ]);

    render(<UploadReconciler />);
    await act(async () => {
      await jest.advanceTimersByTimeAsync(3000);
    });

    expect(statusesMock).toHaveBeenCalledWith(["f1"]);
    expect(useUserFileStore.getState().filesById["f1"]!.file.status).toBe(
      UserFileStatus.COMPLETED,
    );
  });

  it("does not poll when nothing is processing", async () => {
    render(<UploadReconciler />);
    await act(async () => {
      await jest.advanceTimersByTimeAsync(3000);
    });
    expect(statusesMock).not.toHaveBeenCalled();
  });
});
