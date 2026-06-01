# Phase 0 — Runbook & Handoff

Manual prerequisites you run **once**, then hand the values in [§ Handoff to Phase 1](#handoff-to-phase-1) to Claude to scaffold and run Phase 1. Companion to the [implementation plan](implementation-plan.md).

> GitHub org is `kg-aifabrik`. All commands are idempotent-ish; re-running mostly errors harmlessly if a resource exists.

```bash
# ---- variables ----
export PROJECT_ID="k8s-iac-poc"
export PROJECT_NUMBER="783778742587"
export REGION="us-central1"
export STATE_BUCKET="gs://${PROJECT_ID}-tfstate"
export BILLING_ACCOUNT="00194B-D8781C-58A140"
export GH_REPO="kg-aifabrik/iac-gke-poc"        # Terraform/workflows repo
export SA_NAME="k8s-iac-poc-ci"
```

### 1. Project + billing
```bash
gcloud projects create "$PROJECT_ID"
gcloud billing projects link "$PROJECT_ID" --billing-account="$BILLING_ACCOUNT"
gcloud config set project "$PROJECT_ID"
export PROJECT_NUMBER=$(gcloud projects describe "$PROJECT_ID" --format='value(projectNumber)')
```

### 2. Enable APIs (incl. WIF deps: sts, iamcredentials)
```bash
gcloud services enable \
  container.googleapis.com compute.googleapis.com iam.googleapis.com \
  cloudkms.googleapis.com cloudresourcemanager.googleapis.com \
  iamcredentials.googleapis.com sts.googleapis.com --project "$PROJECT_ID"
```

### 3. Terraform state bucket
```bash
gcloud storage buckets create "$STATE_BUCKET" --project="$PROJECT_ID" \
  --location="$REGION" --uniform-bucket-level-access
gcloud storage buckets update "$STATE_BUCKET" --versioning
```

### 4. CI service account + Phase-1 roles
```bash
gcloud iam service-accounts create "$SA_NAME" --project="$PROJECT_ID" \
  --display-name="IaC CI (GitHub Actions)"
export SA="${SA_NAME}@${PROJECT_ID}.iam.gserviceaccount.com"

for r in roles/container.admin roles/compute.admin roles/iam.serviceAccountUser \
         roles/cloudkms.admin roles/storage.admin roles/serviceusage.serviceUsageConsumer; do
  gcloud projects add-iam-policy-binding "$PROJECT_ID" \
    --member="serviceAccount:$SA" --role="$r" --condition=None
done
# NOTE: broad POC roles — tighten to least-privilege before production.
```

### 5. Workload Identity Federation (keyless GitHub OIDC)
```bash
gcloud iam workload-identity-pools create github-pool \
  --project="$PROJECT_ID" --location=global --display-name="GitHub pool"

gcloud iam workload-identity-pools providers create-oidc github-provider \
  --project="$PROJECT_ID" --location=global --workload-identity-pool=github-pool \
  --display-name="GitHub provider" \
  --issuer-uri="https://token.actions.githubusercontent.com" \
  --attribute-mapping="google.subject=assertion.sub,attribute.repository=assertion.repository,attribute.ref=assertion.ref" \
  --attribute-condition="assertion.repository=='${GH_REPO}'"

# let the repo impersonate the CI SA
gcloud iam service-accounts add-iam-policy-binding "$SA" --project="$PROJECT_ID" \
  --role=roles/iam.workloadIdentityUser \
  --member="principalSet://iam.googleapis.com/projects/${PROJECT_NUMBER}/locations/global/workloadIdentityPools/github-pool/attribute.repository/${GH_REPO}"

# the value Claude needs for the workflow:
echo "WIF_PROVIDER=projects/${PROJECT_NUMBER}/locations/global/workloadIdentityPools/github-pool/providers/github-provider"
echo "CI_SA=${SA}"
```

### 6. GitHub repos
```bash
gh repo create kg-aifabrik/iac-gke-poc --private --description "iac-k8s: Terraform + GitHub Actions (POC)"
gh repo create kg-aifabrik/iac-console-poc --private --description "iac-k8s: operator console (POC)"
```
Also create a GitHub **Environment** named `poc-apply` on `iac-gke-poc` with **yourself as a required reviewer** (Settings → Environments) — this is the apply approval gate. *(Or grant Claude admin on the repo and it'll create it via `gh api`.)*

### 7. Budget alert
Easiest via Console (Billing → Budgets & alerts): scope to `$PROJECT_ID`, amount e.g. **$50**, alerts at 50/90/100%. (CLI: `gcloud billing budgets create` — beta.)

### 8. Local tooling (on the machine Claude will use)
```bash
brew install --cask google-cloud-sdk
brew tap hashicorp/tap && brew install hashicorp/tap/terraform   # terraform is NOT in homebrew-core (BSL relicense)
brew install kubernetes-cli gh
gcloud auth login && gcloud auth application-default login
gh auth login        # with repo + workflow scopes, push access to kg-aifabrik/iac-gke-poc
gcloud config set project "$PROJECT_ID"
```

---

## Handoff to Phase 1

Derived values (already known from your inputs — confirm once Phase 0 commands succeed):

```
PROJECT_ID    = k8s-iac-poc
PROJECT_NUMBER= 783778742587
REGION        = us-central1
STATE_BUCKET  = gs://k8s-iac-poc-tfstate
CI_SA         = k8s-iac-poc-ci@k8s-iac-poc.iam.gserviceaccount.com
WIF_PROVIDER  = projects/783778742587/locations/global/workloadIdentityPools/github-pool/providers/github-provider
REPOS         = kg-aifabrik/iac-gke-poc , kg-aifabrik/iac-console-poc
```

Checklist to confirm to Claude:

- [ ] **Project ID** and **Project Number**
- [ ] **Region** (`us-central1`)
- [ ] **Terraform state bucket** name
- [ ] **WIF provider** full resource name (`WIF_PROVIDER` printed in step 5)
- [ ] **CI service account** email (`CI_SA` printed in step 5)
- [ ] **GitHub repo URLs** — `kg-aifabrik/iac-gke-poc`, `kg-aifabrik/iac-console-poc`
- [ ] `gh` is authenticated locally with **push access** to `iac-gke-poc` (so Claude can scaffold, push, and open PRs)
- [ ] `terraform`, `kubectl`, `gcloud` installed; `gcloud` authenticated to the project
- [ ] `poc-apply` **Environment** exists on `iac-gke-poc` with you as required reviewer (or Claude has repo admin to create it)

### What Claude does in Phase 1 (for reference)
Scaffold `iac-gke-poc` (foundation + `gke-cluster` module + `poc.tfvars`), add the `plan`/`apply`/`destroy` GitHub Actions workflows wired to the WIF provider + CI SA, open a PR (you see the plan), and on approval the `apply` workflow builds the cluster — then validate (zones, pools, Confidential, COS) and test teardown.
