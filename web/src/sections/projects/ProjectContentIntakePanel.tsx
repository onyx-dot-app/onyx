"use client";

import React, { useCallback, useEffect, useMemo, useState } from "react";
import { Button, Text } from "@opal/components";
import {
  SvgBookOpen,
  SvgCheckCircle,
  SvgClipboard,
  SvgClock,
  SvgFileText,
  SvgFiles,
  SvgSimpleLoader,
  SvgTag,
  SvgUploadSquare,
} from "@opal/icons";
import { cn } from "@opal/utils";
import Modal from "@/refresh-components/Modal";
import InputTextArea from "@/refresh-components/inputs/InputTextArea";
import { toast } from "@/hooks/useToast";
import { useUser } from "@/providers/UserProvider";

type IntakeType = "text" | "data" | "pdf" | "other";
type BusinessDomain =
  | "brand"
  | "product"
  | "marketing"
  | "sales"
  | "service"
  | "supply_chain"
  | "training"
  | "other";
type ContentKind =
  | "policy"
  | "faq"
  | "guide"
  | "raw_note"
  | "data_record"
  | "asset_reference";
type AuthorityLevel = "official" | "reference" | "raw" | "deprecated";
type IntakeStatus = "pending" | "published" | "returned";

interface PendingIntake {
  id: string;
  projectId: number;
  title: string;
  intakeType: IntakeType;
  businessDomain: BusinessDomain;
  body: string;
  tags: string[];
  sourceNote: string;
  owner: string;
  relatedPerson: string;
  fileName: string | null;
  fileType: string | null;
  fileSize: number | null;
  submittedBy: string;
  submittedAt: string;
  status: IntakeStatus;
  contentKind: ContentKind;
  authorityLevel: AuthorityLevel;
  reviewAt: string;
  aiAssisted?: boolean;
  aiMode?: "stub";
  aiGeneratedBy?: string;
  aiMissingFields?: string[];
  aiSensitiveRisks?: string[];
  aiQualityWarnings?: string[];
  publishedAt?: string;
}

interface AiAssistResponse {
  mode: "stub";
  llm_used: boolean;
  generated_by: string;
  suggested_title: string;
  business_domain: BusinessDomain;
  content_kind: ContentKind;
  authority_level: AuthorityLevel;
  suggested_tags: string[];
  source_note: string;
  missing_fields: string[];
  sensitive_risks: string[];
  quality_warnings: string[];
  warnings: string[];
  markdown_draft: string;
}

interface IntakeFormState {
  title: string;
  intakeType: IntakeType;
  businessDomain: BusinessDomain;
  body: string;
  tags: string;
  sourceNote: string;
  owner: string;
  relatedPerson: string;
  file: File | null;
}

interface ProjectContentIntakePanelProps {
  projectId: number;
  projectName: string;
  onPublishFile: (
    file: File,
    onSuccess: () => void,
    onFailure: () => void
  ) => void;
}

const INTAKE_STORAGE_VERSION = "v1";

const INTAKE_TYPES: Array<{
  value: IntakeType;
  label: string;
  description: string;
  recommendedFormat: string;
  publishGuidance: string;
  icon: typeof SvgFileText;
  accept?: string;
}> = [
  {
    value: "text",
    label: "文本",
    description: "SOP、FAQ、培训话术、会议纪要",
    recommendedFormat: "Markdown 正文 / .md",
    publishGuidance:
      "最适合直接整理成正式知识。建议包含标题、适用场景、正文、禁止表达和引用来源。",
    icon: SvgFileText,
  },
  {
    value: "data",
    label: "数据",
    description: "SKU 表、尺码表、价格表、运营数据",
    recommendedFormat: "CSV / XLSX，发布前转 Markdown 表格",
    publishGuidance:
      "必须补充数据口径、时间范围、字段说明和 owner；不建议把原始表格直接作为回答依据。",
    icon: SvgFiles,
    accept: ".csv,.tsv,.xlsx,.xls,.json",
  },
  {
    value: "pdf",
    label: "PDF",
    description: "品牌手册、供应商资料、活动方案",
    recommendedFormat: "PDF 原件 + Markdown 摘要",
    publishGuidance:
      "PDF 先作为原始素材进入待整理区，正式入库建议发布为摘要、页码依据和可引用口径。",
    icon: SvgBookOpen,
    accept: ".pdf",
  },
  {
    value: "other",
    label: "其他",
    description: "图片、链接、外部素材、暂未结构化资料",
    recommendedFormat: "链接 / 图片 / 附件说明，发布为素材引用",
    publishGuidance:
      "只记录来源、用途、权限和负责人；需要管理员转成可检索 Markdown 后再作为正式知识。",
    icon: SvgClipboard,
  },
];

const BUSINESS_DOMAINS: Array<{ value: BusinessDomain; label: string }> = [
  { value: "brand", label: "品牌" },
  { value: "product", label: "产品" },
  { value: "marketing", label: "市场" },
  { value: "sales", label: "销售" },
  { value: "service", label: "客服" },
  { value: "supply_chain", label: "供应链" },
  { value: "training", label: "培训" },
  { value: "other", label: "其他" },
];

