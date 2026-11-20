"use client";

import {
  memo,
  type ReactNode,
  useCallback,
  useContext,
  useEffect,
  useLayoutEffect,
  useMemo,
  useRef,
  useState,
} from "react";
import { createPortal } from "react-dom";
import { useTranslations } from "next-intl";
import { Button } from "@opal/components";
import { Section, toast } from "@opal/layouts";
import {
  SvgDownloadCloud,
  SvgFiles,
  SvgSearchMenu,
  SvgSidebar,
} from "@opal/icons";
import { cn, richNodes } from "@opal/utils";
import type { PublishedFile } from "@/app/app/services/streamingModels";
import { buildImgUrl } from "@/app/app/components/files/images/utils";
import { downloadFile } from "@/lib/download";
import {
  useChatSessionStore,
  useCurrentRightPanelState,
} from "@/app/app/stores/useChatSessionStore";
import { publishedFilesOf, usePublishedFiles } from "@/lib/chat/hooks";
import { reloadChatPublishedFiles } from "@/lib/chat/pagedSession";
import {
  artifactKey,
  filesSharingALabel,
  newestVersion,
  publishedFileLabel,
  publishedFilePath,
} from "@/lib/chat/publishedFiles";
import {
  RIGHT_PANEL_FILES_TAB,
  RIGHT_PANEL_SOURCES_TAB,
  openCardFileAction,
  rightPanelFileTab,
  type ChatRightPanelAction,
  type ChatRightPanelState,
} from "@/lib/chat/rightPanel";
import {
  OUTPUT_PANEL_HEADER_CONTROL_WIDTH,
  PANEL_TOGGLE_RESERVE,
} from "@/lib/outputPanel/layout";
import { retainedFileViewers } from "@/lib/outputPanel/tabs";
import { getFileIcon } from "@/lib/utils";
import { AppWorkspaceElementsContext } from "@/layouts/chromes/AppWorkspace";
import { OutputPanelLayout } from "@/sections/output-panel/OutputPanelLayout";
import {
  PanelTabStrip,
  panelContentDomId,
  panelTabDomId,
  type PanelTabItem,
} from "@/sections/output-panel/PanelTabStrip";
import {
  PanelResizeHandle,
  PanelSizeButton,
  useOutputPanelWorkspace,
} from "@/sections/output-panel/PanelResize";
import { PanelUrlBar } from "@/sections/output-panel/PanelUrlBar";
import { ChatSidePanel } from "@/sections/chat/ChatSidePanel";
import {
  PublishedFilePreview,
  PublishedFilesGrid,
} from "@/sections/chat/PublishedFileViews";
import type { PublishedFilesPanel } from "@/sections/chat/PublishedFileCards";

interface ChatRightPanelProps {
  // The chat whose panel this is
  sessionId: string | null;
  open: boolean;
  state: ChatRightPanelState;
  dispatch: (action: ChatRightPanelAction) => void;
  // The newest version of each artifact, newest artifact first
  files: PublishedFile[];
  // The Sources tab's content; `hasSources` says whether it has any
  sources: ReactNode;
  hasSources: boolean;
  // Loads the chat's file list again; rejects when the load fails
  reloadFiles: () => Promise<void>;
}

/**
 * The chat's right panel, built from the output panel that Craft also uses:
 * a tab strip with the Files list, Sources and a tab per open file, a URL
 * bar, and the active tab's content, beside the page at a width the user can
 * drag, or over it at full size. On a workspace too narrow for both it covers
 * the page. A toggle at the workspace's top end, over the chat's header or
 * the open panel, opens and closes it; a chat shows it with or without files.
 * In the DOM, the toggle comes before the page while the panel is closed,
 * and before the panel's tabs while it is open, so keyboard order follows
 * what the user sees. Escape leaves full screen, then closes the active
 * file's tab, back on its tile, then closes the panel.
 */
