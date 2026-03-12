#!/usr/bin/env bash
# =============================================================================
# setup-gcp.sh — Run ONCE per project to wire up GCP for GitHub Actions deploys.
#
# What this does:
#   1.  Enables required GCP APIs
#   2.  Creates Artifact Registry repo (docker, asia-southeast1)
#   3.  Creates a least-privilege service account for Cloud Run + CI
#   4.  Grants only the IAM roles the SA actually needs (project-level)
#   5.  Grants roles/iam.serviceAccountTokenCreator on the SA itself
#       (required for GCS signed URL generation via ADC)
#   6.  Cleans up overly broad roles if manually added
#   7.  Creates a Workload Identity Pool + OIDC Provider scoped to YOUR repo
#       and YOUR branch (main) — not all of GitHub
#   8.  Binds the pool provider → SA so GitHub Actions can impersonate it
#   9.  Cross-project grants on FIREBASE_PROJECT_ID:
#       - roles/firebaseauth.admin   → verify Firebase tokens
#       - roles/storage.objectAdmin  → read/write GCS bucket (bucket-scoped)
#   10. Enables Secret Manager and creates placeholder secrets
#   11. Prints the exact values to paste into GitHub Secrets
#
# Security properties:
#   - No JSON key file is created or downloaded at any point
#   - Workload Identity attribute condition restricts auth to one repo + branch
#   - All IAM bindings use --condition=None (explicit, auditable)
#   - GCS access scoped to bucket level in the Firebase project, not project-wide
#   - Script is fully idempotent — safe to re-run
#
# Prerequisites:
#   - gcloud CLI installed and authenticated (gcloud auth login)
#   - A GCP project set: gcloud config set project YOUR_PROJECT
#   - jq installed (brew install jq / apt install jq)
#   - Your account must have Owner/Editor on both PROJECT_ID and FIREBASE_PROJECT_ID
#
# Usage:
#   chmod +x setup-gcp.sh
#   GITHUB_ORG=your-org GITHUB_REPO=your-repo ./setup-gcp.sh
# =============================================================================

set -euo pipefail

# ── Configurable ─────────────────────────────────────────────────────────────
PROJECT_ID="${PROJECT_ID:-$(gcloud config get-value project 2>/dev/null)}"
FIREBASE_PROJECT_ID="${FIREBASE_PROJECT_ID:-pawsport-cfd33}"
GITHUB_ORG="${GITHUB_ORG:-}"
GITHUB_REPO="${GITHUB_REPO:-}"
REGION="${REGION:-asia-southeast1}"
AR_LOCATION="${AR_LOCATION:-asia-southeast1}"
AR_REPO="${AR_REPO:-pawsport}"
GCS_BUCKET="${GCS_BUCKET:-pawsport}"
SA_NAME="${SA_NAME:-pawsport-run}"
POOL_NAME="${POOL_NAME:-github-actions-pool}"
PROVIDER_NAME="${PROVIDER_NAME:-github-oidc}"
DEPLOY_BRANCH="${DEPLOY_BRANCH:-main}"
# ─────────────────────────────────────────────────────────────────────────────

# ── Colours ───────────────────────────────────────────────────────────────────
RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'
CYAN='\033[0;36m'; BOLD='\033[1m'; RESET='\033[0m'

step()  { echo -e "\n${CYAN}▶  ${1}${RESET}"; }
ok()    { echo -e "   ${GREEN}✓${RESET}  ${1}"; }
warn()  { echo -e "   ${YELLOW}⚠${RESET}  ${1}"; }
fatal() { echo -e "\n${RED}✗  ${1}${RESET}"; exit 1; }

# ── Helpers ───────────────────────────────────────────────────────────────────

# Check if a project-level IAM binding exists
has_project_role() {
  local project="$1" role="$2" member="$3"
  gcloud projects get-iam-policy "$project" \
    --format=json 2>/dev/null \
    | jq -r --arg role "$role" --arg member "$member" \
      '.bindings[] | select(.role == $role) | .members[] | select(. == $member)' \
    2>/dev/null || true
}

