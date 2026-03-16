# Phase 3: Cloud Run Timeout Extension

**Files:** `.github/workflows/deploy.yml`, `CLAUDE.md`
**Batch:** [batch-eligible] — no file overlap with phases 1 or 2

## Overview

Add `--timeout=900` (15 minutes) to Cloud Run deployment to match Gemini Live's session duration limit. Without this, Cloud Run's default timeout may terminate the WebSocket before the Gemini session naturally expires.

## Changes

### 1. GitHub Actions workflow (`.github/workflows/deploy.yml`, line 32-39)

Add `--timeout=900` to the `gcloud run deploy` command:

```yaml
# BEFORE:
gcloud run deploy seasussed-backend \
  --source backend/ \
  --region us-central1 \
  --project seasussed-489008 \
  --allow-unauthenticated \
  --memory 1Gi \
  --min-instances 1 \
  --set-env-vars ...

# AFTER (add one line):
gcloud run deploy seasussed-backend \
  --source backend/ \
  --region us-central1 \
  --project seasussed-489008 \
  --allow-unauthenticated \
  --memory 1Gi \
  --min-instances 1 \
  --timeout=900 \
  --set-env-vars ...
```

### 2. CLAUDE.md deploy command (line ~31)

Update the reference deployment command to include `--timeout=900`:

```bash
gcloud run deploy seasussed-backend \
  --source backend/ \
  --region us-central1 \
  --allow-unauthenticated \
  --memory 1Gi \
  --min-instances 1 \
  --timeout=900 \
  --set-env-vars ...
```

## Success Criteria

### Automated
- `deploy.yml` contains `--timeout=900`
- `CLAUDE.md` deploy command contains `--timeout=900`

### Manual
- After deploy: `gcloud run services describe seasussed-backend --region us-central1 --format='value(spec.template.spec.timeoutSeconds)'` returns `900`