export const ChatRightPanel = memo(function ChatRightPanel({
  sessionId,
  open,
  state,
  dispatch,
  files,
  sources,
  hasSources,
  reloadFiles,
}: ChatRightPanelProps) {
  const t = useTranslations("chat.rightPanel");
  // Each tab's shown file and its artifact's newest version
  const fileTabs = state.fileTabs.map(({ file, pinned }) => {
    const newest = newestVersion(file, files);
    return {
      id: rightPanelFileTab(file),
      file: pinned ? file : newest,
      newest,
      pinned,
    };
  });
  const fileByTab = new Map(fileTabs.map((tab) => [tab.id, tab.file]));
  const shown =
    state.activeId === RIGHT_PANEL_SOURCES_TAB || fileByTab.has(state.activeId)
      ? state.activeId
      : RIGHT_PANEL_FILES_TAB;
  const shownFile = fileByTab.get(shown);
  const shownPinned = fileTabs.some((tab) => tab.id === shown && tab.pinned);
  // Files and Sources lead the strip when they have content or are shown
  const fixedTabs: PanelTabItem[] = [
    ...(files.length > 0 || shown === RIGHT_PANEL_FILES_TAB
      ? [
          {
            id: RIGHT_PANEL_FILES_TAB,
            label: t("filesTab.label"),
            icon: SvgFiles,
            closable: false,
            movable: false,
          },
        ]
      : []),
    ...(hasSources || shown === RIGHT_PANEL_SOURCES_TAB
      ? [
          {
            id: RIGHT_PANEL_SOURCES_TAB,
            label: t("sourcesTab.label"),
            icon: SvgSearchMenu,
            closable: false,
            movable: false,
          },
        ]
      : []),
  ];
  // Tabs of one shown name show their path. A tab of an older version says
  // which version it shows.
  const sharingALabel = filesSharingALabel(fileTabs.map((tab) => tab.file));
  const tabs: PanelTabItem[] = [
    ...fixedTabs,
    ...fileTabs.map(({ id, file, newest }): PanelTabItem => {
      const name = sharingALabel.has(file.file_id)
        ? publishedFilePath(file)
        : publishedFileLabel(file);
      const tab = {
        id,
        icon: getFileIcon(file.name),
        closable: true,
        movable: true,
      };
      if (newest === file) return { ...tab, label: name };
      const values = {
        name,
        version: file.version ?? 1,
        latest: newest.version ?? 1,
      };
      return {
        ...tab,
        label: t.markup("fileTab.olderVersion", {
          ...values,
          isolate: (chunks) => chunks,
        }),
        // The name shows in its own direction, apart from the sentence
        content: richNodes(
          t.rich("fileTab.olderVersion", {
            ...values,
            isolate: (chunks) => <bdi>{chunks}</bdi>,
          })
        ),
      };
    }),
  ];
  const retainedTabs = new Set(
    retainedFileViewers(
      [shown, ...state.history].filter((tabId) => fileByTab.has(tabId))
    )
  );

  // Width: Craft's medium share of the workspace, its narrow rule, and full
  // size over the page
  const workspace = useContext(AppWorkspaceElementsContext);
  if (!workspace)
    throw new Error("The chat's right panel needs the app chrome's workspace");
  const toggleRef = useRef<HTMLElement>(null);
  const full = state.mode === "full";
  const layout = useOutputPanelWorkspace({
    workspaceRef: workspace.workspace,
    pageRef: workspace.page,
    coverFocusRef: toggleRef,
    // The host can hide a panel whose state is open, such as Sources
    // without retrieval
    mode: open ? state.mode : "closed",
    proportion: state.proportion,
    onResize: (proportion) => dispatch({ type: "setProportion", proportion }),
    onRestore: useCallback(
      () => dispatch({ type: "setMode", mode: "medium" }),
      [dispatch]
    ),
    sessionId,
  });

  // Files listed when the panel first shows them count as seen
  const { seenFileIds, seenInitialized } = state;
  useEffect(() => {
    if (open && shown !== RIGHT_PANEL_SOURCES_TAB && !seenInitialized)
      dispatch({
        type: "initializeSeen",
        fileIds: files.map((file) => file.file_id),
      });
  }, [open, shown, seenInitialized, files, dispatch]);
  // A shown file counts as seen, also a new version that its open tab
  // moves to
  const shownFileId = open ? shownFile?.file_id : undefined;
  useEffect(() => {
    if (shownFileId !== undefined && !seenFileIds.includes(shownFileId))
      dispatch({ type: "markSeen", fileId: shownFileId });
  }, [shownFileId, seenFileIds, dispatch]);
  const unseenFileIds = useMemo(
    () =>
      seenInitialized
        ? files
            .map((file) => file.file_id)
            .filter((fileId) => !seenFileIds.includes(fileId))
        : [],
    [files, seenFileIds, seenInitialized]
  );

  // Focus moves when an opening comes from outside the panel (a card, a
  // citation control, the panel toggle) or a tile opens a file: to the
  // file's preview, else to the active tab. A card that opens another
  // version of the shown artifact counts as an opening; a new version that an
  // unpinned tab follows does not. A switch in the tab strip leaves focus
  // where it is. Escape on a file goes back to its tile.
  const bodyRef = useRef<HTMLDivElement>(null);
  const insideChangeRef = useRef(false);
  const returnFocusRef = useRef<string | null>(null);
  const shownRef = useRef({
    open,
    shown,
    fileId: shownFile?.file_id,
    pinned: shownPinned,
  });
  const { dragging } = layout;
  useEffect(() => {
    const previous = shownRef.current;
    shownRef.current = {
      open,
      shown,
      fileId: shownFile?.file_id,
      pinned: shownPinned,
    };
    const inside = insideChangeRef.current;
    insideChangeRef.current = false;
    // The tile to go back to only counts when the Files list comes next
    const returnTo = returnFocusRef.current;
    returnFocusRef.current = null;
    if (
      !open ||
      (previous.open &&
        previous.shown === shown &&
        (previous.fileId === shownFile?.file_id ||
          (!previous.pinned && !shownPinned)))
    )
      return;
    const body = bodyRef.current;
    if (!body) return;
    // Without its tile, such as for a file the list leaves out or a tile the
    // search hides, focus goes to the Files tab
    if (returnTo !== null && shown === RIGHT_PANEL_FILES_TAB) {
      (
        body.querySelector<HTMLElement>(
          `[data-published-file="${CSS.escape(returnTo)}"] [role="button"]`
        ) ?? document.getElementById(panelTabDomId(shown))
      )?.focus({ preventScroll: true });
      return;
    }
    if (inside) return;
    const target = shownFile
      ? body.querySelector<HTMLElement>(
          `[data-published-preview="${CSS.escape(shownFile.file_id)}"]`
        )
      : document.getElementById(panelTabDomId(shown));
    target?.focus({ preventScroll: true });
  }, [open, shown, shownFile, shownPinned]);

  const selectTab = useCallback(
    (tabId: string) => {
      insideChangeRef.current = true;
      dispatch({ type: "showTab", tabId });
    },
    [dispatch]
  );
  // A tile shows the newest version, so its tab follows the newest
  const openFile = useCallback(
    (file: PublishedFile) =>
      dispatch({ type: "openFile", file, pinned: false }),
    [dispatch]
  );
  const escape = () => {
    if (!shownFile) {
      dispatch({ type: "closePanel" });
      return;
    }
    returnFocusRef.current = artifactKey(shownFile);
    dispatch({ type: "closeTab", tabId: shown });
  };

  // Reload loads the file list; an open file's tab keeps showing its file.
  // As Craft's, the button is off while the reload runs.
  const [reloading, setReloading] = useState(false);
  const reload = async () => {
    setReloading(true);
    try {
      await reloadFiles();
    } catch (error) {
      console.error("Failed to reload the chat's files", { sessionId, error });
      toast.error(t("reloadButton.error"));
    } finally {
      setReloading(false);
    }
  };

  // The toggle sits at the workspace's top end, over the chat's header or the
  // open panel. It moves between the workspace's slot and the panel, so
  // closing gives focus back to it when it closed the panel, or when the move
  // or the panel took focus.
  const closedByToggleRef = useRef(false);
  const toggle = sessionId !== null && (
    // At Craft's place: centered in the 52px header row, 12px from the end
    <div className="absolute end-3 top-3 z-30">
      <Button
        ref={toggleRef}
        icon={SvgSidebar}
        prominence="tertiary"
        size="sm"
        aria-expanded={open}
        // Decides from what the user sees: the host can hide a panel
        // whose state is open, such as Sources without retrieval
        onClick={() => {
          closedByToggleRef.current = open;
          dispatch(open ? { type: "closePanel" } : { type: "showFiles" });
        }}
        tooltip={t("toggleButton.label")}
        aria-label={t("toggleButton.label")}
      />
    </div>
  );
  const asideRef = useRef<HTMLElement>(null);
  const wasOpenRef = useRef(open);
  useLayoutEffect(() => {
    const wasOpen = wasOpenRef.current;
    wasOpenRef.current = open;
    if (open || !wasOpen) return;
    const closedByToggle = closedByToggleRef.current;
    closedByToggleRef.current = false;
    // Runs after the frame gives focus back to an opener outside the panel
    const focused = document.activeElement;
    if (
      closedByToggle ||
      focused === null ||
      focused === document.body ||
      asideRef.current?.contains(focused)
    )
      toggleRef.current?.focus({ preventScroll: true });
  }, [open]);

  const query = state.search.trim().toLocaleLowerCase();
  const listed = useMemo(
    () =>
      query
        ? files.filter((file) =>
            [publishedFileLabel(file), file.name, publishedFilePath(file)].some(
              (text) => text.toLocaleLowerCase().includes(query)
            )
          )
        : files,
    [files, query]
  );

  return (
    <>
      <ChatSidePanel
        open={open}
        onEscape={escape}
        // The page keeps the medium reserve while the panel is full, so a
        // change of size moves only the panel's edge
        reserve={layout.narrow ? 0 : layout.mediumWidth}
        covers={layout.covers}
        focusOnOpen={false}
        shows={shown}
      >
        <aside
          ref={asideRef}
          aria-label={
            shown === RIGHT_PANEL_SOURCES_TAB
              ? t("sourcesTab.label")
              : t("filesTab.label")
          }
          className="relative h-full w-full bg-background-neutral-00 border-s"
        >
          {open && toggle}
          <OutputPanelLayout
            headerControlWidth={OUTPUT_PANEL_HEADER_CONTROL_WIDTH}
            tabStrip={
              <PanelTabStrip
                tabs={tabs}
                activeTabId={shown}
                onSelect={selectTab}
                onClose={(tabId) => {
                  // The tab strip moves focus to the next tab itself
                  insideChangeRef.current = true;
                  dispatch({ type: "closeTab", tabId });
                }}
                onReorder={(tabId, index) => {
                  // Only file tabs move, among themselves
                  const over = tabs[index];
                  if (!over) return;
                  dispatch({ type: "reorderTab", tabId, overTabId: over.id });
                }}
              />
            }
            toolbar={
              // As Craft's: reload before the search or the file's path, and
              // a file's download after it
              shown !== RIGHT_PANEL_SOURCES_TAB && (
                <PanelUrlBar
                  displayUrl={
                    shownFile ? publishedFilePath(shownFile) : undefined
                  }
                  searchValue={state.search}
                  onSearchChange={
                    shownFile
                      ? undefined
                      : (search) => dispatch({ type: "setSearch", search })
                  }
                  placeholder={t("filesTab.search.placeholder")}
                  refresh={{
                    label: t("reloadButton.label"),
                    onRefresh: () => void reload(),
                    isRefreshing: false,
                    isUserRefreshing: reloading,
                  }}
                >
                  {shownFile && (
                    <Button
                      icon={SvgDownloadCloud}
                      prominence="tertiary"
                      size="sm"
                      onClick={() =>
                        downloadFile(shownFile.name, {
                          url: buildImgUrl(shownFile.file_id),
                        })
                      }
                      tooltip={t("downloadButton.tooltip")}
                      aria-label={t("downloadButton.tooltip")}
                    >
                      {t("downloadButton.label")}
                    </Button>
                  )}
                </PanelUrlBar>
              )
            }
          >
            <div ref={bodyRef} className="absolute inset-0">
              {shown === RIGHT_PANEL_FILES_TAB && (
                <div
                  id={panelContentDomId(shown)}
                  role="tabpanel"
                  aria-labelledby={panelTabDomId(shown)}
                  className="absolute inset-0"
                >
                  <PublishedFilesGrid
                    files={listed}
                    emptyLabel={
                      query ? t("filesTab.search.empty") : t("filesTab.empty")
                    }
                    unseenFileIds={unseenFileIds}
                    onOpen={openFile}
                  />
                </div>
              )}
              {shown === RIGHT_PANEL_SOURCES_TAB && (
                <div
                  id={panelContentDomId(shown)}
                  role="tabpanel"
                  aria-labelledby={panelTabDomId(shown)}
                  className="absolute inset-0 overflow-y-auto"
                >
                  {sources}
                </div>
              )}
              {fileTabs
                .filter((tab) => retainedTabs.has(tab.id))
                .map(({ id, file }) => {
                  const visible = open && id === shown;
                  return (
                    <div
                      key={id}
                      id={panelContentDomId(id)}
                      role="tabpanel"
                      aria-labelledby={panelTabDomId(id)}
                      aria-hidden={!visible}
                      inert={!visible}
                      // A hidden tab keeps its state and scroll but leaves
                      // layout, so a change of width does not reach it.
                      // `invisible` hides it where content-visibility is
                      // unsupported.
                      className={cn(
                        "absolute inset-0",
                        !visible &&
                          "invisible pointer-events-none [content-visibility:hidden]"
                      )}
                    >
                      <PublishedFilePreview file={file} />
                    </div>
                  );
                })}
            </div>
          </OutputPanelLayout>
          {/* Beside the room of the toggle, which the panel places over the
              workspace's end */}
          <div
            className="absolute top-3"
            style={{ insetInlineEnd: PANEL_TOGGLE_RESERVE }}
          >
            {!layout.narrow && (
              <PanelSizeButton
                full={full}
                expandLabel={t("expandButton.label")}
                restoreLabel={t("restoreButton.label")}
                onToggle={() =>
                  dispatch({
                    type: "setMode",
                    mode: full ? "medium" : "full",
                  })
                }
              />
            )}
          </div>
          {dragging && (
            // Over the content, so the pointer hovers nothing in it
            <div className="absolute inset-0 z-40 cursor-col-resize" />
          )}
          {!layout.narrow && (
            // Inside the panel's first 8px, as Craft's, so no edge clips it
            <PanelResizeHandle
              label={t("resizeHandle.label")}
              workspaceWidth={layout.workspaceWidth}
              mediumWidth={layout.mediumWidth}
              active={open && !full}
              insetInlineEnd="calc(100% - 8px)"
              transitions={false}
              handleProps={layout.handleProps}
            />
          )}
        </aside>
      </ChatSidePanel>
      {!open &&
        workspace.panelToggleSlot !== null &&
        createPortal(toggle, workspace.panelToggleSlot)}
    </>
  );
});

