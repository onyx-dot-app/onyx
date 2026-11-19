"use client";

import {
  memo,
  type ReactNode,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
} from "react";
import { useTranslations } from "next-intl";
import { useShallow } from "zustand/react/shallow";
import { Button } from "@opal/components";
import { Section } from "@opal/layouts";
import { SvgFiles, SvgSearchMenu, SvgX } from "@opal/icons";
import { cn, richNodes } from "@opal/utils";
import type { PublishedFile } from "@/app/app/services/streamingModels";
import {
  useChatSessionStore,
  useCurrentRightPanelState,
} from "@/app/app/stores/useChatSessionStore";
import { useCurrentPublishedFiles } from "@/lib/chat/hooks";
import {
  filesSharingALabel,
  publishOrder,
  publishedFileLabel,
  publishedFilePath,
} from "@/lib/chat/publishedFiles";
import {
  RIGHT_PANEL_FILES_TAB,
  RIGHT_PANEL_SOURCES_TAB,
  rightPanelFileTab,
  type ChatRightPanelAction,
  type ChatRightPanelState,
} from "@/lib/chat/rightPanel";
import { OUTPUT_PANEL_HEADER_CONTROL_WIDTH } from "@/lib/outputPanel/layout";
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

interface ChatRightPanelProps {
  // The chat whose panel this is
  sessionId: string | null;
  open: boolean;
  state: ChatRightPanelState;
  dispatch: (action: ChatRightPanelAction) => void;
  // The newest publish of each path, newest first
  files: PublishedFile[];
  // The place of each of the chat's files in publish order, by file ID
  publishOrder: ReadonlyMap<string, number>;
  // The Sources tab's content; `hasSources` says whether it has any
  sources: ReactNode;
  hasSources: boolean;
}

/**
 * The chat's right panel, built from the output panel that Craft also uses:
 * a tab strip with the Files list, Sources and a tab per open file, a URL
 * bar, and the active tab's content, beside the page at a width the user can
 * drag, or over it at full size. On a workspace too narrow for both it covers
 * the page. Escape leaves full screen, then closes the active file's tab,
 * back on its tile, then closes the panel.
 */