const CONTENT_KINDS: Array<{ value: ContentKind; label: string }> = [
  { value: "policy", label: "政策口径" },
  { value: "faq", label: "问答 FAQ" },
  { value: "guide", label: "指南/说明" },
  { value: "raw_note", label: "原始记录" },
  { value: "data_record", label: "数据记录" },
  { value: "asset_reference", label: "素材引用" },
];

const AUTHORITY_LEVELS: Array<{ value: AuthorityLevel; label: string }> = [
  { value: "official", label: "正式标准" },
  { value: "reference", label: "参考资料" },
  { value: "raw", label: "原始记录" },
  { value: "deprecated", label: "已废弃" },
];

const FIELD_CLASS =
  "w-full rounded-08 border border-border-01 bg-background-neutral-00 px-3 py-2 text-sm text-text-05 outline-hidden placeholder:text-text-02 focus:border-border-05";

function getStorageKey(projectId: number) {
  return `novawear:project-content-intake:${INTAKE_STORAGE_VERSION}:${projectId}`;
}

function createEmptyForm(): IntakeFormState {
  return {
    title: "",
    intakeType: "text",
    businessDomain: "product",
    body: "",
    tags: "",
    sourceNote: "",
    owner: "",
    relatedPerson: "",
    file: null,
  };
}

function createId() {
  if (typeof crypto !== "undefined" && "randomUUID" in crypto) {
    return crypto.randomUUID();
  }
  return `${Date.now()}-${Math.random().toString(36).slice(2, 10)}`;
}

function defaultContentKind(intakeType: IntakeType): ContentKind {
  if (intakeType === "data") return "data_record";
  if (intakeType === "pdf" || intakeType === "other") return "asset_reference";
  return "guide";
}

function defaultAuthorityLevel(intakeType: IntakeType): AuthorityLevel {
  return intakeType === "text" ? "reference" : "raw";
}

function defaultReviewDate() {
  const date = new Date();
  date.setDate(date.getDate() + 90);
  return date.toISOString().slice(0, 10);
}

function parseTags(rawTags: string) {
  return Array.from(
    new Set(
      rawTags
        .split(/[，,]/)
        .map((tag) => tag.trim())
        .filter(Boolean)
    )
  ).slice(0, 12);
}

function formatBytes(bytes: number | null) {
  if (!bytes) return "";
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${Math.round(bytes / 1024)} KB`;
  return `${(bytes / 1024 / 1024).toFixed(1)} MB`;
}

function yamlString(value: string) {
  return JSON.stringify(value || "");
}

function yamlArray(values: string[]) {
  return `[${values.map(yamlString).join(", ")}]`;
}

function stripDraftMarkdownBody(markdown: string) {
  return markdown
    .replace(/^---[\s\S]*?---\s*/, "")
    .replace(/^# .+\n+/, "")
    .trim();
}

function domainLabel(value: BusinessDomain) {
  return BUSINESS_DOMAINS.find((domain) => domain.value === value)?.label ?? value;
}

function intakeTypeLabel(value: IntakeType) {
  return INTAKE_TYPES.find((type) => type.value === value)?.label ?? value;
}

function contentKindLabel(value: ContentKind) {
  return CONTENT_KINDS.find((kind) => kind.value === value)?.label ?? value;
}

function authorityLabel(value: AuthorityLevel) {
  return (
    AUTHORITY_LEVELS.find((authority) => authority.value === value)?.label ??
    value
  );
}

function buildMarkdown(item: PendingIntake, projectName: string) {
  const publishedAt = new Date().toISOString();
  const onyxMetadata = {
    title: item.title,
    schema_version: "novawear_kb_intake_v1",
    intake_id: item.id,
    kb_intake_type: item.intakeType,
    business_domain: item.businessDomain,
    content_kind: item.contentKind,
    authority_level: item.authorityLevel,
    publication_status: "published",
    review_status: "approved",
    lifecycle_status: "approved",
    owner: item.owner || item.submittedBy,
    review_at: item.reviewAt,
    source_note: item.sourceNote,
    custom_tags: item.tags,
    ai_assisted: Boolean(item.aiAssisted),
    locale: "zh-CN",
    audience: "novawear_internal",
    project_name: projectName,
  };
  const metadata = [
    "---",
    "schema_version: novawear_kb_intake_v1",
    `intake_id: ${yamlString(item.id)}`,
    `kb_intake_type: ${item.intakeType}`,
    `business_domain: ${item.businessDomain}`,
    `content_kind: ${item.contentKind}`,
    `authority_level: ${item.authorityLevel}`,
    "lifecycle_status: approved",
    `owner: ${yamlString(item.owner || item.submittedBy)}`,
    `review_at: ${yamlString(item.reviewAt)}`,
    `source_note: ${yamlString(item.sourceNote)}`,
    `custom_tags: ${yamlArray(item.tags)}`,
    `project_name: ${yamlString(projectName)}`,
    `submitted_by: ${yamlString(item.submittedBy)}`,
    `submitted_at: ${yamlString(item.submittedAt)}`,
    `published_at: ${yamlString(publishedAt)}`,
    `ai_assisted: ${item.aiAssisted ? "true" : "false"}`,
    item.aiMode ? `ai_mode: ${yamlString(item.aiMode)}` : null,
    item.aiGeneratedBy ? `ai_generated_by: ${yamlString(item.aiGeneratedBy)}` : null,
    item.aiMissingFields?.length
      ? `ai_missing_fields: ${yamlArray(item.aiMissingFields)}`
      : null,
    item.aiSensitiveRisks?.length
      ? `ai_sensitive_risks: ${yamlArray(item.aiSensitiveRisks)}`
      : null,
    item.aiQualityWarnings?.length
      ? `ai_quality_warnings: ${yamlArray(item.aiQualityWarnings)}`
      : null,
    item.fileName ? `original_file_name: ${yamlString(item.fileName)}` : null,
    item.fileType ? `original_file_type: ${yamlString(item.fileType)}` : null,
    item.fileSize ? `original_file_size_bytes: ${item.fileSize}` : null,
    "---",
  ]
    .filter(Boolean)
    .join("\n");

  const sourceSection = [
    "## 来源与治理",
    `- 内容入口：${intakeTypeLabel(item.intakeType)}`,
    `- 业务分类：${domainLabel(item.businessDomain)}`,
    `- 内容类型：${contentKindLabel(item.contentKind)}`,
    `- 权威等级：${authorityLabel(item.authorityLevel)}`,
    `- 负责人：${item.owner || item.submittedBy}`,
    `- 复核日期：${item.reviewAt}`,
    item.relatedPerson ? `- 相关人：${item.relatedPerson}` : null,
    item.sourceNote ? `- 来源说明：${item.sourceNote}` : null,
    item.fileName
      ? `- 原始文件：${item.fileName}${item.fileSize ? `（${formatBytes(item.fileSize)}）` : ""}`
      : null,
    item.tags.length > 0 ? `- 标签：${item.tags.join("、")}` : null,
    item.aiAssisted ? `- AI 整理：${item.aiGeneratedBy || "deterministic_stub"}` : null,
    item.aiMissingFields?.length
      ? `- AI 提示缺失信息：${item.aiMissingFields.join("、")}`
      : null,
    item.aiSensitiveRisks?.length
      ? `- AI 提示敏感风险：${item.aiSensitiveRisks.join("、")}`
      : null,
    item.aiQualityWarnings?.length
      ? `- AI 质量提示：${item.aiQualityWarnings.join("；")}`
      : null,
  ]
    .filter(Boolean)
    .join("\n");

  const body =
    item.body.trim() ||
    "本文由内容录入入口生成。原始素材需要内容管理员补充结构化正文后再作为正式回答依据。";

  return `<!-- ONYX_METADATA=${JSON.stringify(onyxMetadata)} -->\n${metadata}\n\n# ${item.title}\n\n${sourceSection}\n\n## 正文\n\n${body}\n`;
}