interface CurrentChatRightPanelProps {
  open: boolean;
  sources: ReactNode;
  hasSources: boolean;
}

/**
 * The open chat's right panel, with its state kept per chat session in the
 * store, so that coming back to a chat restores it. The page places it in the
 * app chrome's right panel slot, as a memoized element: a change of the
 * panel's state renders only the panel, not the app chrome.
 */
export function CurrentChatRightPanel(props: CurrentChatRightPanelProps) {
  const sessionId = useChatSessionStore((store) => store.currentSessionId);
  const state = useCurrentRightPanelState();
  const dispatch = useChatSessionStore.getState().updateCurrentRightPanel;
  const files = usePublishedFiles("current");
  const reloadFiles = useCallback(async () => {
    if (sessionId !== null) await reloadChatPublishedFiles(sessionId);
  }, [sessionId]);
  return (
    <ChatRightPanel
      {...props}
      sessionId={sessionId}
      state={state}
      dispatch={dispatch}
      files={files}
      reloadFiles={reloadFiles}
    />
  );
}

/** Opens a reply card's published file in the open chat's right panel. */
export function openPublishedFileInChat(file: PublishedFile): void {
  const store = useChatSessionStore.getState();
  store.updateCurrentRightPanel(
    openCardFileAction(
      file,
      publishedFilesOf(store.sessions.get(store.currentSessionId ?? ""))
    )
  );
}

/** The open chat's right panel, for a reply's file cards. */
export const CHAT_FILES_PANEL: PublishedFilesPanel = {
  openFile: openPublishedFileInChat,
  showFiles: () =>
    useChatSessionStore.getState().updateCurrentRightPanel({
      type: "showTab",
      tabId: RIGHT_PANEL_FILES_TAB,
    }),
};
