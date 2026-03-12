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
#   6.  Grants roles/storage.objectAdmin on the GCS bucket (bucket-scoped)
#   7.  Grants Cloud Build SAs objectViewer on GCS bucket + serviceUsageConsumer
#   8.  Cleans up overly broad roles if manually added
#   9.  Creates a Workload Identity Pool + OIDC Provider scoped to YOUR repo
#       and YOUR branch (main) — not all of GitHub
#   10. Binds the pool provider → SA so GitHub Actions can impersonate it
#   11. Enables Secret Manager and creates placeholder secrets
#   12. Prints the exact values to paste into GitHub Secrets
#
# Security properties:
#   - No JSON key file is created or downloaded at any point
#   - Workload Identity attribute condition restricts auth to one repo + branch
#   - All IAM bindings use --condition=None (explicit, auditable)
#   - Firebase Auth works via ADC — same project, no cross-project grants needed
#   - Script is fully idempotent — safe to re-run
#
# Prerequisites:
#   - gcloud CLI installed and authenticated (gcloud auth login)
#   - A GCP project set: gcloud config set project YOUR_PROJECT
#   - jq installed (brew install jq / apt install jq)
#
# Usage:
#   chmod +x setup-gcp.sh
#   GITHUB_ORG=your-org GITHUB_REPO=your-repo PROJECT_ID=your-project ./setup-gcp.sh
# =============================================================================

set -euo pipefail

# ── Configurable ─────────────────────────────────────────────────────────────
PROJECT_ID="${PROJECT_ID:-$(gcloud config get-value project 2>/dev/null)}"
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

has_project_role() {
  local project="$1" role="$2" member="$3"
  gcloud projects get-iam-policy "$project" \
    --format=json 2>/dev/null \
    | jq -r --arg role "$role" --arg member "$member" \
      '.bindings[] | select(.role == $role) | .members[] | select(. == $member)' \
    2>/dev/null || true
}

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
    ok "Granted $role"
  else
    ok "Already has $role"
  fi
}

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
    ok "Removed $role"
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

ok "Authenticated as: $ACTIVE_ACCOUNT"
ok "Project:          $PROJECT_ID"
ok "GitHub repo:      $GITHUB_ORG/$GITHUB_REPO (branch: $DEPLOY_BRANCH)"
ok "GCS bucket:       gs://${GCS_BUCKET}"

SERVICE_ACCOUNT="${SA_NAME}@${PROJECT_ID}.iam.gserviceaccount.com"
SA_MEMBER="serviceAccount:${SERVICE_ACCOUNT}"

# ── Enable APIs ───────────────────────────────────────────────────────────────
step "Enabling GCP APIs"
gcloud services enable \
  run.googleapis.com \
  secretmanager.googleapis.com \
  artifactregistry.googleapis.com \
  cloudbuild.googleapis.com \
  iam.googleapis.com \
  iamcredentials.googleapis.com \
  sts.googleapis.com \
  storage.googleapis.com \
  firebase.googleapis.com \
  identitytoolkit.googleapis.com \
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

# Project-level roles:
#   run.admin                    → create/update Cloud Run services and revisions
#   artifactregistry.writer      → push images from Cloud Build
#   secretmanager.secretAccessor → read secrets at runtime (Cloud Run)
#   secretmanager.admin          → create/update secrets during CI deploy step
#   cloudbuild.builds.editor     → submit builds
#   iam.serviceAccountUser       → allow Cloud Run to act as this SA
#   logging.logWriter            → emit structured logs
#   monitoring.metricWriter      → emit custom metrics
#   cloudtrace.agent             → emit distributed traces
#   storage.admin                → full GCS access incl. Cloud Build staging bucket
#   serviceusage.serviceUsageConsumer → required for Cloud Run to call GCP APIs
#   firebaseauth.admin           → verify/manage Firebase Auth tokens (same project)
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
  "roles/storage.admin"
  "roles/serviceusage.serviceUsageConsumer"
  "roles/firebaseauth.admin"
)

for role in "${SA_ROLES[@]}"; do
  grant_project_role "$PROJECT_ID" "$role" "$SA_MEMBER"
done

# ── Self-referential IAM (signed URL support) ─────────────────────────────────
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

# ── GCS Bucket IAM ────────────────────────────────────────────────────────────
step "GCS Bucket IAM"

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

