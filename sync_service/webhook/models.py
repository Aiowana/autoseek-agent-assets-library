"""
Webhook 数据模型

定义 GitHub Webhook 事件的数据结构。
"""

from dataclasses import dataclass
from typing import Any, Dict, List, Optional
from datetime import datetime


@dataclass
class PushEvent:
    """GitHub Push 事件"""

    ref: str
    before: str
    after: str
    repository: Dict[str, Any]
    pusher: Dict[str, str]
    sender: Dict[str, str]
    commits: List[Dict[str, Any]]
    created_at: datetime

    @property
    def branch(self) -> str:
        """获取分支名"""
        if self.ref.startswith("refs/heads/"):
            return self.ref[11:]
        return self.ref

    @property
    def is_main_branch(self) -> bool:
        """是否是主分支"""
        return self.branch in ("main", "master")

    @property
    def commit_count(self) -> int:
        """提交数量"""
        return len(self.commits)


@dataclass
class WebhookEvent:
    """Webhook 事件基类"""

    event_type: str
    delivery_id: str
    payload: Dict[str, Any]
    received_at: datetime

    def as_push_event(self) -> Optional[PushEvent]:
        """转换为 Push 事件"""
        if self.event_type != "push":
            return None

        try:
            return PushEvent(
                ref=self.payload.get("ref", ""),
                before=self.payload.get("before", ""),
                after=self.payload.get("after", ""),
                repository=self.payload.get("repository", {}),
                pusher=self.payload.get("pusher", {}),
                sender=self.payload.get("sender", {}),
                commits=self.payload.get("commits", []),
                created_at=self.received_at,
            )
        except Exception:
            return None


@dataclass
class SyncTrigger:
    """同步触发器"""

    source: str  # "webhook" | "polling" | "manual"
    event_type: Optional[str] = None  # "push" | "ping" | etc.
    delivery_id: Optional[str] = None  # Webhook 交付 ID
    commit_sha: Optional[str] = None  # 触发的 Commit SHA

    def to_dict(self) -> Dict[str, Any]:
        return {
            "source": self.source,
            "event_type": self.event_type,
            "delivery_id": self.delivery_id,
            "commit_sha": self.commit_sha,
        }
