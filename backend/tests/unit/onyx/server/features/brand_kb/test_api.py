from fastapi import FastAPI
from fastapi.testclient import TestClient

from onyx.server.features.brand_kb.api import _basic_access
from onyx.server.features.brand_kb.api import BrandKbIntakeAssistRequest
from onyx.server.features.brand_kb.api import build_brand_kb_intake_assist_response
from onyx.server.features.brand_kb.api import router


def test_brand_kb_intake_assist_flags_sensitive_data() -> None:
    request = BrandKbIntakeAssistRequest(
        project_id=1,
        intake_type="text",
        business_domain="service",
        title="会员售后记录补充",
        raw_body="会员手机号 13800138000，订单号：NW202606210001，联系 admin@example.com。",
        source_note="客服会议纪要",
        file_name=None,
        file_mime_type=None,
    )

    response = build_brand_kb_intake_assist_response(request)

    assert response.mode == "stub"
    assert response.llm_used is False
    assert response.generated_by == "deterministic_stub"
    assert "手机号" in response.sensitive_risks
    assert "订单号" in response.sensitive_risks
    assert "邮箱" in response.sensitive_risks
    assert response.authority_level == "reference"
    assert "[手机号需脱敏]" in response.markdown_draft
    assert "[邮箱需脱敏]" in response.markdown_draft
    assert "[订单号需脱敏]" in response.markdown_draft


def test_brand_kb_intake_assist_data_requires_governance_fields() -> None:
    request = BrandKbIntakeAssistRequest(
        project_id=1,
        intake_type="data",
        business_domain="product",
        title="FW2026 SKU 价格表",
        raw_body="NW-OW-2601 1299 元",
        source_note="",
        file_name="sku-price.csv",
        file_mime_type="text/csv",
    )

    response = build_brand_kb_intake_assist_response(request)

    assert response.content_kind == "data_record"
    assert response.authority_level == "raw"
    assert "数据口径" in response.missing_fields
    assert "时间范围" in response.missing_fields
    assert "字段说明" in response.missing_fields
    assert "owner" in response.missing_fields
    assert "数据口径" in response.suggested_tags


def test_brand_kb_intake_assist_endpoint_contract() -> None:
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[_basic_access] = lambda: object()
    client = TestClient(app)

    response = client.post(
        "/brand-kb/intake/assist",
        json={
            "project_id": 1,
            "intake_type": "text",
            "business_domain": "service",
            "title": "退换货 FAQ",
            "raw_body": "问：用户要求一定赔付怎么答？答：进入审核路径，不能承诺一定赔付。",
            "source_note": "客服 SOP",
            "file_name": None,
            "file_mime_type": None,
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["mode"] == "stub"
    assert body["llm_used"] is False
    assert body["content_kind"] == "faq"
    assert body["business_domain"] == "service"
    assert body["markdown_draft"].startswith("---")
