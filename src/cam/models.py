from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from . import formatting


@dataclass
class Account:
    id: str
    label: str
    email: str
    identity: dict
    user_id: str | None
    claude_oauth: dict
    added_at: str
    updated_at: str | None = None
    last_used_at: str | None = None
    path: Path | None = None

    @classmethod
    def from_dict(cls, d: dict, path: Path | None = None) -> "Account":
        return cls(
            id=d["id"],
            label=d.get("label") or d.get("email") or d["id"],
            email=d.get("email", ""),
            identity=d.get("identity") or {},
            user_id=d.get("userID"),
            claude_oauth=d.get("claudeAiOauth") or {},
            added_at=d.get("added_at", ""),
            updated_at=d.get("updated_at"),
            last_used_at=d.get("last_used_at"),
            path=path,
        )

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "label": self.label,
            "email": self.email,
            "identity": self.identity,
            "userID": self.user_id,
            "claudeAiOauth": self.claude_oauth,
            "added_at": self.added_at,
            "updated_at": self.updated_at,
            "last_used_at": self.last_used_at,
        }

    @property
    def org_name(self) -> str:
        return self.identity.get("organizationName", "") or ""

    @property
    def org_role(self) -> str:
        return self.identity.get("organizationRole", "") or ""

    @property
    def plan(self) -> str:
        return formatting.plan_label(self.identity, self.claude_oauth)

    @property
    def expiry_text(self) -> str:
        return formatting.token_expiry_text(self.claude_oauth)

    @property
    def expired(self) -> bool:
        return formatting.is_expired(self.claude_oauth)
