#!/usr/bin/env python3
"""
feishu_notify.py — 飞书私聊 + memory_file 双通道 + 24h 去重（Phase 2）

契约来源：
  - D-20260806-011: 24h 同单号同异常类型去重，SKILL 内部维护
  - config.yaml notify 块: channels=[feishu_dm(ou_...), memory_file(memory/
    notify_<date>.md)] / dedup.window_hours=24
  - CLAUDE.md 原则 9: retry 类不飞书通知（调用方凭 failure_handler.decide().notify 过滤）
  - CLAUDE.md 原则 10: cron 空跑不通知（调用方保证）

发送门（开发安全）：env FEISHU_NOTIFY_ENABLED=1 才真发飞书私聊，
缺省 = 只记 memory 通道（防开发迭代打扰确认人）。生产 cron 环境开启。

通道与状态分离：
  - memory 通道 = 按 config 路径写每日 markdown 记录（memory/notify_<date>.md）——
    本地开发为普通文件近似；生产需指向 OpenClaw workspace memory 目录
    （config notify.channels[memory_file].path 可调，Phase 4 部署验证项）
  - 去重状态 = state/notify_dedup.json（SKILL 内部机器状态，不放 memory 通道，
    防污染 OpenClaw memory 记录）
"""
from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

logger = logging.getLogger("feishu_notify")

BASE_DIR = Path(__file__).resolve().parent.parent
CST = timezone(timedelta(hours=8))
DEDUP_STATE_DIR = "state"
DEDUP_STATE_FILE = "notify_dedup.json"


# ============================================================
# 24h 去重（D-20260806-011）
# ============================================================

class NotifyDedup:
    """同单号同异常类型 window_hours 内只通知一次。状态持久化到 state/ JSON。"""

    def __init__(self, state_dir: Path | str | None = None, window_hours: int = 24):
        base = Path(state_dir) if state_dir else BASE_DIR / DEDUP_STATE_DIR
        self.state_path = base / DEDUP_STATE_FILE
        self.window = timedelta(hours=window_hours)
        self.state: dict[str, str] = {}
        self._load()

    def _load(self) -> None:
        if self.state_path.exists():
            try:
                self.state = json.loads(self.state_path.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                logger.warning("去重状态文件损坏, 重置: %s", self.state_path)
                self.state = {}

    def _save(self) -> None:
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        self.state_path.write_text(json.dumps(self.state, ensure_ascii=False, indent=2),
                                   encoding="utf-8")

    @staticmethod
    def _key(order_id: str, exc_type: str) -> str:
        return f"{order_id}|{exc_type}"

    def should_notify(self, order_id: str, exc_type: str, now: datetime) -> bool:
        """True = 应通知（首次或超窗）并记录本次时间；False = 去重跳过。"""
        key = self._key(order_id, exc_type)
        last_raw = self.state.get(key)
        if last_raw:
            try:
                last = datetime.fromisoformat(last_raw)
                if now - last < self.window:
                    return False
            except ValueError:
                pass  # 损坏的时间戳按可通知处理
        self.state[key] = now.isoformat()
        self._save()
        return True

    def cleanup(self, now: datetime) -> int:
        """清理超窗条目，返回清理数。"""
        expired = []
        for key, raw in self.state.items():
            try:
                if now - datetime.fromisoformat(raw) >= self.window:
                    expired.append(key)
            except ValueError:
                expired.append(key)
        for key in expired:
            del self.state[key]
        if expired:
            self._save()
        return len(expired)


# ============================================================
# 消息构造与发送
# ============================================================

def _notify_cfg(cfg: dict) -> dict:
    return cfg["notify"]


def _feishu_dm_target(cfg: dict) -> Optional[str]:
    for ch in _notify_cfg(cfg).get("channels") or []:
        if ch.get("type") == "feishu_dm":
            return ch.get("target")
    return None


def render_message(order_id: str, exc_type: str, detail: str,
                   now: datetime) -> str:
    ts = now.astimezone(CST).strftime("%Y-%m-%d %H:%M")
    return (f"【升级售后判责异常】{ts}\n"
            f"单号: {order_id}\n"
            f"异常类型: {exc_type}\n"
            f"详情: {detail}")


def send_feishu_dm(cfg: dict, text: str, idempotency_key: Optional[str] = None) -> dict:
    """飞书私聊发送（env FEISHU_NOTIFY_ENABLED=1 门控）。"""
    if os.environ.get("FEISHU_NOTIFY_ENABLED") != "1":
        logger.info("发送门未开(FEISHU_NOTIFY_ENABLED!=1), 跳过飞书私聊: %s",
                    text.splitlines()[0] if text else "")
        return {"skipped": True}
    from data_loader import run_lark_cli  # noqa: PLC0415
    target = _feishu_dm_target(cfg)
    if not target:
        raise ValueError("config notify.channels 缺 feishu_dm target")
    args = ["im", "+messages-send", "--user-id", target, "--text", text]
    if idempotency_key:
        args += ["--idempotency-key", idempotency_key[:50]]
    return run_lark_cli(args, cfg)


def append_memory_file(cfg: dict, line: str, now: datetime) -> Path:
    """memory 通道：memory/notify_<date>.md 追加。"""
    path_tpl = None
    for ch in _notify_cfg(cfg).get("channels") or []:
        if ch.get("type") == "memory_file":
            path_tpl = ch.get("path")
    rel = (path_tpl or "memory/notify_<date>.md").replace(
        "<date>", now.astimezone(CST).strftime("%Y-%m-%d"))
    path = BASE_DIR / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a", encoding="utf-8") as f:
        f.write(line.rstrip("\n") + "\n")
    return path


def notify(cfg: dict, dedup: NotifyDedup, order_id: str, exc_type: str,
           detail: str, now: datetime) -> dict:
    """双通道通知入口（含 24h 去重）。

    飞书通道失败不阻断 memory 通道（降级只记本地）。
    """
    if not dedup.should_notify(order_id, exc_type, now):
        return {"notified": False, "reason": "24h 去重跳过"}
    msg = render_message(order_id, exc_type, detail, now)
    dm_result: dict
    try:
        dm_result = send_feishu_dm(cfg, msg, idempotency_key=f"{order_id}|{exc_type}")
    except Exception as e:  # noqa: BLE001 — 飞书失败降级 memory 通道
        logger.warning("飞书私聊发送失败, 降级 memory 通道: %s", e)
        dm_result = {"error": str(e)}
    mem_path = append_memory_file(cfg, msg, now)
    return {"notified": True, "dm": dm_result, "memory_file": str(mem_path)}
