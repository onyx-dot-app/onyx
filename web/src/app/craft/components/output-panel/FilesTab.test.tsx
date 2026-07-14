import React from "react";
import { act, render, screen, waitFor } from "@testing-library/react";
import { SWRConfig } from "swr";

import FilesTab from "@/app/craft/components/output-panel/FilesTab";
import { useBuildSessionStore } from "@/app/craft/hooks/useBuildSessionStore";
import { fetchDirectoryListing } from "@/app/craft/services/apiServices";
import type {
  DirectoryListing,
  FileSystemEntry,
} from "@/app/craft/types/streamingTypes";

jest.mock("@/app/craft/services/apiServices", () => ({
  ...jest.requireActual("@/app/craft/services/apiServices"),
  fetchDirectoryListing: jest.fn(),
}));

const mockedFetchDirectoryListing = jest.mocked(fetchDirectoryListing);

function file(name: string, path: string): FileSystemEntry {
  return {
    name,
    path,
    is_directory: false,
    size: 10,
    mime_type: "text/plain",
  };
}

const outputsDirectory: FileSystemEntry = {
  name: "outputs",
  path: "outputs",
  is_directory: true,
  size: null,
  mime_type: null,
};

describe("FilesTab", () => {
  beforeEach(() => {
    mockedFetchDirectoryListing.mockReset();
    useBuildSessionStore.setState({
      currentSessionId: null,
      sessions: new Map(),
    });
  });

  it("keeps expanded directory contents visible while refreshing", async () => {
    const sessionId = "session-1";
    const oldFile = file("old.txt", "outputs/old.txt");
    const newFile = file("new.txt", "outputs/new.txt");
    let resolveRefreshedOutputs: (listing: DirectoryListing) => void = () => {};
    const refreshedOutputs = new Promise<DirectoryListing>((resolve) => {
      resolveRefreshedOutputs = resolve;
    });

    mockedFetchDirectoryListing.mockImplementation((_sessionId, path) => {
      if (path === "") {
        return Promise.resolve({ path: "", entries: [outputsDirectory] });
      }
      if (path === "outputs") return refreshedOutputs;
      return Promise.resolve({ path: path ?? "", entries: [] });
    });

    useBuildSessionStore.getState().createSession(sessionId, {
      filesTabState: {
        expandedPaths: ["outputs"],
        scrollTop: 0,
        directoryCache: { outputs: [oldFile] },
      },
    });
    useBuildSessionStore.getState().setCurrentSession(sessionId);

    render(
      <SWRConfig value={{ provider: () => new Map() }}>
        <FilesTab sessionId={sessionId} />
      </SWRConfig>
    );

    expect(await screen.findByText("old.txt")).toBeInTheDocument();

    act(() => {
      useBuildSessionStore.getState().triggerFilesRefresh(sessionId);
    });

    await waitFor(() =>
      expect(mockedFetchDirectoryListing).toHaveBeenCalledWith(
        sessionId,
        "outputs"
      )
    );
    expect(screen.getByText("old.txt")).toBeInTheDocument();
    expect(screen.queryByText("Loading...")).not.toBeInTheDocument();

    act(() => {
      resolveRefreshedOutputs({ path: "outputs", entries: [newFile] });
    });

    expect(await screen.findByText("new.txt")).toBeInTheDocument();
    expect(screen.queryByText("old.txt")).not.toBeInTheDocument();
  });

  it("ignores an older directory response that finishes last", async () => {
    const sessionId = "session-1";
    const oldFile = file("old.txt", "outputs/old.txt");
    const staleFile = file("stale.txt", "outputs/stale.txt");
    const newestFile = file("newest.txt", "outputs/newest.txt");
    const outputResolvers: Array<(listing: DirectoryListing) => void> = [];

    mockedFetchDirectoryListing.mockImplementation((_sessionId, path) => {
      if (path === "") {
        return Promise.resolve({ path: "", entries: [outputsDirectory] });
      }
      if (path === "outputs") {
        return new Promise<DirectoryListing>((resolve) => {
          outputResolvers.push(resolve);
        });
      }
      return Promise.resolve({ path: path ?? "", entries: [] });
    });

    useBuildSessionStore.getState().createSession(sessionId, {
      filesTabState: {
        expandedPaths: ["outputs"],
        scrollTop: 0,
        directoryCache: { outputs: [oldFile] },
      },
    });
    useBuildSessionStore.getState().setCurrentSession(sessionId);

    render(
      <SWRConfig value={{ provider: () => new Map() }}>
        <FilesTab sessionId={sessionId} />
      </SWRConfig>
    );

    expect(await screen.findByText("old.txt")).toBeInTheDocument();

    act(() => {
      useBuildSessionStore.getState().triggerFilesRefresh(sessionId);
    });
    await waitFor(() => expect(outputResolvers).toHaveLength(1));

    act(() => {
      useBuildSessionStore.getState().triggerFilesRefresh(sessionId);
    });
    await waitFor(() => expect(outputResolvers).toHaveLength(2));

    act(() => {
      outputResolvers[1]?.({ path: "outputs", entries: [newestFile] });
    });
    expect(await screen.findByText("newest.txt")).toBeInTheDocument();

    act(() => {
      outputResolvers[0]?.({ path: "outputs", entries: [staleFile] });
    });
    await waitFor(() => {
      expect(screen.getByText("newest.txt")).toBeInTheDocument();
      expect(screen.queryByText("stale.txt")).not.toBeInTheDocument();
    });
  });
});
