# subagent-budget-team

Team/CI budget control for subagent token spend. When several agents run
concurrently — a CI matrix, a fleet of coding agents, a team sharing one
token pool — costs can spiral before anyone notices. `subagent-budget-team`
gives you a **pre-spend control plane**: shared budget pools, per-agent
quotas, overspend detection, and a kill switch that freezes spend *before*
the next invoice.

Measured context: subagents can burn ~48% of an agent's total token budget
(see the `subagent-tax` write-up). This tool is what you deploy once you
know that number and want to do something about it at the team level.

## Install

```bash
pip install subagent-budget-team
```

Requires Python 3.9+. Zero dependencies (stdlib only).

## Usage

```bash
# 1. Create a shared budget pool for a CI job or team
subagent-budget-team pool create --name ci-nightly --limit-usd 25

# 2. Give each agent its own quota inside the pool
subagent-budget-team quota set --pool ci-nightly --agent coder-1 --limit-usd 5
subagent-budget-team quota set --pool ci-nightly --agent reviewer-1 --limit-usd 3

# 3. Record spend (call this from your agent wrapper / CI step)
subagent-budget-team spend --pool ci-nightly --agent coder-1 --tokens 12000 --usd 1.20

# 4. Check everything; exit code 1 means over budget — gate your CI on it
subagent-budget-team check
# or machine-readable:
subagent-budget-team check --json

# 5. Kill switch: freeze a pool (or a single agent) immediately
subagent-budget-team kill --pool ci-nightly
subagent-budget-team spend --pool ci-nightly --agent coder-1 --usd 1  # rejected
subagent-budget-team release --pool ci-nightly                        # unfreeze

# List pools
subagent-budget-team pool list
```

State lives in `~/.subagent-budget-team/budgets.json` (override with
`--state` or the `SBT_HOME` env var, handy for per-job isolation in CI).

### CI example (GitHub Actions)

```yaml
- run: pip install subagent-budget-team
- run: subagent-budget-team pool create --name pr-${{ github.event.number }} --limit-usd 10
- run: ./run-agents.sh   # agents call `spend` as they work
- run: subagent-budget-team check   # fails the job on overspend
- if: failure()
  run: subagent-budget-team kill --pool pr-${{ github.event.number }}
```

## Differentiation

- **vs `subagent-tax`**: that tool is a *personal audit* lens — it measures
  how much of *your* token budget subagents burn after the fact.
  `subagent-budget-team` is the *team/CI control* lens: a shared budget
  pool with per-agent quotas and a circuit breaker, designed for many
  agents spending from one pot.
- **vs cloud-vendor budget alerts**: those are *post-hoc alarms* — you get
  paged after the money is spent. This is a *pre-spend circuit breaker*:
  `kill` rejects new spend immediately and `check` can gate a pipeline
  before the next batch of work runs.

## License

MIT — see [LICENSE](LICENSE).
