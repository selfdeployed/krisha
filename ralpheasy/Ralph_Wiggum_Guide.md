# Running Ralph Wiggum the Right Way: A Complete Setup Guide

[Full Video Here](https://youtu.be/eAtvoGlpeRU)

⚫⚫⚫⚪⚪ Intermediate Difficulty | ⏱️ 20-30 Minutes Setup Time

This guide walks you through running Ralph Wiggum (or any long-running autonomous agent) safely, efficiently, and cost-effectively. There's a lot of hype about Ralph Wiggum in the AI coding community, and most people are getting it wrong. This guide covers both the official Claude Code plugin method and the original bash loop—and explains why one is significantly better than the other.

> 💡 **Note**: While this guide focuses on Claude Code, the bash loop method works with any CLI agent (Codex, Gemini, OpenCode, etc.) with minimal tweaks.

## Before You Begin

### What You'll Need

* Claude Code installed and configured
* A PRD or detailed plan for what you want to build
* Basic terminal/command line familiarity
* (Optional) Claude for Chrome or Playwright MCP for visual feedback

### What is Ralph Wiggum?

Ralph Wiggum is a way to run Claude Code (or any agent) in a continuous autonomous loop. It solves the common problem of agents finishing too early by forcing them to keep working and checking until the task is truly complete.

**Best used for:**
- Long-running tasks
- Projects where you already know what you want to build
- Tasks that benefit from continuous iteration without manual intervention

**Not ideal for:**
- Exploratory work without clear goals
- Quick one-off tasks
- Situations where you need frequent human input

### Important Notes

* This guide has been tested on macOS
* Always set max iterations to avoid runaway costs
* Sandbox your environment for safety
* The bash loop method is recommended over the Claude plugin for reasons explained below

## Part 1: The Foundation (Same for Both Methods)

Before touching Ralph Wiggum, you need to set up these foundational pieces. This prep work is essential regardless of which method you choose.

### Step 1: Enable Sandboxing

For long-running autonomous tasks, you want isolation without constant permission prompts. Boris Cherney from Anthropic recommends using the sandbox to avoid permission prompts so Claude can cook without being blocked.

Create or edit `.claude/settings.json` in your project. Here's the configuration I used for my project—yours will look different based on what permissions you need:

```json
{
  "env": {
    "XDG_CACHE_HOME": ".cache",
    "npm_config_cache": ".cache/npm",
    "PIP_CACHE_DIR": ".cache/pip"
  },
  "permissions": {
    "allow": [
      "WebFetch(domain:registry.npmjs.org)",
      "WebFetch(domain:github.com)",
      "mcp__playwright__*",
      "mcp__claude-in-chrome__*"
    ],
    "deny": [
      "Bash(sudo *)",
      "Bash(docker *)",
      "Read(./.env)",
      "Read(~/.ssh/**)",
      "Read(~/.aws/**)"
    ],
    "ask": [
      "Bash(git push:*)"
    ],
    "defaultMode": "acceptEdits"
  },
  "sandbox": {
    "enabled": true,
    "autoAllowBashIfSandboxed": true,
    "allowUnsandboxedCommands": false,
    "network": {
      "allowLocalBinding": true
    }
  }
}
```

Alternatively, run `/sandbox` in Claude Code to enable sandboxing interactively.

> ⚠️ **Important**: Everyone will set up their sandbox differently. Review the [Claude Code sandbox documentation](https://code.claude.com/docs/en/sandboxing) for full options.

### Step 2: Create Your PRD

Don't waste time and money running Ralph Wiggum on an unfleshed-out idea. Start with a comprehensive PRD.

If you need help creating a PRD, check out my [PRD Creator tutorial](https://www.youtube.com/watch?v=0seaP5YjXVM) and [PRD Creator custom instructions](https://github.com/JeredBlu/custom-instructions/blob/main/prd-creator-3-25.md).

### Step 3: Create plan.md

Based on [Anthropic's effective harnesses for long-running agents](https://www.anthropic.com/engineering/effective-harnesses-for-long-running-agents), structure your plan with tasks that can be marked as passing/failing.

Here's the format Anthropic recommends—each task is JSON with a category, description, steps, and a `passes` field:

```markdown
# Project Plan

## Overview
Brief description of what you're building.

**Reference:** `PRD.md`

---

## Task List

```json
[
  {
    "category": "setup",
    "description": "Initialize project structure and dependencies",
    "steps": [
      "Create project directory structure",
      "Initialize package.json or requirements",
      "Install required dependencies",
      "Verify files load correctly"
    ],
    "passes": false
  },
  {
    "category": "feature",
    "description": "Implement main navigation component",
    "steps": [
      "Create Navigation component",
      "Add responsive styling",
      "Implement mobile menu toggle"
    ],
    "passes": false
  },
  {
    "category": "feature",
    "description": "Implement hero section with CTA",
    "steps": [
      "Create Hero component",
      "Add headline and subhead",
      "Style CTA button",
      "Center content properly"
    ],
    "passes": false
  },
  {
    "category": "testing",
    "description": "Verify all components render correctly",
    "steps": [
      "Test responsive layouts",
      "Check console for errors",
      "Verify all links work"
    ],
    "passes": false
  }
]
```

---

## Agent Instructions

1. Read `activity.md` first to understand current state
2. Find next task with `"passes": false`
3. Complete all steps for that task
4. Verify in browser
5. Update task to `"passes": true`
6. Log completion in `activity.md`
7. Repeat until all tasks pass

**Important:** Only modify the `passes` field. Do not remove or rewrite tasks.

---

## Completion Criteria
All tasks marked with `"passes": true`
```

### Step 4: Create activity.md

This file logs what the agent accomplishes during each iteration:

```markdown
# Project Build - Activity Log

## Current Status
**Last Updated:** 
**Tasks Completed:** 
**Current Task:** 

---

## Session Log

<!-- Agent will append dated entries here -->
```

## Part 2: The Claude Code Plugin Method

### Installing the Plugin

1. Open Claude Code
2. Run `/plugin`
3. Navigate to **Discover**
4. Search for "Ralph" or scroll to find it
5. Press Enter to install

For more details, see the [official Ralph Wiggum plugin documentation](https://github.com/anthropics/claude-code/blob/main/plugins/ralph-wiggum/README.md).

### Running with the Plugin

Type `/ralph` and it will auto-complete to show several options. Select the one that says **"Ralph loop"** and press Tab:

```
/ralph → select "Ralph loop"
```

You'll then be prompted for your prompt, max iterations, and completion promise.

**Example Prompt:**

> ⚠️ **Note**: In the video I showed this prompt with line breaks, but Claude didn't like it—send it as one continuous block of text.

```
We are rebuilding the project from scratch in this repo. First read activity.md to see what was recently accomplished. Start the site locally and keep it localhost only. Use either: npm run dev (for Next or Vite) OR python3 -m http.server 8000 --bind 127.0.0.1 (for static HTML). Verify the current behavior in Claude in Chrome by opening the local URL and checking the page loads with no obvious layout issues. Then open plan.md and choose the single highest priority task whose Status is failing. Work on exactly one task: implement the change, run the linter or build check if available (npm run lint, npm run typecheck, or npm run build), and verify in Chrome again. Check the browser console for errors and confirm the change matches the acceptance criteria in plan.md. Append a dated progress entry to activity.md describing what you changed, which commands you ran, and what you verified in Chrome. When the task is confirmed, update that task Status in plan.md from failing to passing. Make one git commit for that task only with a clear single line message. Do not run git init, do not change git remotes, and do not push. Repeat until all tasks are passing. When all tasks are marked passing, output exactly COMPLETE.
```

```
Max Iterations: 20
Completion Promise: COMPLETE
```

### Why the Plugin Has Limitations

The Claude Code plugin runs everything in a **single context window**. This means:

- Context gets bloated over time
- More room for hallucination as context fills
- You may need to manually compact (I had to stop and do this in testing)
- Doesn't truly implement the "fresh loop" concept

The original Ralph Wiggum approach starts a **fresh context window** for each iteration, which is fundamentally better for long-running tasks.

## Part 3: The Bash Loop Method (Recommended)

This method works with Claude Code, Codex CLI, or any CLI agent. Each iteration runs in a fresh context window—this is the key difference.

### Step 1: Set Up Playwright MCP (for Headless Feedback)

Since the bash loop runs headless, use Playwright MCP instead of Claude for Chrome.

Create `.mcp.json` in your project root:

```json
{
  "mcpServers": {
    "playwright": {
      "command": "npx",
      "args": [
        "-y",
        "@playwright/mcp@latest",
        "--headless",
        "--output-dir",
        "."
      ]
    }
  }
}
```

### Step 2: Create PROMPT.md

Create a `PROMPT.md` file in your project root:

```markdown
@plan.md @activity.md

We are rebuilding the project from scratch in this repo.

First read activity.md to see what was recently accomplished.

Start the site locally with python3 -m http.server. If port is taken, try another port.

Open plan.md and choose the single highest priority task where passes is false.

Work on exactly ONE task: implement the change.

After implementing, use Playwright to:
1. Navigate to the local server URL
2. Take a screenshot and save it as screenshots/[task-name].png

Append a dated progress entry to activity.md describing what you changed and the screenshot filename.

Update that task's passes in plan.md from false to true.

Make one git commit for that task only with a clear message.

Do not git init, do not change remotes, do not push.

ONLY WORK ON A SINGLE TASK.

When ALL tasks have passes true, output <promise>COMPLETE</promise>
```

> 💡 **Tip**: The `@plan.md @activity.md` at the top uses Claude Code's file reference syntax to include those files in context.

### Step 3: Create ralph.sh

Create a `ralph.sh` script in your project root. This is the script I've been using—it's not the official way, just my approach:

```bash
#!/bin/bash

if [ -z "$1" ]; then
  echo "Usage: $0 <iterations>"
  exit 1
fi

for ((i=1; i<=$1; i++)); do
  echo "Iteration $i"
  echo "--------------------------------"
  
  result=$(claude -p "$(cat PROMPT.md)" --output-format text 2>&1) || true

  echo "$result"

  if [[ "$result" == *"<promise>COMPLETE</promise>"* ]]; then
    echo "All tasks complete after $i iterations."
    exit 0
  fi
  
  echo ""
  echo "--- End of iteration $i ---"
  echo ""
done

echo "Reached max iterations ($1)"
exit 1
```

### Step 4: Make the Script Executable

```bash
chmod +x ralph.sh
```

### Step 5: Create Screenshots Directory

```bash
mkdir screenshots
```

### Step 6: Run Ralph

```bash
./ralph.sh 20
```

The number (20) is your max iterations. Start with 10-20 for testing.

### Why This Method is Better

Each iteration runs in a **fresh context window**, which means:
- No context bloat
- Reduced hallucination risk
- Cleaner separation between tasks
- Better matches Anthropic's recommended approach for long-running agents

You can watch progress by monitoring:
- `activity.md` for logged updates
- `screenshots/` folder for visual verification
- Git commits for each completed task

## Part 4: Setting Up the Feedback Loop

The feedback loop is crucial—it lets the agent verify its own work. As Boris Cherney recommends: give it a feedback loop.

### Option A: Claude for Chrome (Plugin Method)

To use Claude for Chrome as your feedback loop:

1. Make sure you have Chrome installed
2. Run `/chrome` in Claude Code to enable the Claude for Chrome integration
3. Turn it on when prompted
4. The agent can now open URLs, take screenshots, and check console logs

### Option B: Playwright MCP (Bash Loop Method)

With Playwright configured, the agent can:
- Navigate to URLs headlessly
- Take screenshots (saved to your screenshots folder)
- Check console logs
- Interact with page elements

Screenshots let you visually verify what the agent is doing without watching it live.

## Troubleshooting

### Common Issues

1. **Agent gets stuck / infinite loop**
   - Ensure max iterations is set
   - Check that completion phrase is being output correctly
   - Review plan.md for ambiguous tasks

2. **Context window fills up (plugin method)**
   - Switch to bash loop method
   - Or manually compact and restart

3. **Playwright/Chrome not working**
   - Verify MCP server is configured correctly
   - Check that the local server is actually running
   - Review permissions in sandbox config

4. **Expensive runs**
   - Always set max iterations
   - Use 10-20 iterations for testing
   - Review costs before longer runs

5. **Port already in use**
   - The prompt handles this by telling the agent to try another port

### Best Practices

- **Always sandbox** for long-running autonomous tasks
- **Always set max iterations** - the plugin defaults to unlimited
- **Plan thoroughly** before running Ralph with a PRD and plan.md
- **Use the bash loop** for true iteration separation
- **Give feedback mechanisms** so the agent can verify its work
- **Monitor activity.md** and git commits to track progress

## Key Takeaways

1. **Safety**: Sandbox your environment
2. **Efficiency**: Plan thoroughly with a PRD and plan.md
3. **Cost Control**: Always set max iterations
4. **Validation**: Give the agent visual feedback (Chrome or Playwright)
5. **Method Choice**: Bash loop > Claude plugin for true fresh iterations

## Useful Links

* **Ralph Wiggum Plugin**: [GitHub - Official Plugin](https://github.com/anthropics/claude-code/blob/main/plugins/ralph-wiggum/README.md)
* **Original Ralph Wiggum**: [ghuntley.com/ralph](https://ghuntley.com/ralph/) by Geoffrey Huntley
* **Anthropic's Long-Running Agents**: [Effective Harnesses Blog Post](https://www.anthropic.com/engineering/effective-harnesses-for-long-running-agents)
* **Claude Code Sandbox Docs**: [code.claude.com/docs/en/sandboxing](https://code.claude.com/docs/en/sandboxing)
* **PRD Creator Tutorial**: [YouTube Video](https://www.youtube.com/watch?v=0seaP5YjXVM)
* **PRD Creator Instructions**: [GitHub](https://github.com/JeredBlu/custom-instructions/blob/main/prd-creator-3-25.md)

## Related Resources

* [Boris Cherney's Claude Code Post](https://x.com/bcherny/status/2007179858435281082)
* [My Video on Boris's Approach](https://youtu.be/S_pxMm0Qx7c)
* [Spec-Driven Development Video](https://youtu.be/wKx66sYyyUs)

---

## Contact

For more AI tools and tutorials, follow JeredBlu:
* Book a Call: [JeredBlu on Cal.com](https://cal.com/jeredblu)
* YouTube: [@JeredBlu](https://youtube.com/@JeredBlu)
* Twitter/X: [@JeredBlu](https://twitter.com/JeredBlu)
* Website: [jeredblu.com](https://jeredblu.com)