# Grant a project-level IAM role (idempotent)
grant_project_role() {
  local project="$1" role="$2" member="$3"
  local existing
  existing=$(has_project_role "$project" "$role" "$member")
  if [[ -z "$existing" ]]; then
    gcloud projects add-iam-policy-binding "$project" \
      --member="$member" \
      --role="$role" \
      --condition=None \
      --quiet > /dev/null
    ok "Granted $role on $project"
  else
    ok "Already has $role on $project"
  fi
}

# Remove a project-level IAM role if present (idempotent)
remove_project_role() {
  local project="$1" role="$2" member="$3"
  local existing
  existing=$(has_project_role "$project" "$role" "$member")
  if [[ -n "$existing" ]]; then
    gcloud projects remove-iam-policy-binding "$project" \
      --member="$member" \
      --role="$role" \
      --condition=None \
      --quiet > /dev/null
    ok "Removed $role from $project"
  else
    ok "Already clean: $role"
  fi
}

# ── Preflight ─────────────────────────────────────────────────────────────────
step "Preflight"

[[ -z "$PROJECT_ID"  ]] && fatal "PROJECT_ID not set. Run: gcloud config set project YOUR_PROJECT_ID"
[[ -z "$GITHUB_ORG"  ]] && fatal "GITHUB_ORG not set.  Run: GITHUB_ORG=yourorg ./setup-gcp.sh"
[[ -z "$GITHUB_REPO" ]] && fatal "GITHUB_REPO not set. Run: GITHUB_REPO=yourrepo ./setup-gcp.sh"

for cmd in gcloud jq openssl; do
  command -v "$cmd" &>/dev/null || fatal "'$cmd' is not installed."
done

ACTIVE_ACCOUNT=$(gcloud auth list --filter="status:ACTIVE" --format="value(account)" 2>/dev/null || true)
[[ -z "$ACTIVE_ACCOUNT" ]] && fatal "No active gcloud account. Run: gcloud auth login"

ok "Authenticated as:    $ACTIVE_ACCOUNT"
ok "Cloud Run project:   $PROJECT_ID"
ok "Firebase project:    $FIREBASE_PROJECT_ID"
ok "GitHub repo:         $GITHUB_ORG/$GITHUB_REPO (branch: $DEPLOY_BRANCH)"
ok "GCS bucket:          gs://${GCS_BUCKET} (in $FIREBASE_PROJECT_ID)"

SERVICE_ACCOUNT="${SA_NAME}@${PROJECT_ID}.iam.gserviceaccount.com"
SA_MEMBER="serviceAccount:${SERVICE_ACCOUNT}"

# ── Enable APIs ───────────────────────────────────────────────────────────────
step "Enabling GCP APIs (${PROJECT_ID})"
gcloud services enable \
  run.googleapis.com \
  secretmanager.googleapis.com \
  artifactregistry.googleapis.com \
  cloudbuild.googleapis.com \
  iam.googleapis.com \
  iamcredentials.googleapis.com \
  sts.googleapis.com \
  storage.googleapis.com \
  cloudtrace.googleapis.com \
  monitoring.googleapis.com \
  logging.googleapis.com \
  --project="$PROJECT_ID" \
  --quiet
ok "All APIs enabled"

# ── Artifact Registry ─────────────────────────────────────────────────────────
step "Artifact Registry"
if ! gcloud artifacts repositories describe "$AR_REPO" \
     --location="$AR_LOCATION" --project="$PROJECT_ID" --quiet 2>/dev/null; then
  gcloud artifacts repositories create "$AR_REPO" \
    --repository-format=docker \
    --location="$AR_LOCATION" \
    --project="$PROJECT_ID" \
    --description="PawsPort container images" \
    --quiet
  ok "Created repository: $AR_REPO"
else
  ok "Repository already exists: $AR_REPO"
fi

gcloud artifacts repositories update "$AR_REPO" \
  --location="$AR_LOCATION" \
  --project="$PROJECT_ID" \
  --enable-vulnerability-scanning \
  --quiet 2>/dev/null || warn "Could not enable vulnerability scanning (may already be enabled)"

ok "Image path: ${AR_LOCATION}-docker.pkg.dev/${PROJECT_ID}/${AR_REPO}"

