"use client";

import { useEffect, useEffectEvent, useRef, useState } from "react";
import { useTranslations } from "next-intl";
import {
  Button,
  Card,
  Dropdown,
  FilePickerButton,
  InputTypeIn,
  Text,
} from "@opal/components";
import {
  ConfirmationModalLayout,
  IllustrationContent,
  Section,
  toast,
} from "@opal/layouts";
import {
  SvgArrowLeft,
  SvgArrowRight,
  SvgGlobe,
  SvgMoreHorizontal,
  SvgTrash,
} from "@opal/icons";
import { IconLoader } from "@opal/loaders";
import { clearBrowserData, uploadBrowserFiles } from "@/lib/chat/browser/api";
import type { BrowserStream } from "@/lib/chat/browser/hooks";
import {
  browserOriginLabel,
  browserUrlFromInput,
  isBlankBrowserPage,
} from "@/lib/chat/browser/stream";
import type {
  BrowserConnectionState,
  BrowserTab,
  BrowserViewerControl,
  BrowserViewerMessage,
} from "@/lib/chat/browser/types";
import { PanelUrlBar } from "@/sections/output-panel/PanelUrlBar";
import { BrowserSurface } from "@/sections/chat/browser/BrowserSurface";

interface BrowserPanelProps {
  sessionId: string;
  // The chat's browser stream; the right panel owns it, so that its tab
  // strip lists the browser's pages
  stream: BrowserStream;
  // A view only: no control, navigation, prompt answers or input
  readOnly?: boolean;
}

/**
 * The view of the chat's browser, on the page that the browser selects for
 * this viewer: a URL bar, the control switch and the live view, with the
 * page's dialogs and file choosers. The right panel's tab strip lists and
 * switches the pages, as T3 Code's right panel lists its browser tabs.
 */