export const ChatRightPanel = memo(function ChatRightPanel({
  sessionId,
  open,
  state,
  dispatch,
  files,
  publishOrder,
  sources,
  hasSources,
}: ChatRightPanelProps) {
  const t = useTranslations("chat.rightPanel");
  const fileByTab = new Map(
    state.fileTabs.map((file) => [rightPanelFileTab(file.file_id), file])
  );
  const shown =
    state.activeId === RIGHT_PANEL_SOURCES_TAB || fileByTab.has(state.activeId)
      ? state.activeId
      : RIGHT_PANEL_FILES_TAB;
  const shownFile = fileByTab.get(shown);
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
  // Tabs of one shown name show their path. A tab says it is an earlier
  // version when the listed file of its path was published after its file.
  const sharingALabel = filesSharingALabel(state.fileTabs);
  const listedByPath = new Map(files.map((file) => [file.path, file.file_id]));
  const publishedAt = (fileId: string) => publishOrder.get(fileId) ?? -1;
  const tabs: PanelTabItem[] = [
    ...fixedTabs,
    ...state.fileTabs.map((file): PanelTabItem => {
      const name = sharingALabel.has(file.file_id)
        ? publishedFilePath(file)
        : publishedFileLabel(file);
      const listed = listedByPath.get(file.path);
      const tab = {
        id: rightPanelFileTab(file.file_id),
        icon: getFileIcon(file.name),
        closable: true,
        movable: true,
      };
      if (
        listed === undefined ||
        publishedAt(listed) <= publishedAt(file.file_id)
      )
        return { ...tab, label: name };
      return {
        ...tab,
        label: t.markup("fileTab.earlierVersion", {
          name,
          isolate: (chunks) => chunks,
        }),
        // The name shows in its own direction, apart from the sentence
        content: richNodes(
          t.rich("fileTab.earlierVersion", {
            name,
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
  // size over the page. Outside the app chrome the panel keeps 25rem.
  const workspace = useContext(AppWorkspaceElementsContext);
  const noElement = useRef<HTMLDivElement>(null);
  const closeButtonRef = useRef<HTMLElement>(null);
  const full = state.mode === "full";
  const layout = useOutputPanelWorkspace({
    workspaceRef: workspace?.workspace ?? noElement,
    pageRef: workspace?.page ?? noElement,
    coverFocusRef: closeButtonRef,
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
  // citation control, the Files button) or a tile opens a file: to the
  // file's preview, else to the active tab. A switch in the tab strip leaves
  // focus where it is. Escape on a file goes back to its tile.
  const bodyRef = useRef<HTMLDivElement>(null);
  const insideChangeRef = useRef(false);
  const returnFocusRef = useRef<string | null>(null);
  const shownRef = useRef({ open, shown });
  useEffect(() => {
    const previous = shownRef.current;
    shownRef.current = { open, shown };
    const inside = insideChangeRef.current;
    insideChangeRef.current = false;
    // The tile to go back to only counts when the Files list comes next
    const returnTo = returnFocusRef.current;
    returnFocusRef.current = null;
    if (!open || (previous.open && previous.shown === shown)) return;
    const body = bodyRef.current;
    if (!body) return;
    if (returnTo !== null && shown === RIGHT_PANEL_FILES_TAB) {
      body
        .querySelector<HTMLElement>(
          `[data-published-file="${CSS.escape(returnTo)}"] [role="button"]`
        )
        ?.focus({ preventScroll: true });
      return;
    }
    if (inside) return;
    const target = shownFile
      ? body.querySelector<HTMLElement>(
          `[data-published-preview="${CSS.escape(shownFile.file_id)}"]`
        )
      : document.getElementById(panelTabDomId(shown));
    target?.focus({ preventScroll: true });
  }, [open, shown, shownFile]);

  const selectTab = useCallback(
    (tabId: string) => {
      insideChangeRef.current = true;
      dispatch({ type: "showTab", tabId });
    },
    [dispatch]
  );
  const openFile = useCallback(
    (file: PublishedFile) => dispatch({ type: "openFile", file }),
    [dispatch]
  );
  const close = useCallback(() => dispatch({ type: "closePanel" }), [dispatch]);
  const escape = () => {
    if (!shownFile) {
      close();
      return;
    }
    returnFocusRef.current = shownFile.file_id;
    dispatch({ type: "closeTab", tabId: shown });
  };

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
    <ChatSidePanel
      open={open}
      onEscape={escape}
      width={
        layout.workspaceWidth === 0
          ? "default"
          : layout.covers
            ? "cover"
            : layout.mediumWidth
      }
      focusOnOpen={false}
      animate={!layout.dragging}
      shows={shown}
    >
      <aside
        aria-label={
          shown === RIGHT_PANEL_SOURCES_TAB
            ? t("sourcesTab.label")
            : t("filesTab.label")
        }
        className="relative h-full w-full bg-background-neutral-00 border-s"
      >
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
                insideChangeRef.current = true;
                dispatch({ type: "reorderTab", tabId, overTabId: over.id });
              }}
            />
          }
          toolbar={
            shown === RIGHT_PANEL_FILES_TAB ? (
              <PanelUrlBar
                searchValue={state.search}
                onSearchChange={(search) =>
                  dispatch({ type: "setSearch", search })
                }
                placeholder={t("filesTab.search.placeholder")}
              />
            ) : shownFile ? (
              <PanelUrlBar displayUrl={publishedFilePath(shownFile)} />
            ) : undefined
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
                  emptyLabel={query ? t("filesTab.search.empty") : undefined}
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
            {state.fileTabs
              .filter((file) =>
                retainedTabs.has(rightPanelFileTab(file.file_id))
              )
              .map((file) => {
                const tabId = rightPanelFileTab(file.file_id);
                const visible = open && tabId === shown;
                return (
                  <div
                    key={tabId}
                    id={panelContentDomId(tabId)}
                    role="tabpanel"
                    aria-labelledby={panelTabDomId(tabId)}
                    aria-hidden={!visible}
                    inert={!visible}
                    className={cn(
                      "absolute inset-0",
                      !visible && "invisible pointer-events-none"
                    )}
                  >
                    <PublishedFilePreview file={file} />
                  </div>
                );
              })}
          </div>
        </OutputPanelLayout>
        <Section
          flexDirection="row"
          width="fit"
          height="fit"
          gap={0.25}
          className="absolute end-2 top-3"
        >
          {!layout.narrow && layout.workspaceWidth > 0 && (
            <PanelSizeButton
              full={full}
              expandLabel={t("expandButton.label")}
              restoreLabel={t("restoreButton.label")}
              onToggle={() =>
                dispatch({ type: "setMode", mode: full ? "medium" : "full" })
              }
            />
          )}
          <Button
            ref={closeButtonRef}
            icon={SvgX}
            prominence="tertiary"
            size="sm"
            onClick={close}
            tooltip={t("closeButton.label")}
            aria-label={t("closeButton.label")}
          />
        </Section>
        {layout.workspaceWidth > 0 &&
          !layout.narrow && (
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
  );
});

const NO_PUBLISH_ORDER: ReadonlyMap<string, number> = new Map();

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
  const files = useCurrentPublishedFiles();
  const order = useChatSessionStore(
    useShallow((store) => {
      const session = store.sessions.get(store.currentSessionId ?? "");
      return session
        ? publishOrder(session.loadedPublishedFiles, session.messageTree)
        : NO_PUBLISH_ORDER;
    })
  );
  return (
    <ChatRightPanel
      {...props}
      sessionId={sessionId}
      state={state}
      dispatch={dispatch}
      files={files}
      publishOrder={order}
    />
  );
}

/** Opens a published file in the open chat's right panel (a reply card). */
export function openPublishedFileInChat(file: PublishedFile): void {
  useChatSessionStore
    .getState()
    .updateCurrentRightPanel({ type: "openFile", file });
}
