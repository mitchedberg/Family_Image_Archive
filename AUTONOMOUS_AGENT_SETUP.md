# Autonomous AI Agent Workflow - Complete Setup Guide

*Turn any GitHub repo into an autonomous development environment where AI agents implement features while you're away from your desk.*

## 📱 What This Gives You

**Traditional Workflow:**
- Write code manually at your desk
- Wait for tests to run while watching
- Context-switch between tasks
- Development tied to laptop availability

**Autonomous Agent Workflow:**
1. Create GitHub issue from your **phone** (anywhere, anytime)
2. Add `agent-task` label
3. **Walk away** - AI agent autonomously:
   - Analyzes the request
   - Creates feature branch
   - Writes code
   - Runs tests
   - Fixes failures automatically (up to 2 retries)
   - Creates pull request
   - Posts status updates
4. Get **phone notification** when done (2-10 minutes)
5. **Review from phone** or browser
6. **Merge** - changes go live
7. Pull updates when back at your desk

**Real example from this repo:**
- Issue created: "Add explosion shapes (circle, star, ring)"
- Agent implemented 3 pattern types with randomization
- Created PR with test plan
- CI passed
- Total time: 4 minutes (fully autonomous)

---

## 🎯 Use Cases

**What agents can do:**
- ✅ Implement features from clear specifications
- ✅ Fix bugs with stack traces
- ✅ Add tests for existing code
- ✅ Refactor code with clear goals
- ✅ Update documentation
- ✅ Add type annotations
- ✅ Optimize performance bottlenecks

**What to review (not auto-merge):**
- ⚠️ Security-sensitive changes
- ⚠️ Database migrations
- ⚠️ API contract changes
- ⚠️ Architectural decisions

---

## 📋 Prerequisites