# ── Service Account ───────────────────────────────────────────────────────────
step "Service Account"
if ! gcloud iam service-accounts describe "$SERVICE_ACCOUNT" \
     --project="$PROJECT_ID" --quiet 2>/dev/null; then
  gcloud iam service-accounts create "$SA_NAME" \
    --display-name="PawsPort Cloud Run + CI" \
    --description="Least-privilege SA for Cloud Run runtime and GitHub Actions deploys" \
    --project="$PROJECT_ID" \
    --quiet
  ok "Created: $SERVICE_ACCOUNT"
else
  ok "Already exists: $SERVICE_ACCOUNT"
fi

# Project-level roles in pawsport-api:
#   run.admin                  → create/update Cloud Run services and revisions
#   artifactregistry.writer    → push images from Cloud Build
#   secretmanager.secretAccessor → read secrets at runtime (Cloud Run)
#   secretmanager.admin        → create/update secrets during CI deploy step
#   cloudbuild.builds.editor   → submit builds
#   iam.serviceAccountUser     → allow Cloud Run to act as this SA
#   logging.logWriter          → emit structured logs
#   monitoring.metricWriter    → emit custom metrics
#   cloudtrace.agent           → emit distributed traces
#   serviceusage.serviceUsageConsumer → required for Cloud Run to call APIs
SA_ROLES=(
  "roles/run.admin"
  "roles/artifactregistry.writer"
  "roles/secretmanager.secretAccessor"
  "roles/secretmanager.admin"
  "roles/cloudbuild.builds.editor"
  "roles/iam.serviceAccountUser"
  "roles/logging.logWriter"
  "roles/monitoring.metricWriter"
  "roles/cloudtrace.agent"
  "roles/serviceusage.serviceUsageConsumer"
)

for role in "${SA_ROLES[@]}"; do
  grant_project_role "$PROJECT_ID" "$role" "$SA_MEMBER"
done

# Grant serviceAccountTokenCreator on the SA itself — required for
# blob.generate_signed_url() to work with Application Default Credentials.
# Without this, signed URL generation fails with a signing error at runtime.
step "Self-referential IAM (signed URL support)"
EXISTING_TOKEN_CREATOR=$(gcloud iam service-accounts get-iam-policy "$SERVICE_ACCOUNT" \
  --project="$PROJECT_ID" \
  --format=json 2>/dev/null \
  | jq -r --arg member "$SA_MEMBER" \
    '.bindings[] | select(.role == "roles/iam.serviceAccountTokenCreator") | .members[] | select(. == $member)' \
  || true)

if [[ -z "$EXISTING_TOKEN_CREATOR" ]]; then
  gcloud iam service-accounts add-iam-policy-binding "$SERVICE_ACCOUNT" \
    --role="roles/iam.serviceAccountTokenCreator" \
    --member="$SA_MEMBER" \
    --project="$PROJECT_ID" \
    --quiet > /dev/null
  ok "Granted roles/iam.serviceAccountTokenCreator on SA (self)"
else
  ok "Already has roles/iam.serviceAccountTokenCreator (self)"
fi

# ── Clean up overly broad roles ───────────────────────────────────────────────
step "Cleaning up overly broad project-level roles (${PROJECT_ID})"

STALE_ROLES=(
  "roles/viewer"
  "roles/storage.admin"
  "roles/storage.objectAdmin"
  "roles/logging.viewer"
  "roles/cloudbuild.builds.viewer"
)

for role in "${STALE_ROLES[@]}"; do
  remove_project_role "$PROJECT_ID" "$role" "$SA_MEMBER"
done

# ── Workload Identity Federation ──────────────────────────────────────────────
step "Workload Identity Federation"

if ! gcloud iam workload-identity-pools describe "$POOL_NAME" \
     --location=global --project="$PROJECT_ID" --quiet 2>/dev/null; then
  gcloud iam workload-identity-pools create "$POOL_NAME" \
    --location=global \
    --project="$PROJECT_ID" \
    --display-name="GitHub Actions" \
    --description="Allows GitHub Actions to authenticate without a service account key" \
    --quiet
  ok "Created pool: $POOL_NAME"
else
  ok "Pool already exists: $POOL_NAME"
fi

