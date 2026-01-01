# Multi-Agent Autonomous System

## Overview

This repository uses an intelligent multi-agent orchestrator that automatically selects the best available AI agent to implement tasks, with automatic fallback and retry mechanisms.

## How It Works

### 1. Create an Issue
Create a GitHub issue describing your task.

### 2. Add Label
Add **one** of these labels:

| Label | Behavior |
|-------|----------|
| `agent-auto` | 🎯 **RECOMMENDED** - Intelligent orchestrator tries all 3 agents with automatic fallback |
| `agent-claude` | Forces use of Claude Code only |
| `agent-codex` | Forces use of OpenAI Codex only |
| `agent-gemini` | Forces use of Google Gemini only |

### 3. Automatic Execution

**With `agent-auto` (Smart Mode):**
1. System checks `.github/rate_limits.json` to see which agents are available
2. Tries agents in order: Claude → Codex → Gemini
3. Detects rate limit errors and parses reset times
4. Automatically falls back to next agent if one is rate-limited
5. Updates rate limit tracking file
6. If all agents are rate-limited, adds `rate-limited-all-agents` label

**With specific agent labels:**
- Runs that agent only
- No fallback
- Useful for testing or forcing a specific model

### 4. Automatic Retry

A scheduled job runs **every 30 minutes** and:
- Checks for issues labeled `rate-limited-all-agents`
- Clears expired rate limits (conservative 12-hour window)
- Automatically re-triggers the orchestrator
- Posts progress comments

## Rate Limit Detection

### ✅ Verified & Working

**Claude Code:**
```
Error: "You've hit your limit · resets 10am (America/Los_Angeles)"
```
- Extracts reset time
- Updates tracking file
- Falls back to Codex

**OpenAI Codex:**
```
Error: "You've hit your usage limit... try again at Dec 31st, 2025 11:51 PM"
```
- Extracts reset time
- Updates tracking file
- Falls back to Gemini

### ⚠️ Not Yet Verified

**Google Gemini:**
- Generic error detection (keywords: rate limit, quota, usage limit)
- Exact error format unknown - will update on first occurrence
- Currently treated as "possibly rate limited"

## Rate Limit Tracking

File: `.github/rate_limits.json`

```json
{
  "claude": {
    "limited": true,
    "reset_time": "10am (America/Los_Angeles)",
    "last_error": "Rate limited",
    "last_updated": "2026-01-01T18:35:00Z"
  },
  "codex": {
    "limited": false,
    "reset_time": null,
    "last_error": null,
    "last_updated": "2026-01-01T18:00:00Z"
  },
  "gemini": {
    "limited": false,
    "reset_time": null,
    "last_error": null,
    "last_updated": "2026-01-01T18:00:00Z"
  }
}
```

This file is automatically updated by the orchestrator and committed to the repo.

## Monitoring

### Check Current Status

```bash
# View rate limit file
cat .github/rate_limits.json | jq .

# List rate-limited issues
gh issue list --label "rate-limited-all-agents"

# View recent workflow runs
gh run list --limit 10
```

### Manual Retry

```bash
# Trigger retry workflow manually
gh workflow run agent-retry.yml
```

## Workflows

| File | Trigger | Purpose |
|------|---------|---------|
| `agent-orchestrator.yml` | Label: `agent-auto` | Smart multi-agent with fallback |
| `agent-task.yml` | Label: `agent-claude` | Claude Code only |
| `agent-task-codex.yml` | Label: `agent-codex` | OpenAI Codex only |
| `agent-task-gemini.yml` | Label: `agent-gemini` | Google Gemini only |
| `agent-retry.yml` | Cron: every 30min | Auto-retry rate-limited issues |

## Examples

### Successful Execution
```
🤖 Orchestrating multi-agent task for issue #42...
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
🔵 Attempting with Claude Code...
✅ Claude Code succeeded!
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
🎉 Task completed successfully using: Claude Code
```

### Fallback to Codex
```
🤖 Orchestrating multi-agent task for issue #43...
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
🔵 Attempting with Claude Code...
🚫 Claude Code rate limited (resets: 10am (America/Los_Angeles))
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
🔴 Attempting with OpenAI Codex...
✅ Codex succeeded!
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
🎉 Task completed successfully using: OpenAI Codex
```

### All Rate Limited (Auto-retry scheduled)
```
🤖 Orchestrating multi-agent task for issue #44...
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
🔵 Attempting with Claude Code...
🚫 Claude Code rate limited (resets: 10am (America/Los_Angeles))
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
🔴 Attempting with OpenAI Codex...
🚫 Codex rate limited (resets: Dec 31st, 2025 11:51 PM)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
🟢 Attempting with Google Gemini...
🚫 Gemini appears to be rate limited
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
❌ All agents failed or rate limited

Issue labeled 'rate-limited-all-agents' - will retry automatically
```

## Future Enhancements

### Planned (Need Verification)
- [ ] Parse Gemini rate limit error format (once observed)
- [ ] Precise reset time parsing for all agents
- [ ] Usage API integration for real-time metrics
- [ ] Dashboard with visual meters

### Possible (External Tools Needed)
- [ ] Menu bar app showing agent capacity
- [ ] Desktop notifications when limits reset
- [ ] Web dashboard with usage graphs

## Troubleshooting

**Issue not processing?**
- Check `.github/rate_limits.json` to see if all agents are limited
- Wait for next retry cycle (every 30 minutes)
- Manually trigger: `gh workflow run agent-retry.yml`

**Want to force a specific agent?**
- Use `agent-claude`, `agent-codex`, or `agent-gemini` instead of `agent-auto`

**Rate limit not clearing?**
- Current retry logic uses conservative 12-hour window
- Can manually edit `.github/rate_limits.json` and set `limited: false`
- Then trigger retry workflow
