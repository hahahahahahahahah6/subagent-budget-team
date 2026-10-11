"""Command-line interface for subagent-budget-team."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from . import __version__
from .core import BudgetError, Store, default_state_path

EXIT_OK = 0
EXIT_OVER_BUDGET = 1
EXIT_USAGE = 2


def _store(args: argparse.Namespace) -> Store:
    path = Path(args.state) if getattr(args, "state", None) else default_state_path()
    return Store(path).load()


def cmd_pool_create(args: argparse.Namespace) -> int:
    try:
        _store(args).create_pool(args.name, args.limit_usd, args.limit_tokens)
    except BudgetError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return EXIT_USAGE
    print(f"pool '{args.name}' created")
    return EXIT_OK


def cmd_pool_list(args: argparse.Namespace) -> int:
    pools = _store(args).list_pools()
    if args.json:
        print(json.dumps(pools, indent=2))
        return EXIT_OK
    if not pools:
        print("no pools yet; create one with: pool create --name NAME --limit-usd X")
        return EXIT_OK
    for p in pools:
        status = "KILLED" if p["killed"] else "active"
        lim = []
        if p["limit_usd"] is not None:
            lim.append(f"${p['limit_usd']:.2f}")
        if p["limit_tokens"] is not None:
            lim.append(f"{p['limit_tokens']} tokens")
        print(f"{p['name']}: limit {' + '.join(lim)} | "
              f"spent ${p['spent_usd']:.4f} / {p['spent_tokens']} tokens | "
              f"{status} | agents: {len(p['agents'])}")
    return EXIT_OK


def cmd_quota_set(args: argparse.Namespace) -> int:
    try:
        _store(args).set_quota(args.pool, args.agent,
                               args.limit_usd, args.limit_tokens)
    except BudgetError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return EXIT_USAGE
    print(f"quota set: agent '{args.agent}' in pool '{args.pool}'")
    return EXIT_OK


def cmd_spend(args: argparse.Namespace) -> int:
    try:
        _store(args).record_spend(args.pool, args.agent,
                                  args.tokens, args.usd)
    except BudgetError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return EXIT_USAGE
    print(f"recorded: agent '{args.agent}' +{args.tokens} tokens "
          f"+${args.usd:.4f} in pool '{args.pool}'")
    return EXIT_OK


def cmd_check(args: argparse.Namespace) -> int:
    violations = _store(args).check()
    if args.json:
        print(json.dumps([v.to_dict() for v in violations], indent=2))
    elif violations:
        print(f"OVER BUDGET: {len(violations)} violation(s)")
        for v in violations:
            print(f"  - {v.detail}")
    else:
        print("OK: all pools and quotas within budget")
    return EXIT_OVER_BUDGET if violations else EXIT_OK


def cmd_kill(args: argparse.Namespace) -> int:
    try:
        _store(args).kill(args.pool, args.agent)
    except BudgetError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return EXIT_USAGE
    target = f"agent '{args.agent}' in " if args.agent else ""
    print(f"kill switch engaged: {target}pool '{args.pool}'")
    return EXIT_OK


def cmd_release(args: argparse.Namespace) -> int:
    try:
        _store(args).release(args.pool, args.agent)
    except BudgetError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return EXIT_USAGE
    target = f"agent '{args.agent}' in " if args.agent else ""
    print(f"released: {target}pool '{args.pool}'")
    return EXIT_OK


def _add_limit_opts(p: argparse.ArgumentParser) -> None:
    p.add_argument("--limit-usd", type=float, default=None,
                   help="budget limit in USD (e.g. 25.50)")
    p.add_argument("--limit-tokens", type=int, default=None,
                   help="budget limit in tokens")


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(
        prog="subagent-budget-team",
        description="Team/CI budget control for subagent token spend: "
                    "shared budget pools, per-agent quotas, overspend checks, "
                    "and a kill switch.",
    )
    ap.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    ap.add_argument("--state", default=None,
                    help="path to state file (default: ~/.subagent-budget-team/budgets.json)")
    sub = ap.add_subparsers(dest="command", required=True)

    # pool create / pool list
    pool_p = sub.add_parser("pool", help="manage budget pools")
    pool_sub = pool_p.add_subparsers(dest="pool_command", required=True)
    pc = pool_sub.add_parser("create", help="create a budget pool")
    pc.add_argument("--name", required=True, help="pool name")
    _add_limit_opts(pc)
    pc.set_defaults(func=cmd_pool_create)
    pl = pool_sub.add_parser("list", help="list budget pools")
    pl.add_argument("--json", action="store_true", help="JSON output")
    pl.set_defaults(func=cmd_pool_list)

    # quota set
    quota_p = sub.add_parser("quota", help="manage per-agent quotas")
    quota_sub = quota_p.add_subparsers(dest="quota_command", required=True)
    qs = quota_sub.add_parser("set", help="set an agent's quota inside a pool")
    qs.add_argument("--pool", required=True, help="pool name")
    qs.add_argument("--agent", required=True, help="agent id")
    _add_limit_opts(qs)
    qs.set_defaults(func=cmd_quota_set)

    # spend
    sp = sub.add_parser("spend", help="record token/USD spend")
    sp.add_argument("--pool", required=True)
    sp.add_argument("--agent", required=True)
    sp.add_argument("--tokens", type=int, default=0)
    sp.add_argument("--usd", type=float, default=0.0)
    sp.set_defaults(func=cmd_spend)

    # check
    ch = sub.add_parser("check", help="detect overspend (exit 1 if over budget)")
    ch.add_argument("--json", action="store_true", help="JSON output")
    ch.set_defaults(func=cmd_check)

    # kill / release
    k = sub.add_parser("kill", help="engage the kill switch (freeze a pool or agent)")
    k.add_argument("--pool", required=True)
    k.add_argument("--agent", default=None, help="omit to kill the whole pool")
    k.set_defaults(func=cmd_kill)
    r = sub.add_parser("release", help="release a kill switch")
    r.add_argument("--pool", required=True)
    r.add_argument("--agent", default=None, help="omit to release the whole pool")
    r.set_defaults(func=cmd_release)

    return ap


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return int(args.func(args))
    except BudgetError as exc:  # pragma: no cover - defensive
        print(f"error: {exc}", file=sys.stderr)
        return EXIT_USAGE


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
