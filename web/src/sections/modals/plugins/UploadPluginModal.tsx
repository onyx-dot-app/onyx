"use client";

import { useEffect, useRef, useState, type ReactNode } from "react";
import { useTranslations } from "next-intl";
import {
  Button,
  Card,
  InputCheckbox,
  MessageCard,
  Modal,
  Text,
} from "@opal/components";
import { Content, InputHorizontal, Section } from "@opal/layouts";
import { SvgBlocks, SvgUploadCloud } from "@opal/icons";
import type { RichStr } from "@opal/types";
import { needsAttention } from "@/lib/plugins/needs";
import type { PluginUploadPreview } from "@/lib/plugins/types";
import { pluginUploadKind } from "@/lib/plugins/upload";
import {
  inspectPluginUpload,
  inspectSkillBundle,
  savePluginUpload,
  type PluginUploadResult,
} from "@/lib/skills/api";
import type { PreparedSkillBundle } from "@/lib/skills/bundleUpload";
import type { SkillCreationDraft } from "@/lib/skills/creationDraft";
import PluginNeedList from "@/sections/plugins/PluginNeedList";
import SkillBundlePicker from "@/sections/skills/SkillBundlePicker";

type UploadStep =
  | { step: "pick"; bundle: PreparedSkillBundle | null }
  | { step: "skill"; bundle: PreparedSkillBundle }
  | {
      step: "plugin";
      bundle: PreparedSkillBundle;
      preview: PluginUploadPreview;
      saveAsNew: boolean;
    };

interface UploadPluginModalProps {
  open: boolean;
  onClose: () => void;
  onContinueSkill: (draft: SkillCreationDraft) => void;
  onSaved: (result: PluginUploadResult, needsAttention: boolean) => void;
}

interface PreviewSectionProps {
  title: string | RichStr;
  children: ReactNode;
}

function PreviewSection({ title, children }: PreviewSectionProps) {
  return (
    <Section gap={1} alignItems="stretch" height="auto">
      <Text as="p" font="main-ui-action" color="text-04">
        {title}
      </Text>
      {children}
    </Section>
  );
}

interface PluginPreviewProps {
  preview: PluginUploadPreview;
  saveAsNew: boolean;
  busy: boolean;
  onSaveAsNewChange: (saveAsNew: boolean) => void;
}

function PluginPreview({
  preview,
  saveAsNew,
  busy,
  onSaveAsNewChange,
}: PluginPreviewProps) {
  const t = useTranslations("plugins.upload");
  const { target, manifest } = preview;
  const showSaveAsNew = target.kind === "new_version" || saveAsNew || busy;
  return (
    <Section gap={4} alignItems="stretch" height="auto">
      <Content
        icon={SvgBlocks}
        font="main-content-emphasis"
        title={manifest.name}
        description={manifest.description ?? undefined}
        badge={
          manifest.version
            ? { title: t("version", { version: manifest.version }) }
            : undefined
        }
      />
      <MessageCard
        variant="info"
        outerPadding={1}
        innerPadding={1}
        title={
          target.kind === "new_version"
            ? t("target.newVersion", {
                name: target.plugin_name,
                version: target.version_number,
              })
            : t("target.newPlugin", { name: target.plugin_name })
        }
        bottomChildren={
          showSaveAsNew ? (
            <InputHorizontal
              withLabel
              title={t("saveAsNew.label")}
              description={t("saveAsNew.description")}
            >
              <InputCheckbox
                aria-label={t("saveAsNew.label")}
                checked={saveAsNew}
                disabled={busy}
                onCheckedChange={onSaveAsNewChange}
              />
            </InputHorizontal>
          ) : undefined
        }
      />
      {preview.name_conflicts.length > 0 && (
        <MessageCard
          variant="warning"
          outerPadding={1}
          innerPadding={1}
          title={t("willBeOff", { names: preview.name_conflicts.join(", ") })}
        />
      )}
      {preview.skills.length > 0 && (
        <PreviewSection
          title={t("sections.skills", { count: preview.skills.length })}
        >
          {preview.skills.map((skill) => (
            <Card key={skill.path} padding={2}>
              <Content
                font="main-ui-action"
                title={skill.name}
                description={skill.description}
              />
              {skill.warnings.map((warning) => (
                <Text
                  key={warning}
                  as="p"
                  font="secondary-body"
                  color="status-warning-05"
                >
                  {warning}
                </Text>
              ))}
            </Card>
          ))}
        </PreviewSection>
      )}
      {preview.needs.length > 0 && (
        <PreviewSection
          title={t("sections.integrations", { count: preview.needs.length })}
        >
          <Text as="p" font="secondary-body" color="text-03">
            {preview.will_enable
              ? t("integrationsNote")
              : t("integrationsNoteOff")}
          </Text>
          <PluginNeedList needs={preview.needs} interactive={false} />
        </PreviewSection>
      )}
      {manifest.unused_parts.length > 0 && (
        <PreviewSection title={t("sections.unused")}>
          <Text as="p" font="secondary-body" color="text-03">
            {manifest.unused_parts
              .map((part) => t(`unusedParts.${part}`))
              .join(", ")}
          </Text>
        </PreviewSection>
      )}
      {preview.warnings.length > 0 && (
        <MessageCard
          variant="warning"
          outerPadding={1}
          innerPadding={1}
          title={t("sections.warnings")}
          bottomChildren={
            <Section gap={1} alignItems="stretch" height="auto">
              {preview.warnings.map((warning) => (
                <Text key={warning} as="p" font="secondary-body">
                  {warning}
                </Text>
              ))}
            </Section>
          }
        />
      )}
    </Section>
  );
}

