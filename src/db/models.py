"""Database schema (brief §8) as SQLAlchemy ORM models.

Portable across PostgreSQL + TimescaleDB (docker-compose) and SQLite (local
development / tests). Differences are isolated in src/db/session.py:
  * `features` is JSONB on Postgres, JSON text on SQLite
  * on Postgres, time-series tables become Timescale hypertables

Beyond the minimum schema, two columns/tables were added and are documented:
  * metrics.source / stream_index / policy — distinguishes task-sequence
    results from live-stream evaluations
  * drift_events.model_name / stream_index / window_id
  * window_stats — per-window classification counts for the dashboard
"""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import JSON, BigInteger, Boolean, DateTime, Float, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

JSONType = JSON().with_variant(JSONB(), "postgresql")
# SQLite only auto-increments INTEGER PRIMARY KEY; Postgres wants BIGINT.
PK = BigInteger().with_variant(Integer(), "sqlite")


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Base(DeclarativeBase):
    pass


class FlowRecord(Base):
    __tablename__ = "flow_records"
    id: Mapped[int] = mapped_column(PK, primary_key=True, autoincrement=True)
    ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    src_ip: Mapped[str] = mapped_column(String(64))
    dst_ip: Mapped[str] = mapped_column(String(64))
    features: Mapped[dict] = mapped_column(JSONType)
    label: Mapped[str | None] = mapped_column(String(64), nullable=True)
    task_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    window_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    split: Mapped[str | None] = mapped_column(String(8), nullable=True)


class GraphWindow(Base):
    __tablename__ = "graph_windows"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)  # = window_id
    window_start: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    window_end: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    n_nodes: Mapped[int] = mapped_column(Integer)
    n_edges: Mapped[int] = mapped_column(Integer)
    cache_path: Mapped[str] = mapped_column(Text)
    task_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    split: Mapped[str | None] = mapped_column(String(8), nullable=True)


class ReplayBufferEntry(Base):
    __tablename__ = "replay_buffer"
    id: Mapped[int] = mapped_column(PK, primary_key=True, autoincrement=True)
    attack_class: Mapped[str] = mapped_column(String(32))
    window_id: Mapped[int] = mapped_column(Integer)
    subgraph_path: Mapped[str] = mapped_column(Text)
    added_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    model_name: Mapped[str | None] = mapped_column(String(64), nullable=True)


class Prediction(Base):
    __tablename__ = "predictions"
    id: Mapped[int] = mapped_column(PK, primary_key=True, autoincrement=True)
    flow_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True, index=True)
    model_name: Mapped[str] = mapped_column(String(64))
    predicted_label: Mapped[str] = mapped_column(String(32))
    confidence: Mapped[float] = mapped_column(Float)
    ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)


class Metric(Base):
    __tablename__ = "metrics"
    id: Mapped[int] = mapped_column(PK, primary_key=True, autoincrement=True)
    ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)
    model_name: Mapped[str] = mapped_column(String(64), index=True)
    task_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    accuracy: Mapped[float | None] = mapped_column(Float, nullable=True)
    macro_f1: Mapped[float | None] = mapped_column(Float, nullable=True)
    retention_rate: Mapped[float | None] = mapped_column(Float, nullable=True)
    fpr: Mapped[float | None] = mapped_column(Float, nullable=True)
    source: Mapped[str] = mapped_column(String(16), default="continual")  # continual | stream
    policy: Mapped[str | None] = mapped_column(String(16), nullable=True)
    stream_index: Mapped[int | None] = mapped_column(Integer, nullable=True)
    retrains_so_far: Mapped[int | None] = mapped_column(Integer, nullable=True)
    run_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)


class DriftEventRow(Base):
    __tablename__ = "drift_events"
    id: Mapped[int] = mapped_column(PK, primary_key=True, autoincrement=True)
    ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)
    detector: Mapped[str] = mapped_column(String(32))
    prev_error: Mapped[float | None] = mapped_column(Float, nullable=True)
    new_error: Mapped[float | None] = mapped_column(Float, nullable=True)
    triggered_retrain: Mapped[bool] = mapped_column(Boolean)
    model_name: Mapped[str | None] = mapped_column(String(64), nullable=True)
    stream_index: Mapped[int | None] = mapped_column(Integer, nullable=True)
    window_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    reason: Mapped[str | None] = mapped_column(String(64), nullable=True)
    run_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)


class WindowStat(Base):
    __tablename__ = "window_stats"
    id: Mapped[int] = mapped_column(PK, primary_key=True, autoincrement=True)
    ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)
    run_id: Mapped[str] = mapped_column(String(64), index=True)
    model_name: Mapped[str] = mapped_column(String(64))
    stream_index: Mapped[int] = mapped_column(Integer)
    window_id: Mapped[int] = mapped_column(Integer)
    task_id: Mapped[int] = mapped_column(Integer)
    n_flows: Mapped[int] = mapped_column(Integer)
    error_rate: Mapped[float] = mapped_column(Float)
    pred_benign: Mapped[int] = mapped_column(Integer)
    pred_known_attack: Mapped[int] = mapped_column(Integer)
    pred_novel_drifted: Mapped[int] = mapped_column(Integer)
    true_attack_fraction: Mapped[float] = mapped_column(Float)
    drift_flag: Mapped[bool] = mapped_column(Boolean)
    retrained: Mapped[bool] = mapped_column(Boolean)


class ResponseAction(Base):
    """Improvement 15: a proposed containment action awaiting (or after) human decision.
    Execution is always a dry run — approval is recorded, nothing is applied."""
    __tablename__ = "response_actions"
    id: Mapped[int] = mapped_column(PK, primary_key=True, autoincrement=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    window_id: Mapped[int] = mapped_column(Integer)
    incident_id: Mapped[int] = mapped_column(Integer)
    model_name: Mapped[str] = mapped_column(String(64))
    category: Mapped[str] = mapped_column(String(32))
    action: Mapped[str] = mapped_column(String(32))
    target: Mapped[str] = mapped_column(String(64))
    rationale: Mapped[str] = mapped_column(Text)
    rule_linux: Mapped[str | None] = mapped_column(Text, nullable=True)
    rule_windows: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(24), default="proposed")  # proposed | approved | rejected
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    decided_by: Mapped[str | None] = mapped_column(String(64), nullable=True)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)


# Tables converted to Timescale hypertables on Postgres, with their time column.
HYPERTABLES = {"flow_records": "ts", "predictions": "ts", "metrics": "ts", "drift_events": "ts",
               "window_stats": "ts"}
