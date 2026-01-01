# Autonomous AI Agent Workflow - Complete Setup Guide (BATTLE-TESTED)

*Turn any GitHub repo into an autonomous development environment where AI agents implement features while you're away from your desk.*

**✨ This version includes critical fixes discovered during real-world implementation.**

---

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
   - Fixes failures automatically
   - Creates pull request
   - Posts status updates
4. Get **phone notification** when done (5-30 minutes)
5. **Review from phone** or browser
6. **Merge** - changes go live
7. Pull updates when back at your desk

**Real example from testing:**
- Issue created: "Extract base store classes for CSV and JSON stores"
- Agent created 2 base classes, refactored existing code, wrote 15 unit tests
- Created PR with full test report
- All tests passing
- Total time: 15 minutes (fully autonomous)

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
- ✅ Remove deprecated code
- ✅ Extract duplicate logic

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
- [Claude Code CLI](https://claude.com/claude-code) installed **and logged in**
- GitHub CLI: `brew install gh`
- Basic terminal comfort

**Cost:**
- **$0/month** if using Claude Code subscription (runs locally on your machine)
- No API costs with self-hosted runner

**Time investment:**
- Initial setup: 30-45 minutes (one-time)
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

5. **Create startup script:**

```bash
cat > ~/actions-runner/start-runner.sh << 'EOF'
#!/bin/bash
# Startup script for GitHub Actions Runner

cd ~/actions-runner
nohup ./run.sh > ~/runner.log 2>&1 &

echo "Runner started in background"
echo "Check status: tail -f ~/runner.log"
EOF

chmod +x ~/actions-runner/start-runner.sh
```

6. **Start the runner:**

```bash
~/actions-runner/start-runner.sh
```

Wait 3 seconds, then verify:
```bash
tail ~/runner.log
```

You should see:
```
✓ Connected to GitHub
Current runner version: '2.XXX.X'
Listening for Jobs
```

**✅ Success!** The runner is now running in the background.

---

### 🚨 CRITICAL: Why Not Use Service Mode

**❌ DO NOT use `./svc.sh install`** (despite what GitHub's official docs say)

**Why?** The service runs in a clean environment without access to:
- macOS Keychain (where Claude Code stores credentials)
- Your user's environment variables
- Login session context

**Result:** You'll get `Invalid API key · Please run /login` errors

**✅ Use nohup instead** (what we're doing above):
- Runs in your user context
- Has access to Claude Code credentials
- Works reliably

**To make it start on login:**
1. Open **System Settings** → **General** → **Login Items**
2. Click the **+** button
3. Navigate to `~/actions-runner/start-runner.sh`
4. Add it to the list

---

### Step 2: Verify Claude Code Works

**Open a NEW terminal**:

```bash
# 1. Verify Claude Code is installed
which claude
# Should output: /opt/homebrew/bin/claude (or similar)

# 2. Verify you're logged in
claude -p "Say hello" --allowedTools "Read" --max-turns 1
# Should output a greeting (NOT "Invalid API key")

# 3. Test GitHub CLI is authenticated
gh auth status
# Should show: Logged in to github.com
```

**If Claude says "Invalid API key":**
```bash
claude login
# Follow prompts to authenticate
```

**If `gh auth status` fails:**
```bash
gh auth login
# Follow prompts, choose HTTPS or SSH
```

**If all 3 work:** ✅ Your runner can execute autonomous agents

---

### Step 3: Create Monitoring Tools

These scripts help you track agent progress:

```bash
# Status checker
cat > ~/check-agent-status.sh << 'EOF'
#!/bin/bash
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "🤖 AUTONOMOUS AGENT STATUS"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""
echo "📋 RECENT WORKFLOWS:"
gh run list --repo YOUR-USERNAME/YOUR-REPO --limit 10
echo ""
echo "📝 OPEN PULL REQUESTS:"
gh pr list --repo YOUR-USERNAME/YOUR-REPO --limit 5
echo ""
echo "🏃 RUNNER STATUS:"
if pgrep -f "Runner.Listener" > /dev/null; then
  echo "✅ Runner is ACTIVE"
  tail -3 ~/runner.log 2>/dev/null | grep -E "(Listening|Running)"
else
  echo "❌ Runner is OFFLINE"
fi
EOF

chmod +x ~/check-agent-status.sh

# Test it
~/check-agent-status.sh
```

**💡 Update** `YOUR-USERNAME/YOUR-REPO` in the script above to your actual repo path!

---

## 📦 Part 2: Per-Repo Setup (10 min)

*Add these files to enable agents in any repo.*

### Step 1: Create Agent Workflow File

In your repo root:

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
        env:
          ISSUE_BODY: ${{ github.event.issue.body }}
          ISSUE_TITLE: ${{ github.event.issue.title }}
          ISSUE_NUMBER: ${{ github.event.issue.number }}
        run: |
          echo "Implementing issue #${ISSUE_NUMBER}..."

          # Write issue body to temp file safely (prevents shell injection)
          printf '%s' "$ISSUE_BODY" > /tmp/issue_body.txt

          # Build the prompt using printf to avoid shell interpretation
          printf '%s\n' \
            "You are implementing GitHub issue #${ISSUE_NUMBER}: ${ISSUE_TITLE}" \
            "" \
            "Issue description:" \
            "$(cat /tmp/issue_body.txt)" \
            "" \
            "Instructions:" \
            "1. Create a feature branch named 'feature/issue-${ISSUE_NUMBER}'" \
            "2. Implement the requested feature/refactoring exactly as described" \
            "3. Commit your changes with a clear, descriptive message" \
            "4. Push the branch using: git push -u origin feature/issue-${ISSUE_NUMBER}" \
            "5. Create a PR using gh CLI that references 'Closes #${ISSUE_NUMBER}'" \
            "6. If there are tests, run them and ensure they pass" \
            "7. If tests or checks fail, read the logs, fix the issue, and push again (max 2 retries)" \
            "8. Post a brief status comment in the PR when done" \
            "" \
            "Work carefully and ensure all validation passes before marking as ready for review." \
            > /tmp/full_prompt.txt

          # Run claude with the prompt file (NO turn limit for self-hosted)
          claude -p "$(cat /tmp/full_prompt.txt)" \
            --allowedTools "Read,Edit,Write,Bash,Glob,Grep,TodoWrite"

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

**🔥 CRITICAL FIXES in this workflow:**

1. **Environment Variables for User Input** (lines 36-38)
   - ✅ Prevents shell command injection
   - ❌ Original docs inline `${{ github.event.issue.body }}` directly → security issue

2. **Temp Files for Complex Strings** (lines 42-63)
   - ✅ Handles code blocks, special chars, multiline content safely
   - ❌ Original approach executes code examples as shell commands

3. **NO Turn Limit** (line 66)
   - ✅ Self-hosted = zero API costs, let agent work until done
   - ❌ Original has `--max-turns 50` which artificially limits complex work

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

### Step 3: (Optional but Recommended) Add CI Validation

If you have tests, create `.github/workflows/ci.yml`:

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
     ```markdown
     ## Goal
     Add a comment to README.md

     ## Tasks
     Add the following comment at the top of README.md:
     ```
     <!-- This repository uses autonomous AI agents for development -->
     ```

     ## Success Criteria
     - ✅ Comment added to README.md
     - ✅ File still valid markdown
     - ✅ PR created with clear commit message
     ```

2. **Add the `agent-task` label** to the issue

3. **Watch the magic happen:**
   ```bash
   # In terminal, watch runner logs
   tail -f ~/runner.log

   # Or check status
   ~/check-agent-status.sh
   ```

4. **You should see:**
   - Runner picks up job (within 10 seconds)
   - "Running job: implement" in logs
   - Job completes (1-3 minutes)
   - New PR appears on GitHub

5. **Review the PR:**
   - Open from GitHub (phone or browser)
   - See agent's changes
   - Review commit message
   - Check if CI passed (if you set it up)

6. **Merge it:**
   - Click "Merge pull request"

7. **Pull changes locally:**
   ```bash
   git pull
   cat README.md  # See the new comment
   ```

**✅ If this worked, you're fully operational!**

---

## 🚨 Troubleshooting

### Workflow Didn't Trigger

**Symptoms:**
- Issue has `agent-task` label
- No workflow run appears in Actions tab

**Causes & Fixes:**
1. **Label was added before workflow file was pushed**
   - Workflows only trigger on label ADD events
   - Remove label, wait 2 seconds, re-add label

2. **Workflow syntax error**
   - Check `.github/workflows/agent-task.yml` for typos
   - Validate YAML: https://www.yamllint.com/

3. **Permissions issue**
   - Go to repo Settings → Actions → General
   - Set "Workflow permissions" to "Read and write permissions"

**Quick fix:**
```bash
# Remove and re-add label to retrigger
gh issue edit ISSUE_NUMBER --remove-label "agent-task"
sleep 2
gh issue edit ISSUE_NUMBER --add-label "agent-task"
```

---

### Runner Shows Offline

**Symptoms:**
```bash
gh api repos/USER/REPO/actions/runners
# Shows: "status": "offline"
```

**Diagnose:**
```bash
# Check if running
ps aux | grep Runner.Listener

# Check logs
tail -50 ~/runner.log
```

**Fixes:**

1. **Not running:**
   ```bash
   ~/actions-runner/start-runner.sh
   ```

2. **Signature error:**
   ```
   Runner connect error: The signature is not valid
   ```
   Restart runner:
   ```bash
   pkill -f "Runner.Listener"
   ~/actions-runner/start-runner.sh
   ```

3. **Session conflict:**
   ```
   A session for this runner already exists
   ```
   Kill all instances:
   ```bash
   pkill -f "Runner.Listener"
   sleep 2
   ~/actions-runner/start-runner.sh
   ```

---

### Claude Authentication Fails

**Symptoms:**
```
Invalid API key · Please run /login
```

**This means:** Runner doesn't have access to Claude credentials

**Fixes:**

1. **Verify you're using nohup, not service:**
   ```bash
   # Check if service is running (BAD)
   cd ~/actions-runner
   ./svc.sh status

   # If it says "Started", stop and uninstall it:
   ./svc.sh stop
   ./svc.sh uninstall

   # Start with nohup instead (GOOD)
   ~/actions-runner/start-runner.sh
   ```

2. **Verify Claude is logged in:**
   ```bash
   claude -p "test" --max-turns 1
   # Should work without "Invalid API key" error

   # If it fails:
   claude login
   ```

3. **Retrigger workflow** (after fixing):
   ```bash
   gh issue edit ISSUE_NUMBER --remove-label "agent-task"
   sleep 2
   gh issue edit ISSUE_NUMBER --add-label "agent-task"
   ```

---

### Job Fails with "command not found"

**Symptoms:**
```
decisions.py: command not found
BaseCSVStore: command not found
```

**This means:** Shell is trying to execute issue body as commands

**Cause:** You're using the OLD workflow file (without environment variable fix)

**Fix:** Update `.github/workflows/agent-task.yml` to use the corrected version above (with `env:` and temp files)

---

## 📱 Part 4: Daily Usage

### Creating Tasks (From Anywhere)

**From GitHub mobile app or web:**

#### ✅ Good Issue Example:
```markdown
Title: Extract database connection logic into utility

## Goal
Create a reusable database utility to reduce code duplication

## Current State
Database connection code is duplicated in:
- `src/api/users.js` (lines 10-25)
- `src/api/posts.js` (lines 8-23)
- `src/api/auth.js` (lines 15-30)

## Tasks
1. Create `src/utils/db.js`
2. Extract connection logic
3. Add error handling
4. Update all 3 files to use new utility
5. Add unit tests for db utility

## Success Criteria
- ✅ `src/utils/db.js` exists
- ✅ All 3 files use the utility
- ✅ No code duplication
- ✅ Tests pass: `npm test`
- ✅ No functionality changes

## Validation
bash
npm test
node -e "require('./src/utils/db'); console.log('✓ Import works')"
```

#### ❌ Bad Issue Example:
```markdown
Title: Fix the database stuff

Body: The database code is messy, clean it up
```

**Why the good example works:**
- Clear goal (one sentence)
- Specific file paths
- Step-by-step tasks
- Success criteria checklist
- Validation commands

**Why the bad example fails:**
- Vague goal
- No specifics
- Agent has to guess
- No validation

---

### Reviewing & Merging (From Phone)

**GitHub mobile app:**

1. Get notification → Open PR
2. Review "Files changed" tab
3. Read agent's description
4. Check CI status (if exists)
5. Tap "Merge pull request"

**When back at desk:**
```bash
git pull
# Test locally if needed
```

---

## 🎛️ Part 5: Advanced Configuration

### Adjust Task Complexity

**Simple tasks (docs, typos):**
- Use clear, simple issue descriptions
- Agent typically completes in 2-5 minutes

**Complex tasks (refactoring):**
- Break into smaller focused issues
- Provide detailed specifications
- May take 15-30 minutes
- With NO turn limit, agent can handle it!

---

### Enable Auto-Merge for Safe Tasks

Add this step to workflow **before** "Post completion comment":

```yaml
      - name: Auto-merge if safe
        if: |
          contains(github.event.issue.labels.*.name, 'auto-merge') &&
          success()
        run: |
          pr_number=$(gh pr list --search "Closes #${{ github.event.issue.number }}" --json number --jq '.[0].number')
          gh pr merge $pr_number --merge --delete-branch
```

Create the label:
```bash
gh label create "auto-merge" \
  --color "0e8a16" \
  --description "Auto-merge if CI passes"
```

Now issues with **both** `agent-task` + `auto-merge` labels will merge automatically if CI passes.

**Use for:**
- Documentation updates
- Typo fixes
- Test additions

**Don't use for:**
- New features (review first)
- Security changes
- API changes

---

### Multi-Repo Setup

Instead of per-repo runner:

1. Go to: `https://github.com/organizations/YOUR-ORG/settings/actions/runners/new`
2. Follow same setup process
3. Now **ALL org repos** can use the same runner
4. Just add workflow file + label to each repo

---

## 🔒 Security & Best Practices

### DO ✅

- Review AI-generated code before merging
- Use branch protection rules (require PR reviews)
- Keep runner machine secure (regular updates, firewall)
- Use CI validation on all PRs
- Monitor runner resource usage
- Write detailed issue specifications

### DON'T ❌

- Auto-merge without CI validation
- Give agents production deployment permissions
- Run public repo runners on untrusted issues
- Commit secrets/credentials to repo
- Share runner registration tokens publicly
- Use vague issue descriptions

---

## 📊 What to Expect

**Completion Times (Real-World Data):**
- Simple cleanup (delete files): 3-5 minutes
- Medium refactoring (extract module): 8-12 minutes
- Complex refactoring (base classes + tests): 15-30 minutes

**Quality:**
- Agents write comprehensive unit tests
- Follow existing code patterns
- Add proper documentation
- Create detailed PR descriptions
- **100% success rate with good issue specs**

**What Agents Excel At:**
- Refactoring with clear goals
- Extracting duplicate code
- Writing tests
- Following specifications exactly
- Being thorough

**What Needs Human Review:**
- Architectural decisions
- Security-sensitive changes
- Performance optimizations
- User-facing changes

---

## 🎓 Pro Tips

### Writing Great Issues

**Template:**
```markdown
## Goal
[One sentence objective]

## Current State
[What exists today - be specific]

## Tasks
1. [Specific step with file paths]
2. [Another specific step]
3. [etc.]

## Success Criteria
- ✅ [Measurable outcome]
- ✅ [Another outcome]
- ✅ Tests pass: `[exact command]`

## Validation
bash
[Exact commands to verify it works]
```

**Notes:**
[Constraints, things to avoid, important context]
```

### Monitoring

**Check status anytime:**
```bash
~/check-agent-status.sh
```

**Watch live:**
```bash
tail -f ~/runner.log
```

**Web dashboard:**
```
https://github.com/YOUR-USERNAME/YOUR-REPO/actions
```

### Retry Failed Workflows

If a workflow fails and you fix the issue:

```bash
# Retrigger by removing/adding label
gh issue edit ISSUE_NUM --remove-label "agent-task"
sleep 2
gh issue edit ISSUE_NUM --add-label "agent-task"
```

---

## 🆘 Getting Help

**If something doesn't work:**

1. **Check runner is running:**
   ```bash
   ps aux | grep Runner.Listener
   tail ~/runner.log
   ```

2. **Check workflow logs:**
   - Repo → Actions tab → Click failed run

3. **Verify permissions:**
   - Repo → Settings → Actions → General
   - "Workflow permissions" should be "Read & Write"

4. **Test Claude Code:**
   ```bash
   claude -p "test" --max-turns 1
   ```

5. **Check label exists:**
   - Repo → Issues → Labels (should see `agent-task`)

6. **Retrigger workflow:**
   - Remove and re-add `agent-task` label

---

## 🎉 You're Done!

**What you built:**
- ✅ Autonomous AI development workflow
- ✅ Phone-first task management
- ✅ Automated code review pipeline
- ✅ Zero-cost local execution
- ✅ Production-quality code generation

**What's possible now:**
- Create issues from anywhere (phone, email, Slack)
- Agents work while you sleep/commute/vacation
- Review code from phone in spare moments
- Scale development without hiring
- Focus on strategy, let agents handle implementation

**Next steps:**
1. Create a few real tasks to build confidence
2. Review and merge the PRs
3. Refine your issue-writing skills
4. Build a backlog of agent-ready tasks
5. Enjoy your new superpower! 🚀

---

**Welcome to autonomous development. The future is here.**

---

## 📝 Changelog

**v2.0 - Battle-Tested Updates:**
- ❌ Removed service mode installation (credentials issue)
- ✅ Added nohup background process method
- ✅ Fixed shell escaping vulnerability in workflow
- ✅ Removed turn limits for self-hosted runners
- ✅ Added comprehensive troubleshooting
- ✅ Added monitoring tools
- ✅ Added real-world performance data
- ✅ Updated with production-tested practices

**Tested with:**
- 7 autonomous refactoring tasks
- 100% success rate after setup
- Average 15-minute completion time
- Production-quality code with tests

---

*This guide was refined through real-world implementation and debugging. All fixes are battle-tested.*
