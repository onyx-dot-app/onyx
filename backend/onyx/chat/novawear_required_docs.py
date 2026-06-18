"""NOVAWEAR-specific required document routing for local brand KB demos.

This is intentionally narrow: it only runs for NOVAWEAR personas and only
adds project/persona user files that already belong to the current user scope.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from sqlalchemy.orm import Session

from onyx.db.models import Persona
from onyx.db.models import UserFile
from onyx.file_store.models import FileDescriptor
from onyx.server.query_and_chat.chat_utils import mime_type_to_chat_file_type


INTENT_ROUTES: dict[str, dict[str, Any]] = {
    "campaign_brief": {
        "personas": ("design_planning",),
        "triggers": (
            "季度设计企划",
            "设计企划 brief",
            "企划 brief",
            "主题、目标人群",
            "产品结构和表达边界",
            "FW2026 通勤胶囊",
        ),
        "required_docs": (
            "fw2026-campaign-brief.md",
            "commuter-capsule-launch.md",
            "brand-positioning.md",
        ),
    },
    "design_product_structure": {
        "personas": ("design_planning",),
        "triggers": ("一周通勤", "SKU 组合", "产品结构", "价格带逻辑"),
        "required_docs": (
            "sku-master-fw2026.md",
            "product-line-overview.md",
            "pricing-strategy.md",
            "commuter-capsule-launch.md",
            "outerwear-product-guide.md",
            "pants-product-guide.md",
        ),
    },
    "product_story": {
        "personas": ("design_planning",),
        "triggers": ("产品故事", "NW-OW-2601", "内容角度", "不夸大防水能力"),
        "required_docs": (
            "outerwear-product-guide.md",
            "sku-master-fw2026.md",
            "tone-of-voice.md",
        ),
    },
    "price_objection": {
        "personas": ("product_training",),
        "triggers": ("太贵", "1299", "值不值", "价格", "硬推", "划算"),
        "required_docs": (
            "objection-handling.md",
            "pricing-strategy.md",
            "commuter-capsule-launch.md",
        ),
    },
    "membership_livestream": {
        "personas": ("design_planning", "customer_service"),
        "triggers": ("直播", "直播间", "会员活动", "权益", "赠品", "提前锁定"),
        "required_docs": (
            "membership-campaign.md",
            "fw2026-campaign-brief.md",
            "livestream-script-fw2026.md",
        ),
    },
    "membership_xiaohongshu": {
        "personas": ("design_planning",),
        "triggers": ("小红书", "种草", "选题", "会员", "内容角度"),
        "required_docs": (
            "membership-campaign.md",
            "xiaohongshu-content-examples.md",
            "tone-of-voice.md",
        ),
    },
    "dwr_waterproof_boundary": {
        "personas": ("design_planning", "product_training", "customer_service"),
        "triggers": (
            "DWR",
            "防泼",
            "泼水",
            "不泼水",
            "洗几次",
            "防水",
            "暴雨",
            "十年",
            "永不失效",
            "绝对防水",
        ),
        "required_docs": (
            "fabric-qc-standards.md",
            "care-instructions.md",
            "faq.md",
            "visual-and-copy-dos-donts.md",
            "fw2026-campaign-brief.md",
        ),
        "required_docs_by_persona": {
            "design_planning": (
                "fabric-qc-standards.md",
                "care-instructions.md",
                "visual-and-copy-dos-donts.md",
                "fw2026-campaign-brief.md",
            ),
            "product_training": (
                "fabric-qc-standards.md",
                "care-instructions.md",
                "faq.md",
            ),
            "customer_service": (
                "fabric-qc-standards.md",
                "care-instructions.md",
                "faq.md",
                "quality-issue-handling.md",
                "defect-classification.md",
                "fw2026-campaign-brief.md",
            ),
        },
    },
    "return_exchange": {
        "personas": ("customer_service",),
        "triggers": ("尺码不合适", "吊牌", "退换货", "物流", "判断路径", "退货", "换货"),
        "required_docs": (
            "return-and-exchange-policy.md",
            "size-recommendation-scripts.md",
            "shipping-and-logistics.md",
        ),
    },
    "size_talktrack": {
        "personas": ("product_training",),
        "triggers": ("165cm", "55kg", "尺码建议", "试穿", "尺码", "轻机能裤"),
        "required_docs": (
            "size-and-fit-guide.md",
            "size-recommendation-scripts.md",
            "sku-master-fw2026.md",
        ),
    },
    "product_quiz": {
        "personas": ("product_training",),
        "triggers": ("测验题", "商品知识测验", "培训考核", "外套、裤装、面料", "洗护和竞品"),
        "required_docs": (
            "product-line-overview.md",
            "care-instructions.md",
            "competitor-landscape.md",
        ),
    },
    "quality_after_sales": {
        "personas": ("customer_service",),
        "triggers": ("起球", "掉色", "质量问题", "赔付", "退换", "售后", "缺陷", "拉链"),
        "required_docs": (
            "quality-issue-handling.md",
            "defect-classification.md",
            "fabric-qc-standards.md",
        ),
    },
    "training_outline": {
        "personas": ("product_training",),
        "triggers": ("培训大纲", "门店导购", "SKU、价格、面料、尺码、搭配和异议处理"),
        "required_docs": (
            "store-associate-playbook.md",
            "sku-master-fw2026.md",
            "fabric-and-materials.md",
            "size-and-fit-guide.md",
            "styling-recommendations.md",
            "objection-handling.md",
            "pricing-strategy.md",
        ),
    },
    "commuter_capsule_recommendation": {
        "personas": ("product_training",),
        "triggers": ("通勤胶囊", "骑行", "办公室", "城市徒步", "推荐", "搭配", "场景推荐"),
        "required_docs": (
            "commuter-capsule-launch.md",
            "customer-needs-diagnosis.md",
            "styling-recommendations.md",
            "outerwear-product-guide.md",
            "pants-product-guide.md",
            "product-line-overview.md",
            "sku-master-fw2026.md",
            "pricing-strategy.md",
        ),
    },
    "pdp_to_sales": {
        "personas": ("product_training",),
        "triggers": ("PDP", "详情页", "导购话术", "销售话术", "门店话术", "转成门店"),
        "required_docs": (
            "pdp-copy-guidelines.md",
            "commuter-capsule-launch.md",
            "store-associate-playbook.md",
        ),
    },
    "competitor_boundary": {
        "personas": ("design_planning", "product_training"),
        "triggers": ("Uniqlo", "lululemon", "Arc'teryx", "Veilance", "平替", "同款", "竞品"),
        "required_docs": (
            "competitor-landscape.md",
            "pricing-strategy.md",
            "uniqlo-comparison.md",
            "lululemon-comparison.md",
            "arcteryx-veilance-comparison.md",
        ),
    },
    "privacy_or_sensitive_export": {
        "personas": ("customer_service",),
        "triggers": ("手机号", "订单号", "会员 ID", "地址", "支付", "供应商", "采购成本", "合同", "导出"),
        "required_docs": (
            "membership-campaign.md",
            "supplier-communication-rules.md",
            "vip-client-service.md",
        ),
    },
}


def _is_novawear_persona(persona: Persona) -> bool:
    return bool(persona.name and persona.name.startswith("NOVAWEAR"))


def _persona_key(persona: Persona) -> str | None:
    name = persona.name or ""
    if "设计企划" in name:
        return "design_planning"
    if "商品培训" in name:
        return "product_training"
    if "客服售后" in name:
        return "customer_service"
    return None


def _route_required_docs(route: dict[str, Any], persona_key: str | None) -> tuple[str, ...]:
    by_persona = route.get("required_docs_by_persona", {})
    if isinstance(by_persona, dict) and persona_key and persona_key in by_persona:
        return tuple(by_persona[persona_key])
    return tuple(route["required_docs"])


def _matched_required_doc_names(message: str, persona: Persona) -> tuple[str, ...]:
    persona_key = _persona_key(persona)
    matched: list[str] = []
    for route in INTENT_ROUTES.values():
        allowed_personas = tuple(route.get("personas") or ())
        if allowed_personas and persona_key not in allowed_personas:
            continue
        if any(trigger.lower() in message.lower() for trigger in route["triggers"]):
            matched.extend(_route_required_docs(route, persona_key))
    return tuple(dict.fromkeys(matched))


def _file_descriptor(user_file: UserFile) -> FileDescriptor:
    return {
        "id": user_file.file_id,
        "type": mime_type_to_chat_file_type(user_file.file_type),
        "name": user_file.name,
        "user_file_id": str(user_file.id),
    }


def novawear_required_search_document_ids(*, message: str, persona: Persona) -> list[str]:
    if not _is_novawear_persona(persona):
        return []

    required_names = set(_matched_required_doc_names(message, persona))
    if not required_names:
        return []

    persona_files = {Path(user_file.name).name: user_file for user_file in persona.user_files}
    return [
        persona_files[name].file_id
        for name in required_names
        if name in persona_files
    ]


def add_novawear_required_file_descriptors(
    *,
    message: str,
    persona: Persona,
    file_descriptors: list[FileDescriptor],
    db_session: Session,
) -> list[FileDescriptor]:
    """Append required NOVAWEAR docs for the current intent.

    The candidate pool is the persona's scoped user files, so this cannot grant
    access to files outside the assistant's configured knowledge scope.
    """
    if not _is_novawear_persona(persona):
        return file_descriptors

    required_names = set(_matched_required_doc_names(message, persona))
    if not required_names:
        return file_descriptors

    existing_user_file_ids = {
        str(item.get("user_file_id"))
        for item in file_descriptors
        if item.get("user_file_id")
    }
    persona_files = {Path(user_file.name).name: user_file for user_file in persona.user_files}
    routed_files = [
        persona_files[name]
        for name in required_names
        if name in persona_files and str(persona_files[name].id) not in existing_user_file_ids
    ]
    if not routed_files:
        return file_descriptors

    return [*file_descriptors, *[_file_descriptor(user_file) for user_file in routed_files]]
