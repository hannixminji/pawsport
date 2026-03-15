# Pawsport — New Google Account Migration Checklist

## Files to Change

### `run.sh`
Change one line only:
```bash
export PROJECT_ID=your-new-project-id  # was pawsport-cfd33
```

### Everything else
No changes needed — `Dockerfile`, `cloudbuild.yaml`, `deploy-backend.yml`,
`deploy-ml.yml`, `setup-cloudflare.yml`, `setup-gcp.sh` all stay the same.

---

## Full Step-by-Step

### Step 1 — Create New GCP Project
1. Go to [console.cloud.google.com](https://console.cloud.google.com)
2. Create a new project (note the project ID)
3. Enable billing with the new $300 free credits

---

### Step 2 — Create GCS Bucket (Manual)
Do this **before** running `run.sh` — the script assumes the bucket already exists.

1. Go to [console.cloud.google.com](https://console.cloud.google.com) → **Cloud Storage → Create bucket**
2. Name it `pawsport`, region `asia-southeast1`, uniform access control
3. Copy your ML models from the old bucket into `ml-models/` folder in the new bucket

> ⚠️ If the bucket name `pawsport` is taken (your old account still owns it),
> use a different name like `pawsport-2` and update:
> - `GCS_BUCKET` in `run.sh`
> - `GCS_BUCKET_NAME` GitHub Variable

> The ML models folder is required — `ml/cloudbuild.yaml` pulls `gs://pawsport/ml-models/*.onnx`
> during the ML image build. Without these files the ML build will fail.

---

### Step 3 — Run setup-gcp.sh
Update `run.sh` with the new project ID then run it from WSL:

```bash
# In WSL
cd /path/to/your/project
bash run.sh
```

This sets up:
- Artifact Registry (`pawsport` repo)
- Service Account (`pawsport-run`)
- All IAM roles
- Workload Identity Federation
- Secret Manager placeholder secrets

At the end it **prints the values** you need for the next step. Copy them.

---

### Step 4 — Update GitHub Secrets
Go to GitHub → your repo → **Settings → Secrets and variables → Actions → Secrets**

| Secret | New value (printed by setup-gcp.sh) |
|---|---|
| `GCP_SERVICE_ACCOUNT` | new service account email |
| `GCP_WORKLOAD_IDENTITY_PROVIDER` | new provider resource name |

These stay the same (not tied to GCP):
- `POSTGRES_URL`
- `REDIS_CACHE_URL`
- `QDRANT_CLOUD_URL`
- `QDRANT_CLOUD_API_KEY`
- `BREVO_API_KEY`
- `SECRET_KEY`
- `ADMIN_SESSION_SIGNING_SECRET`
- `ADMIN_PASSWORD`
- `CF_API_TOKEN` *(if using Cloudflare)*
- `CF_ZONE_ID` *(if using Cloudflare)*

---

### Step 5 — Update GitHub Variables
Go to GitHub → your repo → **Settings → Secrets and variables → Actions → Variables**

| Variable | New value |
|---|---|
| `GCP_PROJECT_ID` | your new project ID |

These stay the same:
- `GCS_BUCKET_NAME` *(unless you renamed the bucket)*
- `BREVO_SENDER_EMAIL`
- `BREVO_SENDER_NAME`
- `DOMAIN` *(if using custom domain)*

---

### Step 6 — Firebase Setup (Manual, ~5 minutes)

#### 6a. Link Firebase to new GCP project
1. Go to [console.firebase.google.com](https://console.firebase.google.com)
2. Click **Add project** → select your new GCP project (don't create a new one)
3. Follow the prompts to link it

#### 6b. Enable Firebase Authentication
1. Firebase Console → **Authentication → Get started**
2. Go to **Sign-in method** tab
3. Enable **Google** provider (and any others you use)

#### 6c. Create Firestore Database
1. Firebase Console → **Firestore Database → Create database**
2. Choose **Production mode**
3. Set region to `asia-southeast1`

#### 6d. Create `firebase.json`
Create this file in your project root — the CLI needs it to know where your rules and indexes files are:

```json
{
  "firestore": {
    "rules": "firestore.rules",
    "indexes": "firestore.indexes.json"
  }
}
```

#### 6e. Deploy Firestore Rules
Make sure `firestore.rules` is in your project folder, then:
```bash
firebase login   # login with new Google account
firebase deploy --only firestore:rules --project=your-new-project-id
```

#### 6f. Deploy Firestore Indexes
```bash
firebase deploy --only firestore:indexes --project=your-new-project-id
```

---

### Step 7 — Update Frontend Firebase Config
Your frontend has a `firebaseConfig` object that is tied to the old project. Get the new one from:

Firebase Console → new project → **Project Settings → Your apps → SDK setup and configuration**

Replace the old config in your frontend code:
```js
const firebaseConfig = {
  apiKey: "...",
  authDomain: "your-new-project-id.firebaseapp.com",
  projectId: "your-new-project-id",
  storageBucket: "your-new-project-id.appspot.com",
  messagingSenderId: "...",
  appId: "..."
};
```

---

### Step 8 — Update Local Service Account JSON (for local testing)
Your backend uses a service account JSON file to test locally. You need a new one from the new project.

1. Go to GCP Console → **IAM & Admin → Service Accounts**
2. Click on `pawsport-run` service account
3. Go to **Keys** tab → **Add Key → Create new key → JSON**
4. Download it and replace your existing local `.json` file

---

### Step 9 — Trigger First Deploy
Push to `main` or manually trigger **Deploy Backend** from GitHub Actions.

After deploy succeeds, manually trigger **Deploy ML Service** if needed.

---

## Summary of What Changes vs Stays the Same

| Item | Changes? |
|---|---|
| `run.sh` PROJECT_ID | ✅ Yes |
| GitHub Secret: `GCP_SERVICE_ACCOUNT` | ✅ Yes |
| GitHub Secret: `GCP_WORKLOAD_IDENTITY_PROVIDER` | ✅ Yes |
| GitHub Variable: `GCP_PROJECT_ID` | ✅ Yes |
| GCS bucket (manual create) | ✅ Yes |
| Firebase project (manual link) | ✅ Yes |
| Firestore rules + indexes (deploy via CLI) | ✅ Yes |
| Frontend `firebaseConfig` | ✅ Yes |
| Local service account JSON | ✅ Yes |
| All other GitHub Secrets | ❌ No change |
| All workflow YAML files | ❌ No change |
| Dockerfile | ❌ No change |
| cloudbuild.yaml | ❌ No change |
| App code | ❌ No change |
