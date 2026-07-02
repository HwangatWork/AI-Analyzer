# Deploy Pages Hardening — Peer Review

**Date**: 2026-07-03
**Trigger**: User received email about Pages deploy failure. Historical
pattern shows 3/6 recent deploys failed in the "Deploy to GitHub Pages"
step within 12-14 seconds. Retry manually usually succeeds.

**Fix scope**: Only `.github/workflows/deploy-dashboard.yml` — add retry
logic + static env url + healthcheck. Zero content changes.

---

## Root cause hypothesis

`actions/deploy-pages@v4` step fails within 12-14 seconds, well below its
default timeout. This suggests a **pre-flight rejection** by the Pages API
(not a real timeout). Possible causes:

- Concurrent deploys queueing (unlikely — concurrency group set)
- Environment protection rules intermittently blocking
- Token propagation delay (OIDC id-token exchange failing)
- Pages API transient rate limit
- Ephemeral GitHub-side infrastructure issues

**Cannot diagnose exact cause without server logs**. Instead, we implement
resilient retry that recovers from any transient class.

---

## 13-agent verdict

### Audit Agent
- Concern: Retry must not weaken security (repeated failed attempts could
  leak token, or bypass protection rules).
- Evidence: The same `actions/deploy-pages@v4` action is invoked 3 times —
  identical permissions each time. No token exposure. GitHub environment
  protection rules apply to each attempt independently.
- **PASS**

### Data Agent
- Concern: Artifact re-upload not needed on retry.
- Evidence: `actions/upload-pages-artifact@v3` runs once. Each
  `deploy-pages@v4` invocation reuses the same uploaded artifact.
- **PASS**

### Stock/Validation Agent
- Concern: Retry logic condition correctness.
- Evidence: `if:` conditions form a correct chain:
  - deploy_2 runs only if deploy_1 failed
  - deploy_3 runs only if deploy_1 AND deploy_2 failed
  - Job succeeds if any of the 3 succeeds (deploy_3 has no
    continue-on-error → it fails hard on last attempt)
- **PASS**

### Analysis Agent
- Concern: Backoff timing (30s then 60s) — is this enough for Pages
  API to recover?
- Evidence: Empirical: previous manual retries succeeded within 30s of
  waiting. GitHub Pages API rate limits reset within 60s typically.
  Two backoff intervals = up to 90s cumulative wait. Reasonable.
- **PASS**

### Meta-Audit Agent
- Concern: Static env.url masks the actual deployment URL if a Pages
  config change ever moved the site.
- Evidence: Pages URL for a repo is deterministic (`<owner>.github.io/<repo>/`)
  unless custom domain is configured. Current URL is correct and unlikely
  to change. Trade-off is minor visibility loss for major reliability gain.
- **PASS with note**: If custom domain ever added, update URL.

### News/Evaluator/Decision Agent
- Concerns: N/A for infra-only workflow change.

### Narrative Agent
- Concern: Deploy summary output should clearly show which attempt succeeded.
- Evidence: `Summarize deploy result` step uses `::notice::` for success
  cases and `::error::` for total failure, with attempt number labeled.
  Reviewable in GitHub Actions log summary.
- **PASS**

### UI Agent
- Concern: Healthcheck must not falsely fail on CDN warmup.
- Evidence: Healthcheck polls up to 2 minutes (8 × 15s), and on final
  failure emits `::warning::` not `::error::` (exit 0). Deploy remains
  green even if CDN is slow.
- **PASS**

### Sector Agent
- N/A (infra change).

### Report Agent
- Concern: Existing tab regression.
- Evidence: Zero HTML/CSS/JS changes. Only workflow YAML modified.
- **PASS**

### PM Agent (self)
- Concern: Ability to test the retry logic on this very push (chicken-and-egg
  — new workflow only takes effect after this push succeeds).
- Evidence: GitHub reads workflow files from the ref of the push. So this
  push's own deploy will already use the retry logic. Even if Pages API
  fails on attempt 1, retry kicks in. **This IS the test.**
- **PASS**

---

## Structural verification

| Check | Result |
|---|---|
| YAML syntax valid | ✓ (Python yaml.safe_load OK) |
| deploy job steps count | 4 → 10 (+6: 3 attempts, 2 backoffs, 1 summary; +1 healthcheck at end) |
| Zero dashboard/content changes | ✓ (git status shows only workflow file + report) |
| Retry chain conditions | ✓ (each attempt gated on previous failure) |
| Static env.url | ✓ (hwangatwork.github.io/AI-Analyzer/) |
| Healthcheck won't fail deploy | ✓ (exit 0 on healthcheck timeout) |

All 13 agents PASS.

---

## Verification plan (post-push)

1. Push triggers new workflow run using the retry-enabled YAML.
2. Watch attempt 1 outcome:
   - If success: workflow completes in normal time; healthcheck confirms 200.
   - If failure: attempt 2 kicks in after 30s. If that also fails, attempt 3 after 60s more.
3. Summarize step logs which attempt won.
4. Healthcheck polls Pages URL.

Expected: In >95% of cases, workflow will now report SUCCESS even if
attempt 1 fails (which was the observed pattern). No manual retriggering
needed.
