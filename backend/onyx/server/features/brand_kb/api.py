import re
from typing import Any
from typing import Literal

from fastapi import APIRouter
from fastapi import Depends
from pydantic import BaseModel
from pydantic import Field

from onyx.auth.permissions import require_permission
from onyx.configs.constants import PUBLIC_API_TAGS
from onyx.db.enums import Permission


IntakeType = Literal["text", "data", "pdf", "other"]
BusinessDomain = Literal[
    "brand",
    "product",
    "marketing",
    "sales",
    "service",
    "supply_chain",
    "training",
    "other",
]
ContentKind = Literal[
    "policy",
    "faq",
    "guide",
    "raw_note",
    "data_record",
    "asset_reference",
]
AuthorityLevel = Literal["official", "reference", "raw", "deprecated"]


router = APIRouter(prefix="/brand-kb")
_basic_access = require_permission(Permission.BASIC_ACCESS)


class BrandKbIntakeAssistRequest(BaseModel):
    project_id: int
    intake_type: IntakeType
    business_domain: BusinessDomain
    title: str = Field(default="", max_length=300)
    raw_body: str = Field(default="", max_length=12000)
    source_note: str = Field(default="", max_length=1000)
    file_name: str | None = Field(default=None, max_length=500)
    file_mime_type: str | None = Field(default=None, max_length=200)


class BrandKbIntakeAssistResponse(BaseModel):
    mode: Literal["stub"]
    llm_used: bool
    generated_by: str
    suggested_title: str
    business_domain: BusinessDomain
    content_kind: ContentKind
    authority_level: AuthorityLevel
    suggested_tags: list[str]
    source_note: str
    missing_fields: list[str]
    sensitive_risks: list[str]
    quality_warnings: list[str]
    warnings: list[str]
    markdown_draft: str


PHONE_RE = re.compile(r"(?<!\d)1[3-9]\d{9}(?!\d)")
EMAIL_RE = re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b")
ORDER_RE = re.compile(r"(?:订单号|订单编号|order id|order_id)[:：\s-]*[A-Za-z0-9-]{6,}", re.I)
SECRET_RE = re.compile(
    r"(?:api[_-]?key|token|password|secret|sk-[A-Za-z0-9_-]{12,})",
    re.I,
)

SENSITIVE_KEYWORDS: list[tuple[str, str]] = [
    ("真实供应商名称", "真实供应商名称"),
    ("供应商名称", "供应商名称"),
    ("采购成本", "采购成本"),
    ("合同条款", "合同条款"),
    ("会员手机号", "会员手机号"),
    ("身份证", "身份证信息"),
    ("库存锁定", "库存承诺"),
    ("提前锁定", "库存承诺"),
    ("内部折扣", "内部未公开折扣"),
]

DOMAIN_TAGS: dict[BusinessDomain, list[str]] = {
    "brand": ["品牌", "品牌口径"],
    "product": ["产品", "商品资料"],
    "marketing": ["市场", "活动"],
    "sales": ["销售", "渠道"],
    "service": ["客服", "售后"],
    "supply_chain": ["供应链", "质检"],
    "training": ["培训", "SOP"],
    "other": ["待分类"],
}


def _infer_content_kind(request: BrandKbIntakeAssistRequest) -> ContentKind:
    body = f"{request.title}\n{request.raw_body}".lower()
    if request.intake_type == "data":
        return "data_record"
    if request.intake_type in {"pdf", "other"}:
        return "asset_reference"
    if any(keyword in body for keyword in ["faq", "问：", "答：", "怎么", "如何"]):
        return "faq"
    if any(keyword in body for keyword in ["政策", "口径", "必须", "禁止", "不得"]):
        return "policy"
    if any(keyword in body for keyword in ["会议", "纪要", "讨论", "待确认"]):
        return "raw_note"
    return "guide"


def _detect_sensitive_risks(text: str) -> list[str]:
    risks: list[str] = []
    if PHONE_RE.search(text):
        risks.append("手机号")
    if EMAIL_RE.search(text):
        risks.append("邮箱")
    if ORDER_RE.search(text):
        risks.append("订单号")
    if SECRET_RE.search(text):
        risks.append("API key / token / password")
    for keyword, label in SENSITIVE_KEYWORDS:
        if keyword.lower() in text.lower() and label not in risks:
            risks.append(label)
    return risks


def _mask_sensitive_text(text: str) -> str:
    masked = PHONE_RE.sub("[手机号需脱敏]", text)
    masked = EMAIL_RE.sub("[邮箱需脱敏]", masked)
    masked = ORDER_RE.sub("[订单号需脱敏]", masked)
    masked = SECRET_RE.sub("[密钥或口令需移除]", masked)
    return masked


def _derive_title(request: BrandKbIntakeAssistRequest) -> str:
    title = request.title.strip()
    if title:
        return title[:80]
    if request.file_name:
        base_name = request.file_name.rsplit("/", 1)[-1].rsplit(".", 1)[0]
        return base_name[:80] or "待整理知识"
    first_line = next(
        (line.strip() for line in request.raw_body.splitlines() if line.strip()),
        "",
    )
    return (first_line[:80] if first_line else "待整理知识")


