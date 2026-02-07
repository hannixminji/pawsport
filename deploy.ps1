# Deploy PawsPort Backend to Google Cloud Run

$ErrorActionPreference = "Stop"

Write-Host "Starting PawsPort Deployment..." -ForegroundColor Cyan

# 1. Configuration Prompts
$SERVICE_NAME = Read-Host "Enter Service Name [default: pawsport-backend]"
if ([string]::IsNullOrWhiteSpace($SERVICE_NAME)) { $SERVICE_NAME = "pawsport-backend" }

$REGION = Read-Host "Enter GCP Region [default: asia-southeast1 (Singapore)]"
if ([string]::IsNullOrWhiteSpace($REGION)) { $REGION = "asia-southeast1" }

Write-Host "`nDatabase Configuration (Neon.tech)" -ForegroundColor Yellow
$DEFAULT_POSTGRES = "postgresql://neondb_owner:npg_oAHvbI1pezL6@ep-frosty-wave-a1k41ox3-pooler.ap-southeast-1.aws.neon.tech/neondb?ssl=require"
$POSTGRES_URL = Read-Host "Enter Postgres Connection String [Press Enter for saved Neon URL]"
if ([string]::IsNullOrWhiteSpace($POSTGRES_URL)) { $POSTGRES_URL = $DEFAULT_POSTGRES }

Write-Host "`nRedis Configuration (Upstash)" -ForegroundColor Yellow
$DEFAULT_REDIS = "rediss://default:ARxjAAImcDIwODExZGFhYzI4YzQ0MWE2OTE2NGVhNzU5MzdiMTFmY3AyNzI2Nw@factual-buffalo-7267.upstash.io:6379"
$REDIS_URL = Read-Host "Enter Redis Connection String [Press Enter for saved Upstash URL]"
if ([string]::IsNullOrWhiteSpace($REDIS_URL)) { $REDIS_URL = $DEFAULT_REDIS }

Write-Host "`nQdrant Configuration (Optional)" -ForegroundColor Yellow
$QDRANT_URL = Read-Host "Enter Qdrant URL (Press Enter to skip)"
$QDRANT_KEY = Read-Host "Enter Qdrant API Key (Press Enter to skip)"

# 2. Build & Submit ML Container
$BUILD_ML = Read-Host "`nBuild ML Container? (Takes ~20 mins) [y/N]"
if ($BUILD_ML -eq "y") {
    Write-Host "Building ML Container..." -ForegroundColor Cyan
    # Using explicit path ./ml
    gcloud builds submit --tag "gcr.io/$((gcloud config get-value project))/pawsport-ml" ./ml

    # 3. Deploy ML Service
    Write-Host "`nDeploying ML Service..." -ForegroundColor Cyan
    # Deploy ML service with more memory as ML tasks can be heavy
    gcloud run deploy "$SERVICE_NAME-ml" `
      --image "gcr.io/$((gcloud config get-value project))/pawsport-ml" `
      --region $REGION `
      --platform managed `
      --allow-unauthenticated `
      --memory 4Gi `
      --timeout 300 `
      --cpu 2
} else {
    Write-Host "Skipping ML Container Build..." -ForegroundColor Yellow
}

$ML_SERVICE_URL = gcloud run services describe "$SERVICE_NAME-ml" --region $REGION --format 'value(status.url)'
Write-Host "ML Service Deployed at: $ML_SERVICE_URL" -ForegroundColor Green

# 4. Build & Submit Backend Container
Write-Host "`nBuilding Backend Container..." -ForegroundColor Cyan
gcloud builds submit --tag "gcr.io/$((gcloud config get-value project))/pawsport-backend" .

# 5. Deploy Backend
Write-Host "`nDeploying Backend Service..." -ForegroundColor Cyan

# Construct Env Vars String
$ENV_VARS = "ENVIRONMENT=production"
$ENV_VARS += ",ML_SERVICE_URL=$ML_SERVICE_URL"
$ENV_VARS += ",POSTGRES_URL=$POSTGRES_URL"
$ENV_VARS += ",REDIS_CACHE_URL=$REDIS_URL"
$ENV_VARS += ",QDRANT_CLOUD_URL=$QDRANT_URL"
$ENV_VARS += ",QDRANT_CLOUD_API_KEY=$QDRANT_KEY"
# Using a placeholder for secret key - in prod this should be secure, but for thesis this is fine
$ENV_VARS += ",SECRET_KEY=generate_production_secret_key_here_automatically" 

# Deploy Command
gcloud run deploy $SERVICE_NAME `
  --image "gcr.io/$((gcloud config get-value project))/pawsport-backend" `
  --region $REGION `
  --platform managed `
  --allow-unauthenticated `
  --set-env-vars $ENV_VARS

Write-Host "`nDeployment Complete!" -ForegroundColor Green
