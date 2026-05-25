from __future__ import annotations

from app.modules.ui_automation.requirement_context import (
    build_requirement_context_text,
    extract_relevant_excerpt,
)


def test_extract_relevant_excerpt_prefers_matching_paragraphs() -> None:
    text = "\n\n".join([
        "登录模块支持账号密码登录。",
        "店铺导入支持店铺 ID、店铺名称、主体类型等字段。",
        "订单模块支持查询订单详情。",
    ])
    out = extract_relevant_excerpt(
        text,
        query="验证店铺 ID 导入后列表展示主体类型",
        max_chars=120,
    )
    assert "店铺导入" in out
    assert "主体类型" in out
    assert "订单模块" not in out


def test_build_requirement_context_text_includes_doc_name_and_excerpt() -> None:
    out = build_requirement_context_text(
        document_name="电商平台管理需求.docx",
        content_text="店铺导入支持店铺 ID、店铺名称、主体类型等字段。",
        query="验证店铺 ID 导入",
        max_chars=200,
    )
    assert "来源文档：电商平台管理需求.docx" in out
    assert "相关需求片段" in out
    assert "店铺 ID" in out
