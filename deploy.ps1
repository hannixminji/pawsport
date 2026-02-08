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
$DEFAULT_QDRANT_URL = "https://b05bfc38-37bb-4158-9bed-13d5d3d17bd5.us-west-2-0.aws.cloud.qdrant.io"
$QDRANT_URL = Read-Host "Enter Qdrant URL [Press Enter for saved URL]"
if ([string]::IsNullOrWhiteSpace($QDRANT_URL)) { $QDRANT_URL = $DEFAULT_QDRANT_URL }

$DEFAULT_QDRANT_KEY = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJhY2Nlc3MiOiJtIn0.tCU0pY0IsH4eSPHUi02l-WkGR5_jEH3xGzHu0mfbrVI"
$QDRANT_KEY = Read-Host "Enter Qdrant API Key [Press Enter for saved Key]"
if ([string]::IsNullOrWhiteSpace($QDRANT_KEY)) { $QDRANT_KEY = $DEFAULT_QDRANT_KEY }

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

# Construct Env Vars in YAML format
$EnvConfig = @{
    "ENVIRONMENT" = "staging"
    "ML_SERVICE_URL" = $ML_SERVICE_URL
    "POSTGRES_URL" = $POSTGRES_URL
    "REDIS_CACHE_URL" = $REDIS_URL
    "QDRANT_CLOUD_URL" = $QDRANT_URL
    "QDRANT_CLOUD_API_KEY" = $QDRANT_KEY
    "SECRET_KEY" = "generate_production_secret_key_here_automatically"
}

# Read Google Credentials from file
$SecretPath = ".\secrets\google-service-account.json"
if (Test-Path $SecretPath) {
    Write-Host "Reading Service Account Key from $SecretPath..." -ForegroundColor Green
    $RawJson = Get-Content $SecretPath -Raw
    # Minify JSON to ensure it fits on one line in the YAML value
    $MinifiedJson = $RawJson -replace "`r", "" -replace "`n", "" -replace "  ", ""
    $EnvConfig["GOOGLE_APPLICATION_CREDENTIALS_JSON"] = $MinifiedJson
} else {
    Write-Host "WARNING: Service Account Key not found at $SecretPath" -ForegroundColor Red
}

# Generate YAML file
$YamlContent = @()
foreach ($key in $EnvConfig.Keys) {
    $val = $EnvConfig[$key]
    if (-not [string]::IsNullOrWhiteSpace($val)) {
        # Escape single quotes if present
        $cleanVal = $val.ToString().Replace("'", "''")
        $YamlContent += "$key`: '$cleanVal'"
    }
}
$YamlContent | Set-Content -Path "deployment_env.yaml" -Encoding UTF8

# Deploy Backend with Env Vars File
gcloud run deploy $SERVICE_NAME `
  --image "gcr.io/$((gcloud config get-value project))/pawsport-backend" `
  --region $REGION `
  --platform managed `
  --allow-unauthenticated `
  --env-vars-file deployment_env.yaml

Write-Host "`nDeployment Complete!" -ForegroundColor Green