**You need:**
- GitHub account with a repo (new or existing)
- Mac/Linux machine that can stay on (or run periodically)
- [Claude Code CLI](https://claude.com/claude-code) installed
- GitHub CLI: `brew install gh`
- Basic terminal comfort

**Cost:**
- **$0/month** if using Claude Code subscription (runs locally on your machine)
- ~$0.10-$0.50 per task if using Claude API (optional, for 24/7 cloud operation)

**Time investment:**
- Initial setup: 30 minutes (one-time)
- Per-repo setup: 10 minutes
- Daily usage: 30 seconds to create issue

---

## 🚀 Part 1: One-Time Runner Setup (30 min)

*This step sets up the "worker" that listens for tasks. Do once, works for all repos.*

### Step 1: Install GitHub Actions Self-Hosted Runner

**Why?** This lets GitHub Actions run on YOUR machine (not GitHub's cloud), so it can use your local Claude Code installation.

1. **Go to GitHub runner setup page:**
   - For single repo: `https://github.com/YOUR-USERNAME/YOUR-REPO/settings/actions/runners/new`
   - For all org repos: `https://github.com/organizations/YOUR-ORG/settings/actions/runners/new`

2. **Select your OS** (macOS or Linux)

3. **Copy and run the download commands** in terminal:

```bash
# Create runner directory
mkdir -p ~/actions-runner && cd ~/actions-runner

# Download (URL from GitHub page - copy exact command)
curl -o actions-runner-osx-arm64-2.XXX.X.tar.gz -L [COPY-URL-FROM-GITHUB]

# Extract
tar xzf ./actions-runner-osx-arm64-*.tar.gz
```

4. **Configure the runner** (copy token from GitHub page):

```bash
./config.sh --url https://github.com/YOUR-USERNAME/YOUR-REPO --token YOUR-TOKEN-FROM-GITHUB
```

Press Enter to accept defaults:
- Runner name: (default is fine, e.g., "MacBook-Air")
- Work folder: (default `_work` is fine)

5. **Start the runner:**

```bash
./run.sh
```

You should see:
```
✓ Connected to GitHub
Current runner version: '2.XXX.X'
Listening for Jobs
```

**✅ Success!** Leave this terminal window open.

6. **Keep it running permanently:**

**Option A - Simple (keep terminal open):**
- Pros: Easy, works immediately
- Cons: Stops if you close terminal

**Option B - Production (install as service):**
```bash
sudo ./svc.sh install
sudo ./svc.sh start
```
- Pros: Runs on boot, survives restarts
- Cons: Needs sudo permissions

---

### Step 2: Verify Claude Code Works

**Open a NEW terminal** (keep runner terminal running):

```bash
# 1. Verify Claude Code is installed
which claude
# Should output: /opt/homebrew/bin/claude (or similar)

# 2. Test non-interactive mode
claude -p "Say hello" --allowedTools "Read" --max-turns 1
# Should output a greeting

# 3. Test GitHub CLI is authenticated
gh auth status
# Should show: Logged in to github.com
```

**If all 3 work:** ✅ Your runner can execute autonomous agents

**If `gh auth status` fails:**
```bash
gh auth login
# Follow prompts, choose HTTPS or SSH
```

---

## 📦 Part 2: Per-Repo Setup (10 min)

*Add these files to enable agents in any repo.*

### Step 1: Create Agent Workflow File

In your repo root, create the directory and file:

```bash
mkdir -p .github/workflows
```

Create `.github/workflows/agent-task.yml` with this content:

```yaml
name: Agent Task

on:
  issues:
    types: [labeled]

permissions:
  contents: write
  issues: write
  pull-requests: write

jobs:
  implement:
    if: github.event.label.name == 'agent-task'
    runs-on: self-hosted

    steps:
      - name: Checkout code
        uses: actions/checkout@v3
        with:
          fetch-depth: 0
          token: ${{ secrets.GITHUB_TOKEN }}

      - name: Configure git
        run: |
          git config user.name "GitHub Actions Bot"
          git config user.email "actions@github.com"

      - name: Run Claude Code to implement
        run: |
          echo "Implementing issue #${{ github.event.issue.number }}..."
          claude -p "You are implementing GitHub issue #${{ github.event.issue.number }}: ${{ github.event.issue.title }}

          Issue description:
          ${{ github.event.issue.body }}

          Instructions:
          1. Create a feature branch named 'feature/issue-${{ github.event.issue.number }}'
          2. Implement the requested feature
          3. Commit your changes with a clear message
          4. Push the branch using: git push -u origin feature/issue-${{ github.event.issue.number }}
          5. Create a PR using gh CLI that references 'Closes #${{ github.event.issue.number }}'
          6. Wait for CI to complete by checking the PR status
          7. If CI fails, read the logs, fix the issue, and push again (max 2 retries)
          8. Post a status comment in the PR when done

          Work carefully and ensure CI passes before marking as ready for review." \
            --allowedTools "Read,Edit,Write,Bash,Glob,Grep,TodoWrite" \
            --max-turns 50

      - name: Verify PR was created
        run: |
          pr_count=$(gh pr list --repo ${{ github.repository }} --search "Closes #${{ github.event.issue.number }}" --json number --jq '. | length')
          if [ "$pr_count" -eq "0" ]; then
            echo "Error: No PR was created for issue #${{ github.event.issue.number }}"
            exit 1
          fi
          echo "✓ PR successfully created for issue #${{ github.event.issue.number }}"

      - name: Post completion comment
        if: always()
        uses: actions/github-script@v7
        with:
          github-token: ${{ secrets.GITHUB_TOKEN }}
          script: |
            const status = '${{ job.status }}' === 'success' ? '✅ Completed' : '❌ Failed';
            await github.rest.issues.createComment({
              issue_number: ${{ github.event.issue.number }},
              owner: context.repo.owner,
              repo: context.repo.repo,
              body: `${status}: Agent has finished processing this issue. Check for a new PR.`
            });
```

**Commit this file:**

```bash
git add .github/workflows/agent-task.yml
git commit -m "Add autonomous agent workflow"
git push
```

---

### Step 2: Create the Trigger Label

```bash
gh label create "agent-task" \
  --repo YOUR-USERNAME/YOUR-REPO \
  --color "0e8a16" \
  --description "Trigger autonomous agent to implement this issue"
```

---

### Step 3: (Recommended) Add CI Validation

Create `.github/workflows/ci.yml`:

```yaml
name: CI Validation

on:
  push:
    branches: [ main ]
  pull_request:
    branches: [ main ]

jobs:
  validate:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v3

      # Customize these for your project:

      - name: Run tests
        run: npm test
        # Or: pytest, cargo test, go test, etc.

      - name: Lint
        run: npm run lint
        # Or: eslint, flake8, clippy, golangci-lint, etc.

      - name: Type check
        run: npm run typecheck
        # Or: mypy, tsc --noEmit, etc.
```

**Commit:**
```bash
git add .github/workflows/ci.yml
git commit -m "Add CI validation"
git push
```

---

## ✅ Part 3: Test It Works (5 min)

### Smoke Test

1. **Create a test issue** (via GitHub web or mobile app):
   - Title: `Test autonomous agent`
   - Body:
     ```
     Add a comment to README.md that says:
     "This repository uses autonomous AI agents for development."
     ```

2. **Add the `agent-task` label** to the issue

3. **Watch the magic happen:**
   - Check your runner terminal - you'll see "Running job: implement"
   - Watch it work for 1-2 minutes
   - Get notification when done
   - Check GitHub - new PR should appear

4. **Review the PR:**
   - Open from phone or browser
   - See agent's changes
   - Review commit message
   - Check CI status (should be green)

5. **Merge it:**
   - Click "Merge pull request"

6. **Pull changes locally:**
   ```bash
   git pull
   cat README.md  # See the new comment
   ```

**✅ If this worked, you're fully operational!**

---

## 📱 Part 4: Daily Usage

### Creating Tasks (From Anywhere)

**From GitHub mobile app or web:**

1. **Create issue with clear requirements:**

Good example:
```
Title: Add user authentication

Body:
Implement JWT-based authentication with the following:
- POST /api/auth/login endpoint
- Accepts email + password
- Returns JWT token on success
- Token expires in 24 hours
- Add middleware to protect routes
- Include tests for auth flow
```

Bad example:
```
Title: Make it better
Body: Fix the auth stuff
```

2. **Add `agent-task` label**

3. **Walk away**

**The agent will:**
- Create feature branch
- Read existing code
- Implement the feature
- Write/update tests
- Create PR
- Run CI
- Fix failures if any (up to 2 auto-retries)
- Post status when done

**You'll get notification when PR is ready** (usually 2-10 minutes)

---

### Reviewing & Merging (From Phone)

**GitHub mobile app:**

1. Open notification → View PR
2. Review changes in Files tab
3. Read agent's description & test plan
4. Check CI status (must be green)
5. Tap "Merge pull request"

**When back at desk:**
```bash
git pull
# Test locally if needed
```

---

## 🎛️ Part 5: Configuration Options

### Adjust Complexity Limits

In `.github/workflows/agent-task.yml`, change `--max-turns`:

```yaml
--max-turns 50  # Default - good for most tasks
--max-turns 20  # Simple tasks (docs, typos)
--max-turns 100 # Complex refactors
```

More turns = agent can handle more complex tasks, but costs more time/tokens.

---

### Enable Auto-Merge for Trusted Tasks

Add this step **before** "Post completion comment":

```yaml
      - name: Auto-merge if safe
        if: |
          contains(github.event.issue.labels.*.name, 'auto-merge') &&
          success()
        run: |
          pr_number=$(gh pr list --search "Closes #${{ github.event.issue.number }}" --json number --jq '.[0].number')
          gh pr merge $pr_number --merge --delete-branch
```

Now issues with **both** `agent-task` + `auto-merge` labels will merge automatically if CI passes.

**Use for:**
- Documentation updates
- Typo fixes
- Dependency updates
- Test additions

**Don't use for:**
- New features (review first)
- Security changes
- API changes

---

### Multi-Repo Setup (Organization-Wide)

Instead of installing runner per-repo:

1. Go to: `https://github.com/organizations/YOUR-ORG/settings/actions/runners/new`
2. Follow same setup process
3. Now **ALL org repos** can use the same runner
4. Just add workflow file + label to each repo

---

### Customize Agent Instructions

Edit the prompt in `.github/workflows/agent-task.yml`:

**For backend projects:**
```yaml
claude -p "You are implementing GitHub issue #...

Additional context:
- This is a Node.js/Express API
- Follow REST best practices
- Add OpenAPI/Swagger docs
- Use async/await (not callbacks)
- Write integration tests with supertest

[rest of instructions...]"
```

**For frontend projects:**
```yaml
claude -p "You are implementing GitHub issue #...

Additional context:
- This is a React TypeScript project
- Use functional components with hooks
- Follow Material-UI design system
- Write tests with React Testing Library
- Ensure accessibility (ARIA labels)

[rest of instructions...]"
```

---

## 🔧 Part 6: Troubleshooting

### Runner not picking up jobs

**Check runner status:**
```bash
cd ~/actions-runner
./run.sh
```

Should show: `Listening for Jobs`

**If not working:**
1. Restart runner: Ctrl+C, then `./run.sh`
2. Re-configure: `./config.sh --url YOUR-REPO-URL --token NEW-TOKEN`
3. Check GitHub repo → Settings → Actions → Runners (should show "Active")

---

### Agent creates PR but CI fails repeatedly

**Check workflow logs:**
- Go to repo → Actions tab → Click failed run
- Look for error messages

**Common fixes:**
- **Timeout:** Increase `--max-turns` in workflow
- **Missing dependencies:** Add install step to CI workflow
- **Permissions:** Check agent has write access to repo

---

### Multiple agents create conflicting PRs

**This is normal** when running parallel tasks on same file.

**To fix:**
1. Merge one PR first
2. For conflicting PRs, either:
   - **Option A:** Close PR, remove + re-add `agent-task` label (agent will recreate based on latest main)
   - **Option B:** Manually rebase:
     ```bash
     gh pr checkout NUMBER
     git rebase main
     git push --force-with-lease
     ```

**To prevent:** Add tasks sequentially instead of in parallel.

---

### Agent gets stuck or runs too long

**Safety limits:**
- Default `--max-turns 50` prevents runaway costs
- Workflow timeout: 6 hours max (GitHub default)

**If agent stops mid-task:**
- Check turn limit - complex tasks need more turns
- Check error logs in Actions tab
- Re-run by removing + re-adding `agent-task` label

---

## 🔒 Part 7: Security & Best Practices

### DO ✅

- Review AI-generated code before merging (especially security-sensitive changes)
- Use branch protection rules (require PR reviews)
- Set `--max-turns` limits to prevent runaway execution
- Keep runner machine secure (regular updates, firewall)
- Use CI validation on all PRs
- Monitor runner resource usage (CPU, disk)

### DON'T ❌

- Auto-merge without CI validation
- Give agents production deployment permissions (start with staging only)
- Run public repo runners on untrusted issues
- Commit secrets/credentials to repo
- Share runner registration tokens publicly

### Recommended Branch Protection

Settings → Branches → Add rule for `main`:
- ✅ Require pull request before merging
- ✅ Require status checks to pass (CI validation)
- ✅ Require branches to be up to date
- Optional: Require approvals (for team repos)

---

## 📊 Part 8: Monitoring & Analytics

### Track Agent Performance

Create `.github/workflows/metrics.yml`:

```yaml
name: Agent Metrics

on:
  pull_request:
    types: [closed]

jobs:
  track:
    if: github.event.pull_request.merged == true
    runs-on: ubuntu-latest
    steps:
      - name: Log metrics
        run: |
          echo "PR #${{ github.event.pull_request.number }} merged"
          echo "Files changed: ${{ github.event.pull_request.changed_files }}"
          echo "Lines added: ${{ github.event.pull_request.additions }}"
          echo "Lines deleted: ${{ github.event.pull_request.deletions }}"
          # Send to analytics platform, Slack, etc.
```

### Monitor Costs (if using API instead of local)

```bash
# Track monthly usage
echo "$(date): Task completed, cost ~$0.10" >> ~/agent-costs.log

# Monthly summary
grep "$(date +%Y-%m)" ~/agent-costs.log | wc -l
```

---

## 🚀 Part 9: Advanced Use Cases

### Multi-Model Routing

Route tasks to different AI models based on complexity:

```yaml
- name: Select model based on complexity
  id: route
  run: |
    # Simple heuristic - customize for your needs
    if [[ "${{ github.event.issue.title }}" == *"docs"* ]]; then
      echo "model=haiku" >> $GITHUB_OUTPUT
    elif [[ "${{ github.event.issue.title }}" == *"refactor"* ]]; then
      echo "model=opus" >> $GITHUB_OUTPUT
    else
      echo "model=sonnet" >> $GITHUB_OUTPUT
    fi

- name: Run with selected model
  run: |
    claude -p "..." --model ${{ steps.route.outputs.model }}
```

### Email-Driven Development

Use Zapier/n8n to forward emails → create issues:

1. Email to: `agent@yourproject.com`
2. Zapier creates GitHub issue with email body
3. Auto-adds `agent-task` label
4. Agent implements
5. Email notification when done

### Slack Integration

Add to workflow:

```yaml
- name: Notify Slack
  if: always()
  env:
    SLACK_WEBHOOK: ${{ secrets.SLACK_WEBHOOK }}
  run: |
    status="${{ job.status }}"
    curl -X POST $SLACK_WEBHOOK -d "{
      \"text\": \"Agent finished issue #${{ github.event.issue.number }}: $status\"
    }"
```

---

## 📚 Reference

### Issue Label Guide

Create these labels for better control:

| Label | Purpose | Auto-Merge? |
|-------|---------|-------------|
| `agent-task` | Trigger agent (required) | No |
| `auto-merge` | Merge if CI passes | Yes |
| `simple` | Low complexity (20 turns) | Optional |
| `complex` | High complexity (100 turns) | No |
| `urgent` | Prioritize this task | No |

### Cost Estimation (if using API)

| Task Complexity | Turns | API Cost | Time |
|----------------|-------|----------|------|
| Typo/docs fix | 5-10 | $0.01 | 30s |
| Add function | 20-30 | $0.10 | 2min |
| Implement feature | 40-60 | $0.30 | 5min |
| Complex refactor | 80-120 | $1.00 | 10min |

*Costs are for Claude Sonnet. Local execution with Claude Code subscription = $0*

### Quick Commands

```bash
# Check runner status
cd ~/actions-runner && ./run.sh

# Create agent label
gh label create "agent-task" --color "0e8a16"

# View workflow logs
gh run list
gh run view RUN-ID --log

# List agent-created PRs
gh pr list --label "agent-task"

# Pull all agent changes
git pull --all
```

---

## 🎓 Learning Resources

**Understanding the Stack:**
- [GitHub Actions](https://docs.github.com/en/actions)
- [Self-hosted runners](https://docs.github.com/en/actions/hosting-your-own-runners)
- [Claude Code CLI](https://code.claude.com)

**Example Repos:**
- This repo: Working autonomous fireworks implementation
- [Your other repos using this pattern]

**Community:**
- [GitHub Discussions for this repo]
- [Discord/Slack for questions]

---

## 🆘 Getting Help

**If something doesn't work:**

1. **Check runner is running:** `cd ~/actions-runner && ./run.sh`
2. **Check workflow logs:** Repo → Actions tab → View failed run
3. **Verify permissions:** Repo → Settings → Actions → General → Workflow permissions (should be Read & Write)
4. **Test Claude Code:** `claude -p "test" --max-turns 1`
5. **Check label exists:** Repo → Issues → Labels (should see `agent-task`)

**Still stuck?**
- Open issue in this repo with error logs
- Include: OS, Claude Code version, error message

---

## 🎉 You're Done!

**What you built:**
- ✅ Autonomous AI development workflow
- ✅ Phone-first task management
- ✅ Automated code review pipeline
- ✅ CI validation enforcement
- ✅ Zero-cost local execution

**What's possible now:**
- Create issues from anywhere (phone, email, Slack)
- Agents work while you sleep/commute/vacation
- Review code from phone in spare moments
- Scale development without hiring
- Focus on strategy, let agents handle implementation

**Next steps:**
1. Try 5-10 real tasks to build confidence
2. Customize workflow for your team's needs
3. Add integrations (Slack, Jira, etc.)
4. Share this guide with your team
5. Scale to multiple repos

---

**Welcome to autonomous development. The future is here.** 🚀

---

*Generated from working implementation: https://github.com/mitchedberg/fireworks*

*Questions? Found a bug in this guide? Open an issue!*
