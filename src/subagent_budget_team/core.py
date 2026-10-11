"""Core budget-pool logic. Pure stdlib: JSON state file, no dependencies."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path


def default_state_path() -> Path:
    base = os.environ.get("SBT_HOME") or os.path.expanduser("~")
    return Path(base) / ".subagent-budget-team" / "budgets.json"


@dataclass
class BudgetError(Exception):
    message: str

    def __str__(self) -> str:  # pragma: no cover - trivial
        return self.message


@dataclass
class Violation:
    kind: str  # "pool_over" | "agent_over" | "killed"
    pool: str
    agent: str | None = None
    detail: str = ""

    def to_dict(self) -> dict:
        return {"kind": self.kind, "pool": self.pool,
                "agent": self.agent, "detail": self.detail}


@dataclass
class Store:
    path: Path = field(default_factory=default_state_path)
    data: dict = field(default_factory=lambda: {"pools": {}})

    # ---- persistence -------------------------------------------------
    def load(self) -> "Store":
        if self.path.exists():
            try:
                self.data = json.loads(self.path.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError) as exc:
                raise BudgetError(f"cannot read state file {self.path}: {exc}")
        self.data.setdefault("pools", {})
        return self

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(self.data, indent=2, sort_keys=True),
                       encoding="utf-8")
        os.replace(tmp, self.path)

    # ---- helpers -----------------------------------------------------
    def _pool(self, name: str) -> dict:
        pool = self.data["pools"].get(name)
        if pool is None:
            raise BudgetError(f"pool '{name}' does not exist")
        return pool

    @staticmethod
    def _check_positive(name: str, value: float | int | None) -> None:
        if value is not None and value <= 0:
            raise BudgetError(f"{name} must be positive, got {value}")

    # ---- pool management ---------------------------------------------
    def create_pool(self, name: str, limit_usd: float | None = None,
                    limit_tokens: int | None = None) -> None:
        if not name or not name.strip():
            raise BudgetError("pool name must not be empty")
        if name in self.data["pools"]:
            raise BudgetError(f"pool '{name}' already exists")
        self._check_positive("limit_usd", limit_usd)
        self._check_positive("limit_tokens", limit_tokens)
        if limit_usd is None and limit_tokens is None:
            raise BudgetError("at least one of --limit-usd / --limit-tokens "
                              "is required")
        self.data["pools"][name] = {
            "limit_usd": limit_usd,
            "limit_tokens": limit_tokens,
            "killed": False,
            "spent_usd": 0.0,
            "spent_tokens": 0,
            "agents": {},
        }
        self.save()

    def list_pools(self) -> list[dict]:
        out = []
        for name, pool in sorted(self.data["pools"].items()):
            out.append({
                "name": name,
                "limit_usd": pool.get("limit_usd"),
                "limit_tokens": pool.get("limit_tokens"),
                "killed": pool.get("killed", False),
                "spent_usd": pool.get("spent_usd", 0.0),
                "spent_tokens": pool.get("spent_tokens", 0),
                "agents": sorted(pool.get("agents", {})),
            })
        return out

    # ---- quotas ------------------------------------------------------
    def set_quota(self, pool_name: str, agent: str,
                  limit_usd: float | None = None,
                  limit_tokens: int | None = None) -> None:
        pool = self._pool(pool_name)
        if not agent or not agent.strip():
            raise BudgetError("agent name must not be empty")
        self._check_positive("limit_usd", limit_usd)
        self._check_positive("limit_tokens", limit_tokens)
        if limit_usd is None and limit_tokens is None:
            raise BudgetError("at least one of --limit-usd / --limit-tokens "
                              "is required")
        agents = pool.setdefault("agents", {})
        entry = agents.get(agent, {"spent_usd": 0.0, "spent_tokens": 0})
        entry["limit_usd"] = limit_usd
        entry["limit_tokens"] = limit_tokens
        agents[agent] = entry
        self.save()

    # ---- spend -------------------------------------------------------
    def record_spend(self, pool_name: str, agent: str, tokens: int = 0,
                     usd: float = 0.0) -> None:
        pool = self._pool(pool_name)
        if pool.get("killed"):
            raise BudgetError(f"pool '{pool_name}' is killed: spend rejected")
        if tokens < 0 or usd < 0:
            raise BudgetError("tokens and usd must be non-negative")
        pool["spent_tokens"] = pool.get("spent_tokens", 0) + tokens
        pool["spent_usd"] = pool.get("spent_usd", 0.0) + usd
        agents = pool.setdefault("agents", {})
        entry = agents.setdefault(agent,
                                  {"spent_usd": 0.0, "spent_tokens": 0,
                                   "limit_usd": None, "limit_tokens": None})
        entry["spent_tokens"] = entry.get("spent_tokens", 0) + tokens
        entry["spent_usd"] = entry.get("spent_usd", 0.0) + usd
        if entry.get("killed"):
            raise BudgetError(f"agent '{agent}' in pool '{pool_name}' is "
                              "killed: spend rejected")
        self.save()

    # ---- kill switch -------------------------------------------------
    def kill(self, pool_name: str, agent: str | None = None) -> None:
        pool = self._pool(pool_name)
        if agent is None:
            pool["killed"] = True
        else:
            entry = pool.get("agents", {}).get(agent)
            if entry is None:
                raise BudgetError(f"agent '{agent}' has no quota in pool "
                                  f"'{pool_name}'")
            entry["killed"] = True
        self.save()

    def release(self, pool_name: str, agent: str | None = None) -> None:
        pool = self._pool(pool_name)
        if agent is None:
            pool["killed"] = False
        else:
            entry = pool.get("agents", {}).get(agent)
            if entry is None:
                raise BudgetError(f"agent '{agent}' has no quota in pool "
                                  f"'{pool_name}'")
            entry["killed"] = False
        self.save()

    # ---- check -------------------------------------------------------
    def check(self) -> list[Violation]:
        violations: list[Violation] = []
        for name, pool in self.data["pools"].items():
            if pool.get("killed"):
                violations.append(Violation(
                    "killed", name,
                    detail=f"pool '{name}' is killed (circuit breaker open)"))
                continue
            limit_usd = pool.get("limit_usd")
            spent_usd = pool.get("spent_usd", 0.0)
            limit_tokens = pool.get("limit_tokens")
            spent_tokens = pool.get("spent_tokens", 0)
            if limit_usd is not None and spent_usd > limit_usd:
                violations.append(Violation(
                    "pool_over", name,
                    detail=f"pool '{name}': spent ${spent_usd:.4f} > "
                           f"limit ${limit_usd:.4f}"))
            if limit_tokens is not None and spent_tokens > limit_tokens:
                violations.append(Violation(
                    "pool_over", name,
                    detail=f"pool '{name}': spent {spent_tokens} tokens > "
                           f"limit {limit_tokens}"))
            for agent, entry in pool.get("agents", {}).items():
                if entry.get("killed"):
                    violations.append(Violation(
                        "killed", name, agent,
                        detail=f"agent '{agent}' in pool '{name}' is killed"))
                    continue
                a_usd = entry.get("limit_usd")
                a_spent_usd = entry.get("spent_usd", 0.0)
                a_tokens = entry.get("limit_tokens")
                a_spent_tokens = entry.get("spent_tokens", 0)
                if a_usd is not None and a_spent_usd > a_usd:
                    violations.append(Violation(
                        "agent_over", name, agent,
                        detail=f"agent '{agent}' in pool '{name}': spent "
                               f"${a_spent_usd:.4f} > limit ${a_usd:.4f}"))
                if a_tokens is not None and a_spent_tokens > a_tokens:
                    violations.append(Violation(
                        "agent_over", name, agent,
                        detail=f"agent '{agent}' in pool '{name}': spent "
                               f"{a_spent_tokens} tokens > limit {a_tokens}"))
        return violations