export function BrowserPanel({
  sessionId,
  stream,
  readOnly = false,
}: BrowserPanelProps) {
  const t = useTranslations("chat.browser");
  const { state, send } = stream;
  const { connection, tabs, selectedTabId, control } = state;
  const selectedTab = tabs.find((tab) => tab.id === selectedTabId) ?? null;
  // The agent's cursor shows only on the tab that it moved on
  const agentPointer =
    selectedTab !== null && state.agentPointer?.tab === selectedTab.id
      ? state.agentPointer.pointer
      : null;
  const controlling = !readOnly && control === "you";
  // Only the controller answers the page's file chooser
  const fileChooser = controlling ? state.fileChooser : null;

  // The URL bar shows the tab's URL until the user edits it; each tab keeps
  // its own draft until its navigate is sent
  const [drafts, setDrafts] = useState<ReadonlyMap<string, string>>(
    () => new Map()
  );
  const editedUrl =
    selectedTabId !== null ? (drafts.get(selectedTabId) ?? null) : null;
  const setDraft = (tab: string, url: string | null) =>
    setDrafts((current) => {
      const next = new Map(current);
      if (url === null) next.delete(tab);
      else next.set(tab, url);
      return next;
    });
  const navigate = () => {
    if (selectedTabId === null) return;
    const url = browserUrlFromInput(editedUrl ?? "");
    if (url && !send({ type: "navigate", url })) return;
    setDraft(selectedTabId, null);
  };
  const surfaceInputRef = useRef<HTMLTextAreaElement | null>(null);
  const focusPage = () => {
    // Only a page the user still controls takes the focus back
    const input = surfaceInputRef.current;
    if (input && !input.disabled) input.focus({ preventScroll: true });
  };
  const answerFileChooser = (id: string, paths: string[]): boolean => {
    if (stream.answerFileChooser(id, paths)) return true;
    toast.error(t("answerError"));
    return false;
  };

  const [confirmingClear, setConfirmingClear] = useState(false);
  const [clearing, setClearing] = useState(false);
  const clear = async () => {
    setClearing(true);
    try {
      await clearBrowserData(sessionId);
      toast.success(t("clearData.done"));
      setConfirmingClear(false);
    } catch (error) {
      console.error("Failed to clear the browser data", { sessionId, error });
      toast.error(t("clearData.error"));
    } finally {
      setClearing(false);
    }
  };

  const live = connection === "live";
  return (
    <Section
      height="full"
      gap={0}
      alignItems="stretch"
      justifyContent="start"
      data-chat-browser
    >
      <PanelUrlBar
        leading={
          readOnly ? undefined : (
            <>
              <Button
                icon={SvgArrowLeft}
                prominence="tertiary"
                size="md"
                disabled={!controlling || !selectedTab}
                onClick={() => send({ type: "history", delta: -1 })}
                tooltip={t("urlBar.back")}
                aria-label={t("urlBar.back")}
              />
              <Button
                icon={SvgArrowRight}
                prominence="tertiary"
                size="md"
                disabled={!controlling || !selectedTab}
                onClick={() => send({ type: "history", delta: 1 })}
                tooltip={t("urlBar.forward")}
                aria-label={t("urlBar.forward")}
              />
            </>
          )
        }
        refresh={
          readOnly
            ? undefined
            : {
                label: t("urlBar.reload"),
                onRefresh:
                  controlling && selectedTab
                    ? () => send({ type: "reload" })
                    : undefined,
                isRefreshing: selectedTab?.loading ?? false,
                isUserRefreshing: false,
              }
        }
        // Only the controller navigates; others see the tab's URL
        displayUrl={selectedTab?.url}
        searchValue={editedUrl ?? selectedTab?.url ?? ""}
        onSearchChange={
          controlling && selectedTab
            ? (value) => setDraft(selectedTab.id, value)
            : undefined
        }
        onSubmit={navigate}
        inputLabel={t("urlBar.label")}
        placeholder={t("urlBar.placeholder")}
      >
        {!readOnly && (
          <Dropdown width={50} align="end">
            <Dropdown.Trigger asChild>
              <Button
                icon={SvgMoreHorizontal}
                prominence="tertiary"
                size="md"
                tooltip={t("moreMenu.label")}
                aria-label={t("moreMenu.label")}
              />
            </Dropdown.Trigger>
            <Dropdown.Data
              sizePreset="secondary"
              label={t("moreMenu.label")}
              items={[
                {
                  kind: "action",
                  id: "clear",
                  title: t("clearData.action"),
                  icon: SvgTrash,
                  danger: true,
                  onSelect: () => setConfirmingClear(true),
                },
              ]}
            />
          </Dropdown>
        )}
      </PanelUrlBar>
      {live && selectedTab !== null && !readOnly && (
        <ControlBar
          control={control}
          onTake={() => send({ type: "takeControl" })}
          onRelease={() => send({ type: "releaseControl" })}
        />
      )}
      <div className="relative min-h-0 flex-1 bg-background-tint-01">
        <BrowserSurface
          canvasRef={stream.canvasRef}
          control={control}
          viewport={state.viewport}
          hasFrame={stream.hasFrame && selectedTab !== null}
          agentPointer={agentPointer}
          send={send}
          inputRef={surfaceInputRef}
          dropInputRef={stream.dropInputRef}
        />
        {!live ||
        selectedTab === null ||
        (isBlankBrowserPage(selectedTab) &&
          !selectedTab.dialog &&
          !fileChooser) ? (
          <BrowserStatus
            status={live && selectedTab !== null ? "blank" : connection}
            readOnly={readOnly}
            onRetry={stream.retry}
            onNewTab={() => send({ type: "newTab" })}
          />
        ) : (
          // Shown only with a prompt, so it blocks no clicks on the page
          !readOnly &&
          (selectedTab.dialog || fileChooser) && (
            <Section
              height="auto"
              alignItems="stretch"
              gap={2}
              padding={2}
              className="absolute inset-x-0 top-0 z-30"
              data-browser-prompts
            >
              {selectedTab.dialog && (
                <DialogPrompt
                  // A new dialog starts with an empty answer
                  key={`${selectedTab.id}:${selectedTab.dialog.message}`}
                  dialog={selectedTab.dialog}
                  controlling={controlling}
                  onClosed={focusPage}
                  onAnswer={(accept, promptText) => {
                    const answer: BrowserViewerMessage = {
                      type: "dialog",
                      accept,
                    };
                    if (promptText !== undefined)
                      answer.promptText = promptText;
                    if (!send(answer)) toast.error(t("answerError"));
                  }}
                />
              )}
              {fileChooser && (
                <FileChooserPrompt
                  key={fileChooser.id}
                  sessionId={sessionId}
                  multiple={fileChooser.multiple}
                  origin={fileChooser.origin}
                  onClosed={focusPage}
                  onAnswer={(paths) => answerFileChooser(fileChooser.id, paths)}
                />
              )}
            </Section>
          )
        )}
      </div>
      {confirmingClear && (
        <ConfirmationModalLayout
          icon={SvgTrash}
          color="error"
          title={t("clearData.title")}
          description={t("clearData.description")}
          onClose={clearing ? undefined : () => setConfirmingClear(false)}
          submit={
            <Button
              variant="danger"
              disabled={clearing}
              onClick={() => void clear()}
            >
              {t("clearData.confirm")}
            </Button>
          }
        />
      )}
    </Section>
  );
}

interface ControlBarProps {
  control: BrowserViewerControl | null;
  onTake: () => void;
  onRelease: () => void;
}

