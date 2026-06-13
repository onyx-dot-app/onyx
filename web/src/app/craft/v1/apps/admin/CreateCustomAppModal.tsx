"use client";

import { useEffect, useRef, useState } from "react";
import Modal from "@/refresh-components/Modal";
import {
  Button,
  InputTypeIn,
  MessageCard,
  Text,
  Tooltip,
} from "@opal/components";
import { SvgUploadCloud } from "@opal/icons";
import { ListFieldInput } from "@/refresh-components/inputs/ListFieldInput";
import InputKeyValue, {
  KeyValue,
} from "@/refresh-components/inputs/InputKeyValue";
import { ExternalAppAdminResponse } from "@/app/craft/v1/apps/registry";
import {
  createCustomExternalApp,
  replaceCustomAppBundle,
  updateExternalApp,
} from "@/app/craft/services/externalAppsService";

interface CreateCustomAppModalProps {
  open: boolean;
  onClose: () => void;
  /** Invoked after a successful create/edit so callers can refresh their list. */
  onSaved: () => void;
  /** Null → create a new custom app; non-null → edit that app's config. */
  existingApp: ExternalAppAdminResponse | null;
}

/** Collapse a key-value list into a record, dropping rows with an empty key. */
function toRecord(items: KeyValue[]): Record<string, string> {
  const out: Record<string, string> = {};
  for (const { key, value } of items) {
    const trimmedKey = key.trim();
    if (trimmedKey) out[trimmedKey] = value;
  }
  return out;
}

/** Expand a record into editable rows, seeding one empty row when empty. */
function toKeyValues(record: Record<string, string>): KeyValue[] {
  const entries = Object.entries(record).map(([key, value]) => ({
    key,
    value,
  }));
  return entries.length > 0 ? entries : [{ key: "", value: "" }];
}