function buildFileName(item: PendingIntake) {
  const timestamp = new Date().toISOString().replace(/[-:T]/g, "").slice(0, 12);
  return `novawear-intake-${item.intakeType}-${timestamp}-${item.id.slice(0, 8)}.md`;
}

function loadItems(projectId: number): PendingIntake[] {
  if (typeof window === "undefined") return [];
  const raw = window.localStorage.getItem(getStorageKey(projectId));
  if (!raw) return [];

  try {
    const parsed = JSON.parse(raw);
    if (!Array.isArray(parsed)) return [];
    return parsed.filter((item) => item && item.projectId === projectId);
  } catch {
    return [];
  }
}

function SelectField<T extends string>({
  label,
  value,
  options,
  onChange,
  disabled,
}: {
  label: string;
  value: T;
  options: Array<{ value: T; label: string }>;
  onChange: (value: T) => void;
  disabled?: boolean;
}) {
  return (
    <label className="flex flex-col gap-1">
      <span className="text-xs font-medium text-text-03">{label}</span>
      <select
        value={value}
        disabled={disabled}
        onChange={(event) => onChange(event.target.value as T)}
        className={cn(FIELD_CLASS, disabled && "opacity-60")}
      >
        {options.map((option) => (
          <option key={option.value} value={option.value}>
            {option.label}
          </option>
        ))}
      </select>
    </label>
  );
}

function TextField({
  label,
  value,
  onChange,
  placeholder,
  type = "text",
  disabled,
}: {
  label: string;
  value: string;
  onChange: (value: string) => void;
  placeholder?: string;
  type?: string;
  disabled?: boolean;
}) {
  return (
    <label className="flex flex-col gap-1">
      <span className="text-xs font-medium text-text-03">{label}</span>
      <input
        type={type}
        value={value}
        disabled={disabled}
        onChange={(event) => onChange(event.target.value)}
        placeholder={placeholder}
        className={cn(FIELD_CLASS, disabled && "opacity-60")}
      />
    </label>
  );
}