function UploadPluginModalContent({
  onClose,
  onContinueSkill,
  onSaved,
  onBusyChange,
}: Omit<UploadPluginModalProps, "open"> & {
  onBusyChange: (busy: boolean) => void;
}) {
  const t = useTranslations("plugins.upload");
  const [state, setState] = useState<UploadStep>({
    step: "pick",
    bundle: null,
  });
  const [busy, setBusyState] = useState<"read" | "save" | null>(null);
  const [preparing, setPreparing] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const mounted = useRef(true);

  useEffect(() => {
    mounted.current = true;
    return () => {
      mounted.current = false;
    };
  }, []);

  function setBusy(next: "read" | "save" | null) {
    setBusyState(next);
    onBusyChange(next !== null);
  }

  function failure(caught: Error | null, fallback: string): string {
    return caught?.message || fallback;
  }

  async function read(bundle: PreparedSkillBundle, saveAsNew: boolean) {
    setBusy("read");
    setError(null);
    try {
      if ((await pluginUploadKind(bundle)) === "skill") {
        setState({ step: "skill", bundle });
        return;
      }
      const preview = await inspectPluginUpload(bundle.file, saveAsNew);
      setState({ step: "plugin", bundle, preview, saveAsNew });
    } catch (caught) {
      setState({ step: "pick", bundle });
      setError(
        failure(caught instanceof Error ? caught : null, t("readFailed"))
      );
    } finally {
      setBusy(null);
    }
  }

  async function continueSkill(bundle: PreparedSkillBundle) {
    setBusy("read");
    setError(null);
    try {
      const contents = await inspectSkillBundle(bundle.file);
      onContinueSkill({
        contents,
        upload: {
          file: bundle.file,
          displayName: bundle.displayName,
          entries: contents.files,
          containsSkillMd: true,
        },
      });
    } catch (caught) {
      setError(
        failure(caught instanceof Error ? caught : null, t("readFailed"))
      );
    } finally {
      setBusy(null);
    }
  }

  async function save(bundle: PreparedSkillBundle, saveAsNew: boolean) {
    setBusy("save");
    setError(null);
    try {
      const result = await savePluginUpload(bundle.file, saveAsNew);
      onSaved(
        result,
        result.enabled && needsAttention(result.plugin.plugin?.needs ?? [])
      );
    } catch (caught) {
      setError(
        failure(caught instanceof Error ? caught : null, t("saveFailed"))
      );
    } finally {
      setBusy(null);
    }
  }

  const bundle = state.bundle;
  const disabled = busy !== null || preparing;

  return (
    <>
      <Modal.Header
        icon={SvgUploadCloud}
        title={t("title")}
        description={t("description")}
        onClose={disabled ? undefined : onClose}
      />
      <Modal.Body>
        <SkillBundlePicker
          value={bundle}
          compact={state.step !== "pick"}
          disabled={disabled}
          allowPlugin
          busyLabel={busy === "read" ? t("reading") : undefined}
          onPreparingChange={setPreparing}
          onChange={(next) => {
            if (mounted.current) void read(next, false);
          }}
          onError={(message) => {
            setState({ step: "pick", bundle: null });
            setError(message);
          }}
        />
        {state.step === "pick" && (
          <Section gap={1} alignItems="stretch" height="auto">
            <Text as="p" font="main-ui-body" color="text-02">
              {t("requirements.title")}
            </Text>
            <Text as="p" font="secondary-body" color="text-03">
              {t("requirements.skills")}
            </Text>
            <Text as="p" font="secondary-body" color="text-03">
              {t("requirements.mcp")}
            </Text>
            <Text as="p" font="secondary-body" color="text-03">
              {t("requirements.other")}
            </Text>
          </Section>
        )}
        {state.step === "skill" && (
          <MessageCard
            variant="info"
            outerPadding={1}
            innerPadding={1}
            title={t("skillOnly.title")}
            description={t("skillOnly.description")}
          />
        )}
        {state.step === "plugin" && (
          <PluginPreview
            preview={state.preview}
            saveAsNew={state.saveAsNew}
            busy={disabled}
            onSaveAsNewChange={(saveAsNew) => {
              setState({ ...state, saveAsNew });
              void read(state.bundle, saveAsNew);
            }}
          />
        )}
        {error && (
          <Section role="alert" height="auto" alignItems="start">
            <Text as="p" font="secondary-body" color="status-error-05">
              {error}
            </Text>
          </Section>
        )}
      </Modal.Body>
      <Modal.Footer>
        <Button prominence="secondary" disabled={disabled} onClick={onClose}>
          {t("cancel")}
        </Button>
        {state.step === "skill" ? (
          <Button
            disabled={disabled}
            onClick={() => void continueSkill(state.bundle)}
          >
            {t("skillOnly.continue")}
          </Button>
        ) : (
          <Button
            icon={SvgUploadCloud}
            disabled={disabled || state.step !== "plugin"}
            onClick={() =>
              state.step === "plugin" &&
              void save(state.bundle, state.saveAsNew)
            }
          >
            {busy === "save" ? t("saving") : t("save")}
          </Button>
        )}
      </Modal.Footer>
    </>
  );
}

export default function UploadPluginModal({
  open,
  onClose,
  onContinueSkill,
  onSaved,
}: UploadPluginModalProps) {
  const [busy, setBusy] = useState(false);
  return (
    <Modal open={open} onOpenChange={(isOpen) => !isOpen && !busy && onClose()}>
      <Modal.Content width="md" maxHeight="85dvh">
        {open && (
          <UploadPluginModalContent
            onClose={onClose}
            onContinueSkill={onContinueSkill}
            onSaved={onSaved}
            onBusyChange={setBusy}
          />
        )}
      </Modal.Content>
    </Modal>
  );
}