export default function CreateCustomAppModal({
  open,
  onClose,
  onSaved,
  existingApp,
}: CreateCustomAppModalProps) {
  const isEdit = existingApp !== null;

  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [upstreamPatterns, setUpstreamPatterns] = useState<string[]>([]);
  const [headers, setHeaders] = useState<KeyValue[]>([{ key: "", value: "" }]);
  const [orgCredentials, setOrgCredentials] = useState<KeyValue[]>([
    { key: "", value: "" },
  ]);
  const [file, setFile] = useState<File | null>(null);
  const [isSaving, setIsSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);

  // Re-seed every time the modal opens: from the existing app when editing,
  // blank when creating. Prevents a prior attempt from leaking in.
  useEffect(() => {
    if (!open) return;
    setName(existingApp?.name ?? "");
    setDescription(existingApp?.description ?? "");
    setUpstreamPatterns(existingApp?.upstream_url_patterns ?? []);
    setHeaders(
      existingApp
        ? toKeyValues(existingApp.auth_template)
        : [{ key: "", value: "" }]
    );
    setOrgCredentials(
      existingApp
        ? toKeyValues(existingApp.organization_credentials)
        : [{ key: "", value: "" }]
    );
    setFile(null);
    setError(null);
  }, [open, existingApp]);

  function handleFileChange(event: React.ChangeEvent<HTMLInputElement>) {
    setFile(event.target.files?.[0] ?? null);
  }

  // Headers and org credentials are optional; name + at least one upstream
  // pattern are required. A bundle is required only on create (optional on edit).
  const disabledCreateReason = (() => {
    if (isSaving) return "正在保存。";
    if (name.trim().length === 0) {
      return "创建自定义应用前请输入名称。";
    }
    if (upstreamPatterns.length === 0) {
      return "请至少添加一个上游 URL pattern。输入 pattern 后按 Enter。";
    }
    if (!isEdit && file === null) {
      return "创建自定义应用前请上传 bundle .zip 文件。";
    }
    return null;
  })();
  const createButton = (
    <Button onClick={save} disabled={disabledCreateReason !== null}>
      {isSaving
        ? isEdit
          ? "正在保存..."
          : "正在创建..."
        : isEdit
          ? "保存"
          : "创建"}
    </Button>
  );

  async function save() {
    setIsSaving(true);
    setError(null);
    // Edit is two calls (bundle + fields); track the bundle step to message
    // partial success accurately.
    let bundleSaved = false;
    try {
      if (existingApp) {
        // Bundle first (the failure-prone step): a failure here leaves fields
        // unsent. Clear the file so a retry doesn't re-upload it.
        if (file) {
          await replaceCustomAppBundle(existingApp.id, file);
          setFile(null);
          bundleSaved = true;
        }
        // enabled is toggled separately on the card.
        await updateExternalApp(existingApp.id, {
          name: name.trim(),
          description: description.trim(),
          upstream_url_patterns: upstreamPatterns,
          auth_template: toRecord(headers),
          organization_credentials: toRecord(orgCredentials),
        });
      } else {
        // Create: bundle is required (enforced by `canSave`).
        await createCustomExternalApp({
          name: name.trim(),
          description: description.trim(),
          upstream_url_patterns: upstreamPatterns,
          auth_template: toRecord(headers),
          organization_credentials: toRecord(orgCredentials),
          enabled: true,
          bundle: file!,
        });
      }
      onSaved();
      onClose();
    } catch (e) {
      // A step may have committed; refresh the list to reflect what persisted.
      onSaved();
      const detail = e instanceof Error ? e.message : String(e);
      setError(
        bundleSaved
          ? `新的 bundle 已保存，但更新其他字段失败。请重试以完成：${detail}`
          : detail
      );
    } finally {
      setIsSaving(false);
    }
  }

  return (
    <Modal open={open} onOpenChange={(o) => !o && onClose()}>
      <Modal.Content width="lg" height="lg">
        <Modal.Header
          title={existingApp ? `编辑 ${existingApp.name}` : "创建自定义应用"}
          description={
            isEdit
              ? "更新此自定义应用的配置，也可以上传新的 bundle 替换其文件。"
              : "定义自定义外部应用：上传技能 bundle，并配置出口代理如何认证外发请求。"
          }
        />
        <Modal.Body>
          <div className="flex flex-col gap-4">
            <div className="flex flex-col gap-1">
              <Text font="main-ui-action">名称</Text>
              <InputTypeIn
                value={name}
                onChange={(e) => setName(e.target.value)}
                placeholder="我的自定义应用"
              />
            </div>

            <div className="flex flex-col gap-1">
              <Text font="main-ui-action">描述</Text>
              <InputTypeIn
                value={description}
                onChange={(e) => setDescription(e.target.value)}
                placeholder="可选，默认使用 bundle 中 SKILL.md 的描述"
              />
            </div>

            <div className="flex flex-col gap-1">
              <Text font="main-ui-action">上游 URL patterns</Text>
              <Text font="secondary-body" color="text-03">
                {
                  "代理可以注入凭据的外发 URL。使用 * 匹配任意字符（例如 https://api.example.com/* 覆盖该主机上的所有路径）。主机必须是字面值，第一个斜杠前不能使用通配符。输入 pattern 后按 Enter。"
                }
              </Text>
              <ListFieldInput
                values={upstreamPatterns}
                onChange={setUpstreamPatterns}
                placeholder="https://api.example.com/*"
              />
            </div>

            <div className="flex flex-col gap-1">
              <Text font="main-ui-action">Header 凭据 pattern</Text>
              <Text font="secondary-body" color="text-03">
                {`可选，注入外发请求的 Header。使用 {placeholder} 表示用户（或下方组织）提供的值，例如 "Bearer {api_key}"。留空则只允许上游 pattern，不注入凭据。`}
              </Text>
              <InputKeyValue
                keyTitle="Header"
                valueTitle="Value"
                keyPlaceholder="Authorization"
                valuePlaceholder="Bearer {api_key}"
                items={headers}
                onChange={setHeaders}
                mode="line"
                addButtonLabel="添加 Header"
              />
            </div>

            <div className="flex flex-col gap-1">
              <Text font="main-ui-action">组织凭据</Text>
              <Text font="secondary-body" color="text-03">
                可选，你的组织为每位用户预填的值。若应用由每位用户自行提供凭据，请留空。
              </Text>
              <InputKeyValue
                keyTitle="凭据 Key"
                valueTitle="Value"
                keyPlaceholder="api_key"
                valuePlaceholder="sk-…"
                items={orgCredentials}
                onChange={setOrgCredentials}
                mode="line"
                addButtonLabel="添加凭据"
              />
            </div>

            <div className="flex flex-col gap-1">
              <Text font="main-ui-action">
                {isEdit ? "替换 bundle（.zip）" : "Bundle（.zip）"}
              </Text>
              <Text font="secondary-body" color="text-03">
                {isEdit
                  ? "可选，上传新的 zip 替换当前 bundle。留空则保留当前 bundle，slug 保持不变。"
                  : "包含 SKILL.md 及其他文件的 zip。文件名会成为应用 slug。"}
              </Text>
              <div className="flex items-center gap-2">
                <input
                  ref={fileInputRef}
                  type="file"
                  accept=".zip,application/zip"
                  onChange={handleFileChange}
                  className="hidden"
                />
                <Button
                  icon={SvgUploadCloud}
                  prominence="secondary"
                  onClick={() => fileInputRef.current?.click()}
                >
                  {file
                    ? "更换文件"
                    : isEdit
                      ? "选择新的 zip"
                      : "选择 zip"}
                </Button>
                <Text font="main-ui-body" color="text-03">
                  {file
                    ? file.name
                    : isEdit
                      ? "保留当前 bundle"
                      : "未选择文件"}
                </Text>
              </div>
            </div>

            {error && (
              <MessageCard
                variant="error"
                title="保存失败"
                description={error}
              />
            )}
          </div>
        </Modal.Body>
        <Modal.Footer>
          <div className="flex justify-end gap-2 w-full">
            <Button
              prominence="secondary"
              onClick={onClose}
              disabled={isSaving}
            >
              取消
            </Button>
            {disabledCreateReason ? (
              <Tooltip tooltip={disabledCreateReason}>
                <span className="inline-flex">{createButton}</span>
              </Tooltip>
            ) : (
              createButton
            )}
          </div>
        </Modal.Footer>
      </Modal.Content>
    </Modal>
  );
}