export default function ProjectContentIntakePanel({
  projectId,
  projectName,
  onPublishFile,
}: ProjectContentIntakePanelProps) {
  const { user, isAdmin } = useUser();
  const [open, setOpen] = useState(false);
  const [activeTab, setActiveTab] = useState<"submit" | "queue">("submit");
  const [form, setForm] = useState<IntakeFormState>(() => createEmptyForm());
  const [items, setItems] = useState<PendingIntake[]>([]);
  const [publishingId, setPublishingId] = useState<string | null>(null);
  const [aiSuggestion, setAiSuggestion] = useState<AiAssistResponse | null>(
    null
  );
  const [aiSuggestionApplied, setAiSuggestionApplied] = useState(false);
  const [isAiAssisting, setIsAiAssisting] = useState(false);
  const [aiAssistError, setAiAssistError] = useState<string | null>(null);

  useEffect(() => {
    setItems(loadItems(projectId));
  }, [projectId]);

  const updateItems = useCallback(
    (updater: (currentItems: PendingIntake[]) => PendingIntake[]) => {
      setItems((currentItems) => {
        const nextItems = updater(currentItems);
        if (typeof window !== "undefined") {
          window.localStorage.setItem(
            getStorageKey(projectId),
            JSON.stringify(nextItems)
          );
        }
        return nextItems;
      });
    },
    [projectId]
  );

  const pendingItems = useMemo(
    () => items.filter((item) => item.status === "pending"),
    [items]
  );
  const publishedCount = useMemo(
    () => items.filter((item) => item.status === "published").length,
    [items]
  );

  const selectedType = useMemo(
    () => INTAKE_TYPES.find((type) => type.value === form.intakeType),
    [form.intakeType]
  );

  const updateForm = useCallback(
    <K extends keyof IntakeFormState>(key: K, value: IntakeFormState[K]) => {
      setForm((prev) => ({ ...prev, [key]: value }));
    },
    []
  );

  const updateItem = useCallback(
    <K extends keyof PendingIntake>(
      itemId: string,
      key: K,
      value: PendingIntake[K]
    ) => {
      updateItems((currentItems) =>
        currentItems.map((item) =>
          item.id === itemId ? { ...item, [key]: value } : item
        )
      );
    },
    [updateItems]
  );

  const submitDisabled =
    !form.title.trim() ||
    (!form.body.trim() && !form.file) ||
    (form.intakeType === "text" && !form.body.trim());

  const canRunAiAssist =
    Boolean(form.title.trim()) || Boolean(form.body.trim()) || Boolean(form.file);

  const clearAiSuggestion = useCallback(() => {
    setAiSuggestion(null);
    setAiSuggestionApplied(false);
    setAiAssistError(null);
  }, []);

  const handleAiAssist = useCallback(async () => {
    if (!canRunAiAssist) {
      toast.warning("请先输入标题、正文或上传文件说明。");
      return;
    }

    setIsAiAssisting(true);
    setAiAssistError(null);

    try {
      const response = await fetch("/api/brand-kb/intake/assist", {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
        },
        body: JSON.stringify({
          project_id: projectId,
          intake_type: form.intakeType,
          business_domain: form.businessDomain,
          title: form.title,
          raw_body: form.body,
          source_note: form.sourceNote,
          file_name: form.file?.name ?? null,
          file_mime_type: form.file?.type || null,
        }),
      });

      if (!response.ok) {
        throw new Error(`AI 整理接口返回 ${response.status}`);
      }

      const suggestion = (await response.json()) as AiAssistResponse;
      setAiSuggestion(suggestion);
      setAiSuggestionApplied(false);
      toast.success("已生成整理草稿，可预览后应用。");
    } catch (error) {
      setAiAssistError(
        error instanceof Error ? error.message : "AI 整理失败，请手动提交。"
      );
      toast.error("AI 整理失败，仍可继续手动提交。");
    } finally {
      setIsAiAssisting(false);
    }
  }, [canRunAiAssist, form, projectId]);

  const handleApplyAiSuggestion = useCallback(() => {
    if (!aiSuggestion) return;

    setForm((prev) => ({
      ...prev,
      title: aiSuggestion.suggested_title || prev.title,
      businessDomain: aiSuggestion.business_domain,
      body: stripDraftMarkdownBody(aiSuggestion.markdown_draft) || prev.body,
      tags: aiSuggestion.suggested_tags.join("，"),
      sourceNote: aiSuggestion.source_note || prev.sourceNote,
    }));
    setAiSuggestionApplied(true);
    toast.success("已应用 AI 建议，提交前仍可继续编辑。");
  }, [aiSuggestion]);

  const handleSubmit = useCallback(() => {
    if (submitDisabled) {
      toast.warning("请补齐标题和正文或文件后再提交。");
      return;
    }

    const nextItem: PendingIntake = {
      id: createId(),
      projectId,
      title: form.title.trim(),
      intakeType: form.intakeType,
      businessDomain: form.businessDomain,
      body: form.body.trim(),
      tags: parseTags(form.tags),
      sourceNote: form.sourceNote.trim(),
      owner: form.owner.trim(),
      relatedPerson: form.relatedPerson.trim(),
      fileName: form.file?.name ?? null,
      fileType: form.file?.type || null,
      fileSize: form.file?.size ?? null,
      submittedBy: user?.email || "unknown",
      submittedAt: new Date().toISOString(),
      status: "pending",
      contentKind:
        aiSuggestionApplied && aiSuggestion
          ? aiSuggestion.content_kind
          : defaultContentKind(form.intakeType),
      authorityLevel:
        aiSuggestionApplied && aiSuggestion
          ? aiSuggestion.authority_level
          : defaultAuthorityLevel(form.intakeType),
      reviewAt: defaultReviewDate(),
      aiAssisted: aiSuggestionApplied,
      aiMode: aiSuggestionApplied ? aiSuggestion?.mode : undefined,
      aiGeneratedBy: aiSuggestionApplied
        ? aiSuggestion?.generated_by
        : undefined,
      aiMissingFields:
        aiSuggestionApplied && aiSuggestion ? aiSuggestion.missing_fields : [],
      aiSensitiveRisks:
        aiSuggestionApplied && aiSuggestion ? aiSuggestion.sensitive_risks : [],
      aiQualityWarnings:
        aiSuggestionApplied && aiSuggestion ? aiSuggestion.quality_warnings : [],
    };

    updateItems((currentItems) => [nextItem, ...currentItems]);
    setForm(createEmptyForm());
    clearAiSuggestion();
    setActiveTab("queue");
    toast.success("已进入待整理内容，不会进入正式知识库检索。");
  }, [
    aiSuggestion,
    aiSuggestionApplied,
    clearAiSuggestion,
    form,
    projectId,
    submitDisabled,
    updateItems,
    user?.email,
  ]);

  const markPublished = useCallback(
    (itemId: string) => {
      updateItems((currentItems) =>
        currentItems.map((item) =>
          item.id === itemId
            ? {
                ...item,
                status: "published",
                publishedAt: new Date().toISOString(),
              }
            : item
        )
      );
      setPublishingId(null);
      toast.success("已发布为正式知识库 Markdown，正在进入项目索引。");
    },
    [updateItems]
  );

  const handlePublish = useCallback(
    (item: PendingIntake) => {
      if (!isAdmin) {
        toast.error("只有管理员可以发布正式知识。");
        return;
      }
      if (item.intakeType === "data" && !item.sourceNote.trim()) {
        toast.warning("数据类发布前请补充数据口径、时间范围或字段说明。");
        return;
      }
      if (!item.body.trim()) {
        toast.warning("发布前请补充可检索的 Markdown 正文或摘要。");
        return;
      }
      if (
        item.authorityLevel === "official" &&
        (item.aiSensitiveRisks?.length ?? 0) > 0
      ) {
        toast.warning("存在敏感风险提示时，不能直接发布为正式标准。");
        return;
      }

      const markdown = buildMarkdown(item, projectName);
      const file = new File([markdown], buildFileName(item), {
        type: "text/markdown",
      });

      setPublishingId(item.id);
      onPublishFile(
        file,
        () => markPublished(item.id),
        () => {
          setPublishingId(null);
          toast.error("发布失败，内容仍保留在待整理区。");
        }
      );
    },
    [isAdmin, markPublished, onPublishFile, projectName]
  );

  const handleReturn = useCallback(
    (itemId: string) => {
      updateItems((currentItems) =>
        currentItems.map((item) =>
          item.id === itemId ? { ...item, status: "returned" } : item
        )
      );
      toast.info("已退回该条内容。");
    },
    [updateItems]
  );

  return (
    <>
      <div
        className="rounded-12 border border-border-01 bg-background-neutral-00 p-3"
        data-testid="project-content-intake-panel"
      >
        <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
          <div className="min-w-0">
            <Text as="p" font="main-ui-body" color="text-05">
              内容录入
            </Text>
            <Text as="p" font="secondary-body" color="text-03">
              快速提交文本、数据、PDF 或其他素材；审核发布后才进入 Agent
              检索。
            </Text>
          </div>
          <div className="flex shrink-0 flex-wrap items-center gap-2">
            {isAdmin && pendingItems.length > 0 && (
              <Button
                icon={SvgClock}
                prominence="tertiary"
                onClick={() => {
                  setActiveTab("queue");
                  setOpen(true);
                }}
              >
                {`待整理 ${pendingItems.length}`}
              </Button>
            )}
            <Button
              icon={SvgUploadSquare}
              prominence="secondary"
              onClick={() => {
                setActiveTab("submit");
                setOpen(true);
              }}
            >
              录入内容
            </Button>
          </div>
        </div>
      </div>

      <Modal open={open} onOpenChange={setOpen}>
        <Modal.Content width="lg" height="lg" preventAccidentalClose={false}>
          <Modal.Header
            icon={SvgUploadSquare}
            title="内容录入"
            description="提交内容先进入待整理区，发布后才进入正式知识库。"
            onClose={() => setOpen(false)}
          />

          <Modal.Body>
            <div className="flex w-full flex-col gap-4">
              <div className="flex w-full flex-wrap gap-2">
                <button
                  type="button"
                  onClick={() => setActiveTab("submit")}
                  className={cn(
                    "rounded-08 border px-3 py-2 text-sm font-medium",
                    activeTab === "submit"
                      ? "border-border-05 bg-background-neutral-00 text-text-05"
                      : "border-border-01 text-text-03 hover:bg-background-tint-02"
                  )}
                >
                  提交内容
                </button>
                <button
                  type="button"
                  onClick={() => setActiveTab("queue")}
                  className={cn(
                    "rounded-08 border px-3 py-2 text-sm font-medium",
                    activeTab === "queue"
                      ? "border-border-05 bg-background-neutral-00 text-text-05"
                      : "border-border-01 text-text-03 hover:bg-background-tint-02"
                  )}
                >
                  待整理内容 {pendingItems.length}
                </button>
              </div>

              {activeTab === "submit" ? (
                <div className="grid w-full gap-4 lg:grid-cols-[minmax(0,0.8fr)_minmax(0,1.2fr)]">
                  <div className="grid gap-2 sm:grid-cols-2 lg:grid-cols-1">
                    {INTAKE_TYPES.map((type) => {
                      const Icon = type.icon;
                      const selected = form.intakeType === type.value;
                      return (
                        <button
                          key={type.value}
                          type="button"
                          onClick={() => {
                            setForm((prev) => ({
                              ...prev,
                              intakeType: type.value,
                              file: null,
                            }));
                            clearAiSuggestion();
                          }}
                          className={cn(
                            "flex min-h-20 items-start gap-3 rounded-08 border p-3 text-left",
                            selected
                              ? "border-border-05 bg-background-neutral-00"
                              : "border-border-01 bg-background-tint-00 hover:bg-background-tint-02"
                          )}
                        >
                          <Icon className="mt-0.5 h-4 w-4 shrink-0 stroke-text-03" />
                          <span className="min-w-0">
                            <span className="block text-sm font-semibold text-text-05">
                              {type.label}
                            </span>
                            <span className="block text-xs leading-5 text-text-03">
                              {type.description}
                            </span>
                            <span className="mt-2 block rounded-06 border border-border-01 bg-background-tint-02 px-2 py-1 text-xs leading-5 text-text-04">
                              {`推荐格式：${type.recommendedFormat}`}
                            </span>
                          </span>
                        </button>
                      );
                    })}
                  </div>

                  <div className="flex min-w-0 flex-col gap-3 rounded-12 border border-border-01 bg-background-neutral-00 p-4">
                    {selectedType && (
                      <div className="rounded-08 border border-border-01 bg-background-tint-01 p-3">
                        <Text as="p" font="secondary-body" color="text-04">
                          {`推荐格式：${selectedType.recommendedFormat}`}
                        </Text>
                        <Text as="p" font="secondary-body" color="text-03">
                          {selectedType.publishGuidance}
                        </Text>
                      </div>
                    )}

                    <div className="rounded-08 border border-border-01 bg-background-tint-00 p-3">
                      <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
                        <div className="min-w-0">
                          <Text as="p" font="main-ui-body" color="text-05">
                            AI 整理草稿
                          </Text>
                          <Text as="p" font="secondary-body" color="text-03">
                            后端受控 stub 会生成标准 Markdown、缺失信息和敏感风险提示；不会自动提交或发布。
                          </Text>
                        </div>
                        <Button
                          icon={isAiAssisting ? SvgSimpleLoader : SvgClipboard}
                          prominence="secondary"
                          disabled={!canRunAiAssist || isAiAssisting}
                          onClick={handleAiAssist}
                        >
                          {isAiAssisting ? "整理中" : "AI 整理"}
                        </Button>
                      </div>

                      {aiAssistError && (
                        <Text as="p" font="secondary-body" color="text-03">
                          {`整理失败：${aiAssistError}。可以继续手动提交。`}
                        </Text>
                      )}

                      {aiSuggestion && (
                        <div className="mt-3 flex flex-col gap-3 rounded-08 border border-border-01 bg-background-neutral-00 p-3">
                          <div className="flex flex-wrap items-center gap-2">
                            <span className="rounded-06 bg-background-tint-02 px-2 py-1 text-xs font-medium text-text-03">
                              {aiSuggestion.mode}
                            </span>
                            <span className="rounded-06 bg-background-tint-02 px-2 py-1 text-xs font-medium text-text-03">
                              {aiSuggestion.generated_by}
                            </span>
                            <span className="rounded-06 bg-background-tint-02 px-2 py-1 text-xs font-medium text-text-03">
                              {authorityLabel(aiSuggestion.authority_level)}
                            </span>
                          </div>
                          <div>
                            <Text as="p" font="main-ui-body" color="text-05">
                              {aiSuggestion.suggested_title}
                            </Text>
                            <Text as="p" font="secondary-body" color="text-03">
                              {`建议分类：${domainLabel(
                                aiSuggestion.business_domain
                              )} / ${contentKindLabel(
                                aiSuggestion.content_kind
                              )}`}
                            </Text>
                          </div>
                          {aiSuggestion.suggested_tags.length > 0 && (
                            <Text as="p" font="secondary-body" color="text-03">
                              {`建议标签：${aiSuggestion.suggested_tags.join(
                                "、"
                              )}`}
                            </Text>
                          )}
                          {(aiSuggestion.missing_fields.length > 0 ||
                            aiSuggestion.sensitive_risks.length > 0 ||
                            aiSuggestion.quality_warnings.length > 0) && (
                            <div className="grid gap-2 text-xs leading-5 text-text-03 sm:grid-cols-3">
                              <div className="rounded-06 border border-border-01 p-2">
                                <span className="block font-medium text-text-04">
                                  缺失信息
                                </span>
                                {aiSuggestion.missing_fields.length > 0
                                  ? aiSuggestion.missing_fields.join("、")
                                  : "暂无明显缺失"}
                              </div>
                              <div className="rounded-06 border border-border-01 p-2">
                                <span className="block font-medium text-text-04">
                                  敏感风险
                                </span>
                                {aiSuggestion.sensitive_risks.length > 0
                                  ? aiSuggestion.sensitive_risks.join("、")
                                  : "暂无自动识别风险"}
                              </div>
                              <div className="rounded-06 border border-border-01 p-2">
                                <span className="block font-medium text-text-04">
                                  质量提示
                                </span>
                                {aiSuggestion.quality_warnings.join("；")}
                              </div>
                            </div>
                          )}
                          <div>
                            <Text as="p" font="secondary-body" color="text-04">
                              查看整理草稿
                            </Text>
                            <pre className="mt-1 max-h-44 overflow-auto whitespace-pre-wrap rounded-06 border border-border-01 bg-background-tint-02 p-3 text-xs leading-5 text-text-04">
                              {aiSuggestion.markdown_draft}
                            </pre>
                          </div>
                          <div className="flex flex-wrap gap-2">
                            <Button
                              icon={SvgCheckCircle}
                              prominence="secondary"
                              onClick={handleApplyAiSuggestion}
                            >
                              应用 AI 建议
                            </Button>
                            <Button
                              prominence="tertiary"
                              onClick={clearAiSuggestion}
                            >
                              继续手动提交
                            </Button>
                          </div>
                          {aiSuggestionApplied && (
                            <Text as="p" font="secondary-body" color="text-03">
                              已应用建议，提交前仍可编辑正文、标签和来源说明。
                            </Text>
                          )}
                        </div>
                      )}
                    </div>

                    <div className="grid gap-3 sm:grid-cols-2">
                      <TextField
                        label="标题"
                        value={form.title}
                        onChange={(value) => updateForm("title", value)}
                        placeholder="例如 FW2026 门店培训补充话术"
                      />
                      <SelectField
                        label="业务分类"
                        value={form.businessDomain}
                        options={BUSINESS_DOMAINS}
                        onChange={(value) =>
                          updateForm("businessDomain", value)
                        }
                      />
                    </div>

                    {form.intakeType !== "text" && (
                      <label className="flex flex-col gap-1">
                        <span className="text-xs font-medium text-text-03">
                          文件
                        </span>
                        <input
                          type="file"
                          accept={selectedType?.accept}
                          onChange={(event) =>
                            updateForm("file", event.target.files?.[0] ?? null)
                          }
                          className="w-full rounded-08 border border-border-01 bg-background-neutral-00 p-2 text-sm text-text-03 file:mr-3 file:rounded-06 file:border-0 file:bg-background-tint-02 file:px-3 file:py-1 file:text-text-05"
                        />
                      </label>
                    )}

                    <label className="flex flex-col gap-1">
                      <span className="text-xs font-medium text-text-03">
                        正文或说明
                      </span>
                      <InputTextArea
                        value={form.body}
                        onChange={(event) =>
                          updateForm("body", event.target.value)
                        }
                        rows={form.intakeType === "text" ? 8 : 4}
                        placeholder={
                          form.intakeType === "text"
                            ? "粘贴 SOP、FAQ、会议结论或培训话术。"
                            : "补充文件背景、适用范围或需要管理员整理的重点。"
                        }
                      />
                    </label>

                    <div className="grid gap-3 sm:grid-cols-2">
                      <TextField
                        label="标签"
                        value={form.tags}
                        onChange={(value) => updateForm("tags", value)}
                        placeholder="逗号分隔，最多 12 个"
                      />
                      <TextField
                        label="相关负责人"
                        value={form.owner}
                        onChange={(value) => updateForm("owner", value)}
                        placeholder="默认使用提交人"
                      />
                    </div>

                    <div className="grid gap-3 sm:grid-cols-2">
                      <TextField
                        label="来源说明"
                        value={form.sourceNote}
                        onChange={(value) => updateForm("sourceNote", value)}
                        placeholder="会议、系统、渠道或文档来源"
                      />
                      <TextField
                        label="相关人"
                        value={form.relatedPerson}
                        onChange={(value) => updateForm("relatedPerson", value)}
                        placeholder="可选"
                      />
                    </div>
                  </div>
                </div>
              ) : (
                <div className="flex w-full flex-col gap-3">
                  {pendingItems.length === 0 ? (
                    <div className="rounded-12 border border-dashed border-border-01 p-6 text-center">
                      <Text as="p" font="main-ui-body" color="text-04">
                        暂无待整理内容
                      </Text>
                      <Text as="p" font="secondary-body" color="text-03">
                        新提交的内容会先停留在这里，不会进入正式检索。
                      </Text>
                    </div>
                  ) : (
                    pendingItems.map((item) => (
                      <div
                        key={item.id}
                        className="rounded-12 border border-border-01 bg-background-neutral-00 p-4"
                        data-testid="pending-intake-item"
                      >
                        <div className="flex flex-col gap-3 lg:flex-row lg:items-start lg:justify-between">
                          <div className="min-w-0">
                            <div className="flex flex-wrap items-center gap-2">
                              <span className="rounded-06 bg-background-tint-02 px-2 py-1 text-xs font-medium text-text-03">
                                {intakeTypeLabel(item.intakeType)}
                              </span>
                              <span className="rounded-06 bg-background-tint-02 px-2 py-1 text-xs font-medium text-text-03">
                                {domainLabel(item.businessDomain)}
                              </span>
                              <span className="rounded-06 bg-background-tint-02 px-2 py-1 text-xs font-medium text-text-03">
                                pending
                              </span>
                              {item.aiAssisted && (
                                <span className="rounded-06 bg-background-tint-02 px-2 py-1 text-xs font-medium text-text-03">
                                  AI assisted
                                </span>
                              )}
                              {(item.aiSensitiveRisks?.length ?? 0) > 0 && (
                                <span className="rounded-06 bg-background-tint-02 px-2 py-1 text-xs font-medium text-text-03">
                                  {`敏感风险 ${item.aiSensitiveRisks?.length}`}
                                </span>
                              )}
                            </div>
                            <Text as="p" font="main-ui-body" color="text-05">
                              {item.title}
                            </Text>
                            <Text as="p" font="secondary-body" color="text-03">
                              {`${item.submittedBy} · ${new Date(
                                item.submittedAt
                              ).toLocaleString()}`}
                            </Text>
                            {item.fileName && (
                              <Text as="p" font="secondary-body" color="text-03">
                                {`${item.fileName} ${formatBytes(
                                  item.fileSize
                                )}`}
                              </Text>
                            )}
                          </div>
                          <div className="flex shrink-0 flex-wrap gap-2">
                            <Button
                              icon={SvgCheckCircle}
                              prominence="secondary"
                              disabled={!isAdmin || publishingId === item.id}
                              onClick={() => handlePublish(item)}
                            >
                              {publishingId === item.id
                                ? "发布中"
                                : "发布到知识库"}
                            </Button>
                            <Button
                              icon={
                                publishingId === item.id
                                  ? SvgSimpleLoader
                                  : SvgTag
                              }
                              prominence="tertiary"
                              disabled={!isAdmin || publishingId === item.id}
                              onClick={() => handleReturn(item.id)}
                            >
                              退回
                            </Button>
                          </div>
                        </div>

                        <div className="mt-4 grid gap-3 lg:grid-cols-4">
                          <SelectField
                            label="内容类型"
                            value={item.contentKind}
                            options={CONTENT_KINDS}
                            disabled={!isAdmin}
                            onChange={(value) =>
                              updateItem(item.id, "contentKind", value)
                            }
                          />
                          <SelectField
                            label="权威等级"
                            value={item.authorityLevel}
                            options={AUTHORITY_LEVELS}
                            disabled={!isAdmin}
                            onChange={(value) =>
                              updateItem(item.id, "authorityLevel", value)
                            }
                          />
                          <TextField
                            label="负责人"
                            value={item.owner}
                            disabled={!isAdmin}
                            onChange={(value) =>
                              updateItem(item.id, "owner", value)
                            }
                            placeholder={item.submittedBy}
                          />
                          <TextField
                            label="复核日期"
                            type="date"
                            value={item.reviewAt}
                            disabled={!isAdmin}
                            onChange={(value) =>
                              updateItem(item.id, "reviewAt", value)
                            }
                          />
                        </div>

                        <div className="mt-3">
                          <label className="flex flex-col gap-1">
                            <span className="text-xs font-medium text-text-03">
                              来源说明 / 数据口径
                            </span>
                            <InputTextArea
                              value={item.sourceNote}
                              rows={2}
                              onChange={(event) =>
                                updateItem(
                                  item.id,
                                  "sourceNote",
                                  event.target.value
                                )
                              }
                              readOnly={!isAdmin}
                              placeholder="数据类发布前需要补充口径、时间范围或字段说明。"
                            />
                          </label>
                        </div>

                        {item.body && (
                          <div className="mt-3 rounded-08 border border-border-01 bg-background-tint-00 p-3">
                            <Text as="p" font="secondary-body" color="text-04">
                              {item.body}
                            </Text>
                          </div>
                        )}

                        {item.aiAssisted &&
                          ((item.aiMissingFields?.length ?? 0) > 0 ||
                            (item.aiQualityWarnings?.length ?? 0) > 0 ||
                            (item.aiSensitiveRisks?.length ?? 0) > 0) && (
                            <div className="mt-3 rounded-08 border border-border-01 bg-background-tint-00 p-3 text-xs leading-5 text-text-03">
                              {item.aiMissingFields?.length ? (
                                <div>{`缺失信息：${item.aiMissingFields.join(
                                  "、"
                                )}`}</div>
                              ) : null}
                              {item.aiSensitiveRisks?.length ? (
                                <div>{`敏感风险：${item.aiSensitiveRisks.join(
                                  "、"
                                )}`}</div>
                              ) : null}
                              {item.aiQualityWarnings?.length ? (
                                <div>{`质量提示：${item.aiQualityWarnings.join(
                                  "；"
                                )}`}</div>
                              ) : null}
                            </div>
                          )}
                      </div>
                    ))
                  )}
                </div>
              )}
            </div>
          </Modal.Body>

          {activeTab === "submit" && (
            <Modal.Footer>
              <Button prominence="secondary" onClick={() => setOpen(false)}>
                取消
              </Button>
              <Button
                prominence="secondary"
                disabled={submitDisabled}
                onClick={handleSubmit}
              >
                提交到待整理
              </Button>
            </Modal.Footer>
          )}
        </Modal.Content>
      </Modal>

      {publishedCount > 0 && (
        <div className="sr-only" aria-live="polite">
          已发布 {publishedCount} 条内容到正式知识库。
        </div>
      )}
    </>
  );
}
