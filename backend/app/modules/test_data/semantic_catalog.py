"""测试物料语义目录。

本目录用于两类消费方：
- 前端编辑器：给 purpose / semantic 下拉提供标准选项，同时允许自定义。
- UI 自动化 skill：让 LLM 在选物料时优先使用稳定语义，而不是猜 key 名。

字段只作为推荐词表，不限制数据库存储；用户仍可按项目习惯自定义。
"""

from __future__ import annotations

from typing import TypedDict


class SemanticCatalogEntry(TypedDict):
    value: str
    label: str
    category: str
    description: str


ITEM_SEMANTICS: tuple[SemanticCatalogEntry, ...] = (
    {
        "value": "login_username",
        "label": "登录用户名",
        "category": "account",
        "description": "用于账号密码登录的用户名、工号或账号名",
    },
    {
        "value": "login_password",
        "label": "登录密码",
        "category": "account",
        "description": "与登录账号配套的密码或临时密码",
    },
    {
        "value": "login_phone",
        "label": "登录手机号",
        "category": "account",
        "description": "手机号登录、短信登录或账号绑定场景使用",
    },
    {
        "value": "login_email",
        "label": "登录邮箱",
        "category": "account",
        "description": "邮箱登录或账号绑定场景使用",
    },
    {
        "value": "verification_code",
        "label": "验证码",
        "category": "account",
        "description": "短信、邮箱或图形验证码测试值",
    },
    {
        "value": "target_user_id",
        "label": "目标用户 ID",
        "category": "user",
        "description": "查询、编辑或授权目标用户时使用的用户标识",
    },
    {
        "value": "target_username",
        "label": "目标用户名",
        "category": "user",
        "description": "查询、编辑或授权目标用户时使用的展示名或登录名",
    },
    {
        "value": "product_id",
        "label": "商品 ID",
        "category": "commerce",
        "description": "商品详情、下单、库存或搜索场景使用的商品标识",
    },
    {
        "value": "product_name",
        "label": "商品名称",
        "category": "commerce",
        "description": "商品搜索、创建或断言场景使用的商品名",
    },
    {
        "value": "order_id",
        "label": "订单 ID",
        "category": "commerce",
        "description": "订单查询、支付、售后或履约场景使用的订单标识",
    },
    {
        "value": "amount",
        "label": "金额",
        "category": "commerce",
        "description": "支付、退款、优惠或校验金额时使用",
    },
    {
        "value": "coupon_code",
        "label": "优惠码",
        "category": "commerce",
        "description": "优惠券、营销活动或兑换码场景使用",
    },
    {
        "value": "search_keyword",
        "label": "搜索关键词",
        "category": "content",
        "description": "列表检索、全局搜索或筛选场景使用",
    },
    {
        "value": "upload_file",
        "label": "上传文件",
        "category": "file",
        "description": "文件上传、导入或附件场景使用",
    },
    {
        "value": "contact_name",
        "label": "联系人姓名",
        "category": "profile",
        "description": "表单、收货地址、联系人维护场景使用",
    },
    {
        "value": "contact_phone",
        "label": "联系人电话",
        "category": "profile",
        "description": "表单、收货地址、联系人维护场景使用",
    },
    {
        "value": "address",
        "label": "地址",
        "category": "profile",
        "description": "收货地址、门店地址或地区表单场景使用",
    },
    {
        "value": "tenant_id",
        "label": "租户 ID",
        "category": "system",
        "description": "多租户、组织隔离或权限边界场景使用",
    },
)


SET_PURPOSES: tuple[SemanticCatalogEntry, ...] = (
    {
        "value": "login",
        "label": "登录账号",
        "category": "account",
        "description": "账号、密码、验证码等登录基础物料",
    },
    {
        "value": "smoke",
        "label": "冒烟测试",
        "category": "quality",
        "description": "稳定、可重复使用的核心链路物料",
    },
    {
        "value": "regression",
        "label": "回归测试",
        "category": "quality",
        "description": "覆盖常规回归场景的综合物料",
    },
    {
        "value": "negative",
        "label": "异常场景",
        "category": "quality",
        "description": "非法输入、边界值、权限不足等负向物料",
    },
    {
        "value": "commerce",
        "label": "交易链路",
        "category": "business",
        "description": "商品、订单、支付、售后等交易相关物料",
    },
    {
        "value": "profile",
        "label": "用户资料",
        "category": "business",
        "description": "联系人、地址、个人信息等资料维护物料",
    },
    {
        "value": "file_upload",
        "label": "文件上传",
        "category": "file",
        "description": "附件、导入模板、图片或文档上传物料",
    },
    {
        "value": "environment_default",
        "label": "环境默认",
        "category": "system",
        "description": "特定测试环境默认加载的基础物料集",
    },
)


def list_semantic_catalog() -> dict[str, list[SemanticCatalogEntry]]:
    """返回可 JSON 序列化的语义目录副本。"""
    return {
        "item_semantics": [dict(item) for item in ITEM_SEMANTICS],
        "set_purposes": [dict(item) for item in SET_PURPOSES],
    }