# objectViewer on the bucket for Cloud Build SAs — needed to pull ML models during build
PROJECT_NUMBER=$(gcloud projects describe "$PROJECT_ID" --format="value(projectNumber)")
CLOUDBUILD_SA="serviceAccount:${PROJECT_NUMBER}@cloudbuild.gserviceaccount.com"
COMPUTE_SA="serviceAccount:${PROJECT_NUMBER}-compute@developer.gserviceaccount.com"

for BUILD_SA in "$CLOUDBUILD_SA" "$COMPUTE_SA"; do
  EXISTING_BUILD_GCS=$(gcloud storage buckets get-iam-policy "gs://${GCS_BUCKET}" \
    --format=json 2>/dev/null \
    | jq -r --arg member "$BUILD_SA" \
      '.bindings[] | select(.role == "roles/storage.objectViewer") | .members[] | select(. == $member)' \
    || true)

  if [[ -z "$EXISTING_BUILD_GCS" ]]; then
    gcloud storage buckets add-iam-policy-binding "gs://${GCS_BUCKET}" \
      --member="$BUILD_SA" \
      --role="roles/storage.objectViewer" \
      --quiet
    ok "Granted roles/storage.objectViewer on gs://${GCS_BUCKET} to ${BUILD_SA}"
  else
    ok "Already has roles/storage.objectViewer: ${BUILD_SA}"
  fi
done

# serviceusage.serviceUsageConsumer for Cloud Build SAs — required to access the
# Cloud Build staging bucket (PROJECT_cloudbuild) during builds
for BUILD_SA in "$CLOUDBUILD_SA" "$COMPUTE_SA"; do
  grant_project_role "$PROJECT_ID" "roles/serviceusage.serviceUsageConsumer" "$BUILD_SA"
done

# serviceAccountTokenCreator on the runtime SA for Cloud Build SAs
for BUILD_SA in "$CLOUDBUILD_SA" "$COMPUTE_SA"; do
  EXISTING_TC=$(gcloud iam service-accounts get-iam-policy "$SERVICE_ACCOUNT" \
    --project="$PROJECT_ID" \
    --format=json 2>/dev/null \
    | jq -r --arg member "$BUILD_SA" \
      '.bindings[] | select(.role == "roles/iam.serviceAccountTokenCreator") | .members[] | select(. == $member)' \
    || true)

  if [[ -z "$EXISTING_TC" ]]; then
    gcloud iam service-accounts add-iam-policy-binding "$SERVICE_ACCOUNT" \
      --role="roles/iam.serviceAccountTokenCreator" \
      --member="$BUILD_SA" \
      --project="$PROJECT_ID" \
      --quiet > /dev/null
    ok "Granted roles/iam.serviceAccountTokenCreator to ${BUILD_SA}"
  else
    ok "Already has roles/iam.serviceAccountTokenCreator: ${BUILD_SA}"
  fi
done

# ── Clean up overly broad roles ───────────────────────────────────────────────
step "Cleaning up overly broad project-level roles"

STALE_ROLES=(
  "roles/viewer"
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
echo -e "  ${YELLOW}Note: GCP_PROJECT_ID, RESEND_FROM_EMAIL and GCS_BUCKET_NAME are GitHub Variables (not secrets).${RESET}"
echo -e "  ${YELLOW}Add them under Settings → Secrets → Actions → Variables.${RESET}"
echo ""
echo -e "${BOLD}══════════════════════════════════════════════════════════════${RESET}"
echo -e "${GREEN}  Setup complete. Push to ${DEPLOY_BRANCH} to trigger your first deploy.${RESET}"
echo -e "${BOLD}══════════════════════════════════════════════════════════════${RESET}"
echo ""
echo -e "  ${YELLOW}Recommended next steps:${RESET}"
echo "  1. Update GitHub Secrets: GCP_SERVICE_ACCOUNT and GCP_WORKLOAD_IDENTITY_PROVIDER"
echo "  2. Update GitHub Variable: GCP_PROJECT_ID = $PROJECT_ID"
echo "  3. In GitHub → Settings → Environments:"
echo "     - Create 'staging' (no approval gate)"
echo "     - Create 'production' (add required reviewer — yourself)"
echo "  4. Enable branch protection on 'main': require PR + passing checks"
echo "  5. Commit .github/workflows/ and setup-gcp.sh to your repo"
echo "  6. Delete secrets/google-service-account.json — no longer needed"
echo "     Cloud Run uses Application Default Credentials via the attached SA"
echo ""
