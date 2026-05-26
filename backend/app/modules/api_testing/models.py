from __future__ import annotations

import uuid

from sqlalchemy import ForeignKey, Integer, String, Text, UniqueConstraint, text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base


class ApiTestModule(Base):
    """接口测试模块树节点。独立于测试用例模块。"""

    __tablename__ = "api_test_modules"

    project_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("projects.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    parent_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("api_test_modules.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    order_index: Mapped[int] = mapped_column(Integer, default=0, server_default="0")

    project = relationship("Project", lazy="selectin")
    children: Mapped[list["ApiTestModule"]] = relationship(
        back_populates="parent",
        cascade="all, delete-orphan",
        lazy="selectin",
        order_by="ApiTestModule.order_index",
    )
    parent: Mapped["ApiTestModule | None"] = relationship(
        back_populates="children",
        remote_side="ApiTestModule.id",
        lazy="selectin",
    )
    api_tests: Mapped[list["ApiTestCase"]] = relationship(
        back_populates="module",
        cascade="all, delete-orphan",
        lazy="noload",
    )


class ApiTestEnvironment(Base):
    """项目级 API 环境配置。"""

    __tablename__ = "api_test_environments"

    project_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("projects.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    base_url: Mapped[str] = mapped_column(String(1000), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    order_index: Mapped[int] = mapped_column(Integer, default=0, server_default="0")

    project = relationship("Project", lazy="selectin")
    api_tests: Mapped[list["ApiTestCase"]] = relationship(
        back_populates="environment",
        lazy="noload",
        passive_deletes=True,
    )
    variables: Mapped[list["ApiTestEnvironmentVariable"]] = relationship(
        back_populates="environment",
        cascade="all, delete-orphan",
        lazy="selectin",
        order_by="ApiTestEnvironmentVariable.key",
    )


class ApiTestEnvironmentVariable(Base):
    """API 环境变量，可在 API 请求配置中通过 {{key}} 引用。"""

    __tablename__ = "api_test_environment_variables"
    __table_args__ = (
        UniqueConstraint("environment_id", "key", name="uq_api_test_environment_variables_env_key"),
    )

    project_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("projects.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    environment_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("api_test_environments.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    key: Mapped[str] = mapped_column(String(100), nullable=False)
    value: Mapped[str] = mapped_column(Text, nullable=False)
    description: Mapped[str | None] = mapped_column(Text)

    project = relationship("Project", lazy="selectin")
    environment = relationship("ApiTestEnvironment", back_populates="variables", lazy="selectin")


class ApiTestCase(Base):
    """A regular HTTP API test case saved under an API test module."""

    __tablename__ = "api_test_cases"

    project_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("projects.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    module_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("api_test_modules.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    environment_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("api_test_environments.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    name: Mapped[str] = mapped_column(String(300), nullable=False)
    method: Mapped[str] = mapped_column(String(10), nullable=False)
    url: Mapped[str] = mapped_column(String(1000), nullable=False)
    base_url: Mapped[str | None] = mapped_column(String(1000))
    path: Mapped[str | None] = mapped_column(String(1000))
    headers: Mapped[dict] = mapped_column(
        JSONB,
        nullable=False,
        default=dict,
        server_default=text("'{}'::jsonb"),
    )
    query_params: Mapped[dict] = mapped_column(
        JSONB,
        nullable=False,
        default=dict,
        server_default=text("'{}'::jsonb"),
    )
    body_type: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        default="none",
        server_default="none",
    )
    body_json: Mapped[object | None] = mapped_column(JSONB, nullable=True)
    body_text: Mapped[str | None] = mapped_column(Text)
    assertions: Mapped[list[dict]] = mapped_column(
        JSONB,
        nullable=False,
        default=list,
        server_default=text("'[]'::jsonb"),
    )
    created_by: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id"),
        nullable=False,
    )

    project = relationship("Project", lazy="selectin")
    module = relationship("ApiTestModule", back_populates="api_tests", lazy="selectin")
    environment = relationship("ApiTestEnvironment", back_populates="api_tests", lazy="selectin")
    creator = relationship("User", lazy="selectin")