POOL_RESOURCE=$(gcloud iam workload-identity-pools describe "$POOL_NAME" \
  --location=global \
  --project="$PROJECT_ID" \
  --format="value(name)")

ATTRIBUTE_CONDITION="assertion.repository == '${GITHUB_ORG}/${GITHUB_REPO}' && assertion.ref == 'refs/heads/${DEPLOY_BRANCH}'"

if ! gcloud iam workload-identity-pools providers describe "$PROVIDER_NAME" \
     --workload-identity-pool="$POOL_NAME" \
     --location=global \
     --project="$PROJECT_ID" --quiet 2>/dev/null; then
  gcloud iam workload-identity-pools providers create-oidc "$PROVIDER_NAME" \
    --workload-identity-pool="$POOL_NAME" \
    --location=global \
    --project="$PROJECT_ID" \
    --issuer-uri="https://token.actions.githubusercontent.com" \
    --attribute-mapping="\
google.subject=assertion.sub,\
attribute.repository=assertion.repository,\
attribute.actor=assertion.actor,\
attribute.ref=assertion.ref" \
    --attribute-condition="${ATTRIBUTE_CONDITION}" \
    --quiet
  ok "Created OIDC provider: $PROVIDER_NAME"
else
  warn "Provider already exists — attribute-condition NOT updated automatically."
  warn "To update: gcloud iam workload-identity-pools providers update-oidc $PROVIDER_NAME ..."
fi

PROVIDER_RESOURCE=$(gcloud iam workload-identity-pools providers describe "$PROVIDER_NAME" \
  --workload-identity-pool="$POOL_NAME" \
  --location=global \
  --project="$PROJECT_ID" \
  --format="value(name)")

PRINCIPAL="principalSet://iam.googleapis.com/${POOL_RESOURCE}/attribute.repository/${GITHUB_ORG}/${GITHUB_REPO}"

EXISTING_WIF=$(gcloud iam service-accounts get-iam-policy "$SERVICE_ACCOUNT" \
  --project="$PROJECT_ID" \
  --format=json 2>/dev/null \
  | jq -r --arg member "$PRINCIPAL" \
    '.bindings[] | select(.role == "roles/iam.workloadIdentityUser") | .members[] | select(. == $member)' \
  || true)

if [[ -z "$EXISTING_WIF" ]]; then
  gcloud iam service-accounts add-iam-policy-binding "$SERVICE_ACCOUNT" \
    --role="roles/iam.workloadIdentityUser" \
    --member="$PRINCIPAL" \
    --project="$PROJECT_ID" \
    --quiet > /dev/null
  ok "Bound Workload Identity → SA"
else
  ok "Workload Identity binding already exists"
fi

# ── Cross-project: Firebase + GCS (pawsport-cfd33) ───────────────────────────
step "Cross-project grants on ${FIREBASE_PROJECT_ID}"

# firebaseauth.admin → verify/manage Firebase Auth tokens at runtime
grant_project_role "$FIREBASE_PROJECT_ID" "roles/firebaseauth.admin" "$SA_MEMBER"

# GCS bucket-scoped objectAdmin — bucket lives in the Firebase project
# objectAdmin = read, write, delete objects (no bucket config changes)
EXISTING_GCS=$(gcloud storage buckets get-iam-policy "gs://${GCS_BUCKET}" \
  --format=json 2>/dev/null \
  | jq -r --arg member "$SA_MEMBER" \
    '.bindings[] | select(.role == "roles/storage.objectAdmin") | .members[] | select(. == $member)' \
  || true)

if [[ -z "$EXISTING_GCS" ]]; then
  gcloud storage buckets add-iam-policy-binding "gs://${GCS_BUCKET}" \
    --member="$SA_MEMBER" \
    --role="roles/storage.objectAdmin"
  ok "Granted roles/storage.objectAdmin on gs://${GCS_BUCKET}"
else
  ok "Already has roles/storage.objectAdmin on gs://${GCS_BUCKET}"
fi

# ── Placeholder Secrets ───────────────────────────────────────────────────────
step "Secret Manager — creating placeholder secrets"