/** Who drives the selected tab, and the switch to take or release it. */
function ControlBar({ control, onTake, onRelease }: ControlBarProps) {
  const t = useTranslations("chat.browser");
  const label =
    control === "you"
      ? t("control.you")
      : control === "agent"
        ? t("control.agent")
        : control === "another-viewer"
          ? t("control.anotherViewer")
          : t("control.none");
  return (
    <div className="shrink-0 border-t px-3 py-1">
      <Section flexDirection="row" justifyContent="between" gap={2}>
        <Text
          as="p"
          font="secondary-body"
          color="text-03"
          maxLines={1}
          role="status"
        >
          {label}
        </Text>
        {control === "you" ? (
          <Button prominence="secondary" size="sm" onClick={onRelease}>
            {t("control.release")}
          </Button>
        ) : (
          <Button
            prominence="secondary"
            size="sm"
            disabled={control === null || control === "another-viewer"}
            onClick={onTake}
          >
            {t("control.take")}
          </Button>
        )}
      </Section>
    </div>
  );
}

interface BrowserStatusProps {
  // The connection's state, or "blank" for a page with no URL yet
  status: BrowserConnectionState | "blank";
  // A view only: it waits for the agent and opens no page
  readOnly: boolean;
  onRetry: () => void;
  onNewTab: () => void;
}

/** The view's state while it has no page to show. */
function BrowserStatus({
  status,
  readOnly,
  onRetry,
  onNewTab,
}: BrowserStatusProps) {
  const t = useTranslations("chat.browser");
  const content = (() => {
    switch (
      readOnly && (status === "blank" || status === "live") ? "waiting" : status
    ) {
      case "waiting":
        return {
          icon: SvgGlobe,
          title: t("status.waiting.title"),
          description: t("status.waiting.description"),
        };
      case "blank":
        // As T3 Code's empty preview: the URL bar opens a page
        return {
          icon: SvgGlobe,
          title: t("status.blank.title"),
          description: t("status.blank.description"),
        };
      case "connecting":
        return { title: t("status.connecting"), busy: true };
      case "starting":
        return { title: t("status.starting"), busy: true };
      case "live":
        return {
          title: t("status.noTabs.title"),
          description: t("status.noTabs.description"),
          action: { label: t("tabs.new"), onClick: onNewTab },
        };
      case "disconnected":
        return {
          title: t("status.disconnected.title"),
          description: t("status.disconnected.description"),
          busy: true,
          action: { label: t("status.retry"), onClick: onRetry },
        };
      case "disabled":
        return {
          title: t("status.disabled.title"),
          description: t("status.disabled.description"),
        };
      case "unreachable":
        return {
          title: t("status.unreachable.title"),
          description: t("status.unreachable.description"),
          action: { label: t("status.retry"), onClick: onRetry },
        };
      case "error":
        return {
          title: t("status.error.title"),
          description: t("status.error.description"),
          action: { label: t("status.retry"), onClick: onRetry },
        };
    }
  })();
  return (
    <div
      className="absolute inset-0 z-30 bg-background-neutral-00"
      role="status"
    >
      <Section gap={2} padding={4}>
        {"busy" in content && content.busy && <IconLoader size={20} />}
        <IllustrationContent
          illustration={"icon" in content ? content.icon : undefined}
          title={content.title}
          description={
            "description" in content ? content.description : undefined
          }
          size="sm"
        />
        {"action" in content && content.action && (
          <Button prominence="secondary" onClick={content.action.onClick}>
            {content.action.label}
          </Button>
        )}
      </Section>
    </div>
  );
}

interface DialogPromptProps {
  dialog: NonNullable<BrowserTab["dialog"]>;
  controlling: boolean;
  onAnswer: (accept: boolean, promptText?: string) => void;
  // Runs when the dialog goes, to give the focus back to the page
  onClosed: () => void;
}