def _derive_tags(
    request: BrandKbIntakeAssistRequest, content_kind: ContentKind
) -> list[str]:
    text = f"{request.title}\n{request.raw_body}\n{request.source_note}"
    tags = [*DOMAIN_TAGS[request.business_domain]]
    if content_kind == "faq":
        tags.append("FAQ")
    if content_kind == "policy":
        tags.append("标准口径")
    if request.intake_type == "data":
        tags.append("数据口径")
    if request.intake_type == "pdf":
        tags.append("PDF 摘要")

    keyword_tags = [
        ("退换货", "退换货"),
        ("起球", "起球"),
        ("尺码", "尺码"),
        ("洗护", "洗护"),
        ("DWR", "DWR"),
        ("活动", "活动规则"),
        ("赠品", "赠品"),
        ("SKU", "SKU"),
        ("质检", "质检"),
        ("供应商", "供应链"),
    ]
    for keyword, tag in keyword_tags:
        if keyword.lower() in text.lower():
            tags.append(tag)

    deduped: list[str] = []
    for tag in tags:
        if tag and tag not in deduped:
            deduped.append(tag)
    return deduped[:8]


def _missing_fields(request: BrandKbIntakeAssistRequest) -> list[str]:
    missing: list[str] = []
    if not request.source_note.strip():
        missing.append("来源说明")
    if request.intake_type == "data":
        missing.extend(["数据口径", "时间范围", "字段说明", "owner"])
    if request.intake_type in {"pdf", "other"} and not request.raw_body.strip():
        missing.append("文件摘要或适用范围")
    if not request.title.strip():
        missing.append("明确标题")
    return missing


def _authority_level(
    request: BrandKbIntakeAssistRequest,
    sensitive_risks: list[str],
) -> AuthorityLevel:
    if sensitive_risks:
        return "reference"
    if request.intake_type in {"data", "pdf", "other"}:
        return "raw"
    source = request.source_note.lower()
    if any(keyword in source for keyword in ["官方", "已审批", "制度", "标准"]):
        return "official"
    return "reference"


def _build_markdown_draft(
    request: BrandKbIntakeAssistRequest,
    title: str,
    content_kind: ContentKind,
    authority_level: AuthorityLevel,
    tags: list[str],
    missing: list[str],
    sensitive_risks: list[str],
) -> str:
    body = _mask_sensitive_text(request.raw_body.strip())
    if not body:
        body = "需管理员根据原始文件补充结构化正文。"

    return f"""---
kb_intake_type: {request.intake_type}
business_domain: {request.business_domain}
content_kind: {content_kind}
authority_level: {authority_level}
lifecycle_status: draft
owner: ""
review_at: ""
source_note: "{request.source_note.strip() or "需补充来源说明"}"
custom_tags: {tags}
ai_assisted: true
---

# {title}

## 摘要

本文由 AI 辅助录入生成草稿，发布前必须由内容管理员复核来源、适用范围和敏感信息边界。

## 适用场景

适用于 {request.business_domain} 相关知识沉淀；如场景不准确，请管理员在发布前调整。

## 标准口径

{body}

## 操作步骤

1. 核对来源是否可信。
2. 补齐适用范围、负责人和复核日期。
3. 确认是否可作为正式知识进入检索。

## 禁止表达 / 风险边界

{"；".join(sensitive_risks) if sensitive_risks else "暂无自动识别的敏感风险；仍需人工复核。"}

## 需要人工确认的信息

{"；".join(missing) if missing else "暂无明显缺失字段。"}

## 来源说明

{request.source_note.strip() or "需补充来源说明。"}
"""


def build_brand_kb_intake_assist_response(
    request: BrandKbIntakeAssistRequest,
) -> BrandKbIntakeAssistResponse:
    title = _derive_title(request)
    content_kind = _infer_content_kind(request)
    sensitive_risks = _detect_sensitive_risks(
        f"{request.title}\n{request.raw_body}\n{request.source_note}\n{request.file_name or ''}"
    )
    missing = _missing_fields(request)
    authority_level = _authority_level(request, sensitive_risks)
    tags = _derive_tags(request, content_kind)

    quality_warnings = [
        "MVP 当前使用后端启发式整理 stub；后续需接入受控 LLM provider。",
    ]
    if len(request.raw_body.strip()) < 30:
        quality_warnings.append("正文信息较少，建议补充背景、场景或具体口径。")
    if request.intake_type in {"pdf", "other"}:
        quality_warnings.append("原始文件不会直接成为高质量知识源，建议发布前整理为 Markdown 摘要。")

    return BrandKbIntakeAssistResponse(
        mode="stub",
        llm_used=False,
        generated_by="deterministic_stub",
        suggested_title=title,
        business_domain=request.business_domain,
        content_kind=content_kind,
        authority_level=authority_level,
        suggested_tags=tags,
        source_note=request.source_note.strip() or "需补充来源说明",
        missing_fields=missing,
        sensitive_risks=sensitive_risks,
        quality_warnings=quality_warnings,
        warnings=[
            "LLM assistance is not configured; returned rule-based draft metadata.",
        ],
        markdown_draft=_build_markdown_draft(
            request=request,
            title=title,
            content_kind=content_kind,
            authority_level=authority_level,
            tags=tags,
            missing=missing,
            sensitive_risks=sensitive_risks,
        ),
    )


@router.post("/intake/assist", tags=PUBLIC_API_TAGS)
def assist_brand_kb_intake(
    request: BrandKbIntakeAssistRequest,
    _: Any = Depends(_basic_access),
) -> BrandKbIntakeAssistResponse:
    # TODO: Replace this deterministic MVP stub with a configured Onyx LLM
    # provider call. Keep the same request/response contract and retain the
    # safety checks as a post-processing guard before returning model output.
    return build_brand_kb_intake_assist_response(request)
