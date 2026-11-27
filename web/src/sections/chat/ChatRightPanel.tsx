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
  SvgFiles,
  SvgGlobe,
  SvgMonitor,
  SvgSearchMenu,
  SvgSidebar,
} from "@opal/icons";
import { cn, richNodes } from "@opal/utils";
import type { PublishedFile } from "@/app/app/services/streamingModels";
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
  RIGHT_PANEL_BROWSER_TAB,
  RIGHT_PANEL_CHROME_TAB,
  RIGHT_PANEL_FILES_TAB,
  RIGHT_PANEL_SOURCES_TAB,
  openCardFileAction,
  rightPanelFileTab,
  type ChatRightPanelAction,
  type ChatRightPanelState,
} from "@/lib/chat/rightPanel";
import {
  OUTPUT_PANEL_HEADER_CONTROL_WIDTH,
  PANEL_TOGGLE_RESERVE_VAR,
} from "@/lib/outputPanel/layout";
import { retainedFileViewers } from "@/lib/outputPanel/tabs";
import { getFileIcon } from "@/lib/utils";
import { useSettings } from "@/lib/settings/hooks";
import { useIncognito } from "@/providers/IncognitoProvider";
import { PreviewActionsSlotContext } from "@/sections/file-preview/FloatingFooter";
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
import { BrowserPanel } from "@/sections/chat/browser/BrowserPanel";
import {
  useChatBrowserTabs,
  useChromeBrowserState,
} from "@/lib/chat/browser/hooks";
import { ChromeBrowserPanel } from "@/sections/chat/browser/ChromeBrowserPanel";

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
  // The "+" menu offers the chat's browser
  browserAvailable?: boolean;
  // The "+" menu offers the user's own Chrome
  chromeAvailable?: boolean;
  // The chat's user messages so far; each starts a turn, and a turn picks
  // its browser when it starts
  userMessageCount?: number;
}