create_placeholder() {
  local name="$1"
  if ! gcloud secrets describe "$name" --project="$PROJECT_ID" --quiet 2>/dev/null; then
    echo "PLACEHOLDER_REPLACE_ME" | gcloud secrets create "$name" \
      --replication-policy=automatic \
      --data-file=- \
      --project="$PROJECT_ID" \
      --quiet
    ok "Created (placeholder): $name"
  else
    ok "Already exists: $name"
  fi
}

create_placeholder "POSTGRES_URL"
create_placeholder "REDIS_CACHE_URL"
create_placeholder "QDRANT_CLOUD_URL"
create_placeholder "QDRANT_CLOUD_API_KEY"
create_placeholder "SECRET_KEY"
create_placeholder "ADMIN_SESSION_SIGNING_SECRET"
create_placeholder "RESEND_API_KEY"
create_placeholder "ADMIN_PASSWORD"
create_placeholder "GCS_BUCKET_NAME"

warn "Placeholder secrets created. The deploy workflow will overwrite them on first push."
warn "You can also set real values now: echo 'value' | gcloud secrets versions add NAME --data-file=-"

# ── Print GitHub Secrets ──────────────────────────────────────────────────────
echo ""
echo -e "${BOLD}══════════════════════════════════════════════════════════════${RESET}"
echo -e "${BOLD}  Add these to GitHub → Settings → Secrets → Actions:${RESET}"
echo -e "${BOLD}══════════════════════════════════════════════════════════════${RESET}"
echo ""
printf "  ${CYAN}%-40s${RESET} %s\n" "GCP_PROJECT_ID"                    "$PROJECT_ID"
printf "  ${CYAN}%-40s${RESET} %s\n" "GCP_SERVICE_ACCOUNT"               "$SERVICE_ACCOUNT"
printf "  ${CYAN}%-40s${RESET} %s\n" "GCP_WORKLOAD_IDENTITY_PROVIDER"    "$PROVIDER_RESOURCE"
printf "  ${CYAN}%-40s${RESET} %s\n" "POSTGRES_URL"                      "(your Neon connection string)"
printf "  ${CYAN}%-40s${RESET} %s\n" "REDIS_CACHE_URL"                   "(your Upstash Redis URL)"
printf "  ${CYAN}%-40s${RESET} %s\n" "QDRANT_CLOUD_URL"                  "(your Qdrant cluster URL)"
printf "  ${CYAN}%-40s${RESET} %s\n" "QDRANT_CLOUD_API_KEY"              "(your Qdrant API key)"
printf "  ${CYAN}%-40s${RESET} %s\n" "SECRET_KEY"                        "(your app secret key)"
printf "  ${CYAN}%-40s${RESET} %s\n" "ADMIN_SESSION_SIGNING_SECRET"      "(your admin session secret)"
printf "  ${CYAN}%-40s${RESET} %s\n" "RESEND_API_KEY"                    "(your Resend API key)"
printf "  ${CYAN}%-40s${RESET} %s\n" "ADMIN_PASSWORD"                    "(your admin password)"
echo ""
echo -e "  ${YELLOW}Note: RESEND_FROM_EMAIL and GCS_BUCKET_NAME are GitHub Variables (not secrets).${RESET}"
echo -e "  ${YELLOW}Add them under Settings → Secrets → Actions → Variables.${RESET}"
echo ""
echo -e "${BOLD}══════════════════════════════════════════════════════════════${RESET}"
echo -e "${GREEN}  Setup complete. Push to ${DEPLOY_BRANCH} to trigger your first deploy.${RESET}"
echo -e "${BOLD}══════════════════════════════════════════════════════════════${RESET}"
echo ""
echo -e "  ${YELLOW}Recommended next steps:${RESET}"
echo "  1. Set real secret values in GitHub → Settings → Secrets → Actions"
echo "  2. In GitHub → Settings → Environments:"
echo "     - Create 'staging' (no approval gate)"
echo "     - Create 'production' (add required reviewer — yourself)"
echo "  3. Enable branch protection on 'main': require PR + passing checks"
echo "  4. Commit .github/workflows/ and .github/dependabot.yml to your repo"
echo "  5. Delete secrets/google-service-account.json — no longer needed"
echo "     Cloud Run uses Application Default Credentials via the attached SA"
echo ""