/** The page's alert, confirm or prompt dialog. */
function DialogPrompt({
  dialog,
  controlling,
  onAnswer,
  onClosed,
}: DialogPromptProps) {
  const t = useTranslations("chat.browser");
  const [promptText, setPromptText] = useState("");
  const isPrompt = dialog.type === "prompt";
  // The controller answers at once: focus goes to the answer field, else
  // to Accept
  const cardRef = usePromptFocus(controlling, onClosed);
  return (
    <Card
      ref={cardRef}
      padding={2}
      role="dialog"
      aria-label={t("dialog.label")}
    >
      <Section alignItems="stretch" gap={2} height="auto">
        {dialog.origin !== null && (
          <Text
            as="p"
            font="main-ui-action"
            color="text-05"
            wordWrap="wrap-anywhere"
          >
            {t("dialog.from", { origin: browserOriginLabel(dialog.origin) })}
          </Text>
        )}
        <Text
          as="p"
          font="main-ui-body"
          color="text-04"
          wordWrap="wrap-anywhere"
        >
          {dialog.message}
        </Text>
        {controlling ? (
          <>
            {isPrompt && (
              <InputTypeIn
                data-prompt-focus
                aria-label={t("dialog.response")}
                placeholder={t("dialog.responsePlaceholder")}
                value={promptText}
                onChange={(event) => setPromptText(event.target.value)}
              />
            )}
            <Section flexDirection="row" justifyContent="end" gap={2}>
              <Button
                prominence="secondary"
                size="sm"
                onClick={() => onAnswer(false)}
              >
                {t("dialog.dismiss")}
              </Button>
              <Button
                size="sm"
                data-prompt-focus
                onClick={() =>
                  onAnswer(true, isPrompt ? promptText : undefined)
                }
              >
                {t("dialog.accept")}
              </Button>
            </Section>
          </>
        ) : (
          <Text as="p" font="secondary-body" color="text-03">
            {t("dialog.takeControl")}
          </Text>
        )}
      </Section>
    </Card>
  );
}

interface FileChooserPromptProps {
  sessionId: string;
  multiple: boolean;
  origin: string | null;
  // False when the answer was not sent
  onAnswer: (paths: string[]) => boolean;
  // Runs when the chooser goes, to give the focus back to the page
  onClosed: () => void;
}

/** The page asks for files: upload the picked ones into the chat's VM. */
function FileChooserPrompt({
  sessionId,
  multiple,
  origin,
  onAnswer,
  onClosed,
}: FileChooserPromptProps) {
  const t = useTranslations("chat.browser");
  const [uploading, setUploading] = useState(false);
  const cardRef = usePromptFocus(true, onClosed);
  // The chooser closes, or the user loses control, while the upload runs
  const shownRef = useRef(false);
  useEffect(() => {
    shownRef.current = true;
    return () => {
      shownRef.current = false;
    };
  }, []);
  const upload = async (files: File[]) => {
    if (files.length === 0) return;
    setUploading(true);
    try {
      const paths = await uploadBrowserFiles(
        sessionId,
        multiple ? files : files.slice(0, 1)
      );
      if (shownRef.current && !onAnswer(paths)) setUploading(false);
    } catch (error) {
      console.error("Failed to upload files for the page", {
        sessionId,
        error,
      });
      if (!shownRef.current) return;
      toast.error(t("fileChooser.error"));
      setUploading(false);
    }
  };
  return (
    <Card
      ref={cardRef}
      padding={2}
      role="dialog"
      aria-label={t("fileChooser.label")}
    >
      <Section alignItems="stretch" gap={2} height="auto">
        <Text
          as="p"
          font="main-ui-body"
          color="text-04"
          wordWrap="wrap-anywhere"
        >
          {origin === null
            ? t(multiple ? "fileChooser.askMany" : "fileChooser.askOne")
            : t(
                multiple ? "fileChooser.askManyFrom" : "fileChooser.askOneFrom",
                { origin: browserOriginLabel(origin) }
              )}
        </Text>
        <Section flexDirection="row" justifyContent="end" gap={2}>
          <Button
            prominence="secondary"
            size="sm"
            disabled={uploading}
            onClick={() => onAnswer([])}
          >
            {t("fileChooser.cancel")}
          </Button>
          <FilePickerButton
            data-prompt-focus
            size="sm"
            icon={uploading ? IconLoader : undefined}
            disabled={uploading}
            multiple={multiple}
            inputLabel={t("fileChooser.inputLabel")}
            onFiles={(files) => void upload(files)}
          >
            {multiple
              ? t("fileChooser.chooseMany")
              : t("fileChooser.chooseOne")}
          </FilePickerButton>
        </Section>
      </Section>
    </Card>
  );
}

/**
 * Moves focus to a page prompt's first `data-prompt-focus` element for its
 * controller, and gives it back to the page when the prompt goes while it
 * still holds the focus. Returns the ref for the prompt's card.
 */
function usePromptFocus(controlling: boolean, onClosed: () => void) {
  const cardRef = useRef<HTMLDivElement | null>(null);
  useEffect(() => {
    if (!controlling) return;
    cardRef.current?.querySelector<HTMLElement>("[data-prompt-focus]")?.focus();
  }, [controlling]);
  const closed = useEffectEvent(onClosed);
  useEffect(() => {
    const card = cardRef.current;
    return () => {
      // The removed prompt leaves the focus on the body
      const active = document.activeElement;
      if (active === null || active === document.body || card?.contains(active))
        closed();
    };
  }, []);
  return cardRef;
}