/**
 * The chat's right panel, built from the output panel that Craft also uses:
 * a tab strip with the Files list, Sources, a tab per page of the chat's
 * browser and a tab per open file, a URL bar, and the active tab's content, beside the page at a width the user can
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
  browserAvailable = false,
  chromeAvailable = false,
  userMessageCount = 0,
}: ChatRightPanelProps) {
  const t = useTranslations("chat.rightPanel");
  // Each tab's shown file, with the name that the list gives its artifact,
  // and the artifact's newest version
  const fileTabs = useMemo(
    () =>
      state.fileTabs.map(({ file, pinned }) => {
        const newest = newestVersion(file, files);
        const shownVersion = pinned ? file : newest;
        // A rename reaches the list, not the file that the tab opened with
        const name =
          files.find((listed) => artifactKey(listed) === artifactKey(file))
            ?.name ?? file.name;
        return {
          id: rightPanelFileTab(file),
          file:
            shownVersion.name === name
              ? shownVersion
              : { ...shownVersion, name },
          newest,
          pinned,
        };
      }),
    [state.fileTabs, files]
  );
  const fileByTab = new Map(fileTabs.map((tab) => [tab.id, tab.file]));

  const showFilesList = useCallback(
    () => dispatch({ type: "showTab", tabId: RIGHT_PANEL_FILES_TAB }),
    [dispatch]
  );
  // A tab change that the panel makes itself leaves focus where it is
  const insideChangeRef = useRef(false);
  // While the user shares Chrome with the chat, its browser tools drive
  // Chrome, so the panel shows Chrome in place of the sandbox's browser
  const chrome = useChromeBrowserState(
    chromeAvailable ? sessionId : null,
    open && state.chromeOpen
  );
  // A refused refresh (Chrome turned off, or the user's access) ends the
  // share in the panel; a transient failure keeps the last state
  const refused =
    chrome.error !== undefined &&
    chrome.error.status >= 400 &&
    chrome.error.status < 500;
  const grant = refused ? undefined : chrome.data?.grant;
  const chromeShared = !!grant && grant.expires_at * 1000 > Date.now();
  // A turn picks its browser when it starts. A sandbox browser that was open
  // before the share began belongs to a turn that still uses the sandbox,
  // so it stays until the next message starts a turn, which uses Chrome.
  // The chat and its count of user messages when the sandbox browser was
  // last open unshared; null: none open.
  const [sandboxTurn, setSandboxTurn] = useState<{
    sessionId: string | null;
    count: number;
  } | null>(null);
  if (!state.browserOpen && sandboxTurn !== null) setSandboxTurn(null);
  if (
    state.browserOpen &&
    !chromeShared &&
    (sandboxTurn?.sessionId !== sessionId ||
      sandboxTurn.count !== userMessageCount)
  )
    setSandboxTurn({ sessionId, count: userMessageCount });
  const redirectBrowser =
    chromeShared &&
    (sandboxTurn === null ||
      sandboxTurn.sessionId !== sessionId ||
      userMessageCount > sandboxTurn.count);
  const browser = useChatBrowserTabs({
    sessionId,
    open,
    state: redirectBrowser ? { ...state, browserOpen: false } : state,
    dispatch,
    onInsideChange: () => {
      insideChangeRef.current = true;
    },
  });
  const closeBrowser = browser.closeTab;
  useEffect(() => {
    if (!redirectBrowser || !state.browserOpen) return;
    // The browser's close also drops pages queued for the sandbox
    closeBrowser(RIGHT_PANEL_BROWSER_TAB);
    dispatch({ type: "openChrome" });
  }, [redirectBrowser, state.browserOpen, closeBrowser, dispatch]);
  useEffect(() => {
    if (!chromeAvailable && state.chromeOpen)
      dispatch({ type: "closeTab", tabId: RIGHT_PANEL_CHROME_TAB });
  }, [chromeAvailable, state.chromeOpen, dispatch]);
  const chromeShown =
    chromeAvailable && state.activeId === RIGHT_PANEL_CHROME_TAB;
  const shown =
    state.activeId === RIGHT_PANEL_SOURCES_TAB ||
    fileByTab.has(state.activeId) ||
    chromeShown
      ? state.activeId
      : browser.shown
        ? browser.tabId
        : RIGHT_PANEL_FILES_TAB;
  const shownFile = fileByTab.get(shown);
  const shownPinned = fileTabs.some((tab) => tab.id === shown && tab.pinned);
  // Files and Sources lead the strip while open, then a tab per page of the open browser, as T3 Code lists its browser
  // tabs among its other tabs: a globe, the page's title or host, a close
  // button
  const fixedTabs: PanelTabItem[] = [
    ...(state.filesOpen
      ? [
          {
            id: RIGHT_PANEL_FILES_TAB,
            label: t("filesTab.label"),
            icon: SvgFiles,
            movable: false,
          },
        ]
      : []),
    ...(state.sourcesOpen
      ? [
          {
            id: RIGHT_PANEL_SOURCES_TAB,
            label: t("sourcesTab.label"),
            icon: SvgSearchMenu,
            movable: false,
          },
        ]
      : []),
    ...(state.chromeOpen && chromeAvailable
      ? [
          {
            id: RIGHT_PANEL_CHROME_TAB,
            label: t("chromeTab.label"),
            icon: SvgMonitor,
            closable: true,
            movable: false,
          },
        ]
      : []),
    ...browser.tabs.map(
      (tab): PanelTabItem => ({
        id: tab.id,
        label: tab.title ?? t("browserTab.label"),
        icon: SvgGlobe,
        movable: false,
      })
    ),
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
        movable: true,
      };
      if (newest.file_id === file.file_id) return { ...tab, label: name };
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
    if (
      open &&
      shown !== RIGHT_PANEL_SOURCES_TAB &&
      !browser.shown &&
      !chromeShown &&
      !seenInitialized
    )
      dispatch({
        type: "initializeSeen",
        fileIds: files.map((file) => file.file_id),
      });
  }, [
    open,
    shown,
    browser.shown,
    chromeShown,
    seenInitialized,
    files,
    dispatch,
  ]);
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
  const returnFocusRef = useRef<string | null>(null);
  const shownRef = useRef({
    open,
    shown,
    browser: browser.shown,
    fileId: shownFile?.file_id,
    pinned: shownPinned,
  });
  const { dragging } = layout;
  useEffect(() => {
    const previous = shownRef.current;
    shownRef.current = {
      open,
      shown,
      browser: browser.shown,
      fileId: shownFile?.file_id,
      pinned: shownPinned,
    };
    const inside = insideChangeRef.current;
    insideChangeRef.current = false;
    // A move between the browser's tabs, such as to a page that the agent
    // opens, leaves focus where it is
    if (open && previous.open && previous.browser && browser.shown) {
      returnFocusRef.current = null;
      // The tab that stands for the browser goes when the pages come; the
      // focus it had goes to the shown page's tab
      if (
        previous.shown === RIGHT_PANEL_BROWSER_TAB &&
        shown !== RIGHT_PANEL_BROWSER_TAB &&
        document.activeElement === document.body
      )
        document
          .getElementById(panelTabDomId(shown))
          ?.focus({ preventScroll: true });
      return;
    }
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
  }, [open, shown, browser.shown, shownFile, shownPinned]);

  const selectTab = (tabId: string) => {
    insideChangeRef.current = true;
    if (!browser.selectTab(tabId)) dispatch({ type: "showTab", tabId });
  };
  const closeTab = (tabId: string) => {
    if (!browser.closeTab(tabId)) dispatch({ type: "closeTab", tabId });
  };

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
    closeTab(shown);
  };

  // Reload loads the file list; an open file's tab keeps showing its file.
  // As Craft's, the button is off while the reload runs.
  const [reloading, setReloading] = useState(false);
  const [actionsSlot, setActionsSlot] = useState<HTMLElement | null>(null);
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
  // The open panel holds the toggle, so the page needs no room for it
  useLayoutEffect(() => {
    const page = workspace.page.current;
    if (!open || !page) return;
    page.style.setProperty(PANEL_TOGGLE_RESERVE_VAR, "0px");
    return () => {
      page.style.removeProperty(PANEL_TOGGLE_RESERVE_VAR);
    };
  }, [open, workspace.page]);
  const toggle = sessionId !== null && (
    // On the chat header's button line: 8px from the top, as its padding
    // (a flex box, so no line box shifts it), 12px from the end
    <Section width="fit" height="auto" className="absolute end-3 top-2 z-30">
      <Button
        ref={toggleRef}
        icon={SvgSidebar}
        prominence="tertiary"
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
    </Section>
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
              : browser.shown
                ? t("browserTab.label")
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
                  closeTab(tabId);
                }}
                onReorder={(tabId, index) => {
                  // Only file tabs move, among themselves
                  const over = tabs[index];
                  if (!over) return;
                  dispatch({ type: "reorderTab", tabId, overTabId: over.id });
                }}
                menuItems={[
                  {
                    kind: "action",
                    id: RIGHT_PANEL_FILES_TAB,
                    title: t("filesTab.label"),
                    icon: SvgFiles,
                    onSelect: showFilesList,
                  },
                  ...(browserAvailable && !chromeShared && sessionId !== null
                    ? [
                        {
                          kind: "action" as const,
                          id: RIGHT_PANEL_BROWSER_TAB,
                          title: t("browserTab.label"),
                          icon: SvgGlobe,
                          onSelect: () => {
                            insideChangeRef.current = true;
                            browser.openPage();
                          },
                        },
                      ]
                    : []),
                  ...(chromeAvailable && sessionId !== null
                    ? [
                        {
                          kind: "action" as const,
                          id: RIGHT_PANEL_CHROME_TAB,
                          title: t("chromeTab.label"),
                          icon: SvgMonitor,
                          onSelect: () => {
                            insideChangeRef.current = true;
                            dispatch({ type: "openChrome" });
                          },
                        },
                      ]
                    : []),
                  ...(hasSources
                    ? [
                        {
                          kind: "action" as const,
                          id: RIGHT_PANEL_SOURCES_TAB,
                          title: t("sourcesTab.label"),
                          icon: SvgSearchMenu,
                          onSelect: () =>
                            dispatch({
                              type: "showTab",
                              tabId: RIGHT_PANEL_SOURCES_TAB,
                            }),
                        },
                      ]
                    : []),
                ]}
              />
            }
            toolbar={
              // As Craft's: reload before the search or the file's path. The
              // Browser has its own URL bar.
              shown !== RIGHT_PANEL_SOURCES_TAB &&
              !browser.shown &&
              !chromeShown && (
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
                  {/* The shown file's preview puts its actions here */}
                  {shownFile && <div ref={setActionsSlot} />}
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
              {chromeShown && sessionId !== null && (
                <div
                  id={panelContentDomId(RIGHT_PANEL_CHROME_TAB)}
                  role="tabpanel"
                  aria-labelledby={panelTabDomId(RIGHT_PANEL_CHROME_TAB)}
                  className="absolute inset-0 overflow-y-auto"
                >
                  <ChromeBrowserPanel
                    key={sessionId}
                    sessionId={sessionId}
                    chrome={chrome}
                  />
                </div>
              )}
              {browser.sessionId !== null && (
                // One view for all the browser's tabs, mounted while the
                // browser is open: a switch of tabs keeps its connection
                <div
                  id={panelContentDomId(browser.tabId)}
                  role="tabpanel"
                  aria-labelledby={panelTabDomId(browser.tabId)}
                  aria-hidden={!(open && browser.shown)}
                  inert={!(open && browser.shown)}
                  className={cn(
                    "absolute inset-0",
                    !(open && browser.shown) &&
                      "invisible pointer-events-none [content-visibility:hidden]"
                  )}
                >
                  {/* Keyed: another chat's tab ids can match this chat's */}
                  <BrowserPanel
                    key={browser.sessionId}
                    sessionId={browser.sessionId}
                    stream={browser.stream}
                  />
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
                      <PreviewActionsSlotContext.Provider
                        value={visible ? actionsSlot : null}
                      >
                        <PublishedFilePreview file={file} />
                      </PreviewActionsSlotContext.Provider>
                    </div>
                  );
                })}
            </div>
          </OutputPanelLayout>
          {/* Beside the room of the toggle, which the panel places over the
              workspace's end */}
          {/* end-12 is --panel-toggle-reserve's 48px (globals.css) */}
          <Section width="fit" height="auto" className="absolute end-12 top-2">
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
          </Section>
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
  const { incognitoEnabled } = useIncognito();
  const settings = useSettings();
  const browserAvailable =
    (settings.chat_browser_available ?? false) && !incognitoEnabled;
  const chromeAvailable =
    (settings.chrome_browser_available ?? false) && !incognitoEnabled;
  const reloadFiles = useCallback(async () => {
    if (sessionId !== null) await reloadChatPublishedFiles(sessionId);
  }, [sessionId]);
  const userMessageCount = useChatSessionStore((store) => {
    const tree =
      sessionId === null
        ? undefined
        : store.sessions.get(sessionId)?.messageTree;
    let count = 0;
    tree?.forEach((message) => {
      if (message.type === "user") count += 1;
    });
    return count;
  });
  return (
    <ChatRightPanel
      {...props}
      sessionId={sessionId}
      state={state}
      dispatch={dispatch}
      files={files}
      reloadFiles={reloadFiles}
      browserAvailable={browserAvailable}
      chromeAvailable={chromeAvailable}
      userMessageCount={userMessageCount}
    />
  );
}

/** Opens a published file in the open chat's right panel. */
export function openPublishedFileInChat(
  file: PublishedFile,
  pinVersion = false
): void {
  const store = useChatSessionStore.getState();
  store.updateCurrentRightPanel(
    openCardFileAction(
      file,
      publishedFilesOf(store.sessions.get(store.currentSessionId ?? "")),
      pinVersion
    )
  );
}

/** The open chat's right panel, for a reply's file cards. */
export const CHAT_FILES_PANEL: Omit<PublishedFilesPanel, "chatId"> = {
  openFile: openPublishedFileInChat,
  showFiles: () =>
    useChatSessionStore.getState().updateCurrentRightPanel({
      type: "showTab",
      tabId: RIGHT_PANEL_FILES_TAB,
    }),
};
