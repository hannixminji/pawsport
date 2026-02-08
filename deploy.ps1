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
$ENV_VARS = "ENVIRONMENT=staging"
$ENV_VARS += ",GOOGLE_APPLICATION_CREDENTIALS_JSON='ew0KICAidHlwZSI6ICJzZXJ2aWNlX2FjY291bnQiLA0KICAicHJvamVjdF9pZCI6ICJwYXdzcG9ydC1jZmQzMyIsDQogICJwcml2YXRlX2tleV9pZCI6ICJhODk4ZGEyMDJjY2M5MGRhODQ3N2FiNTk4NWFhMGEyZGRlMDlmYzcyIiwNCiAgInByaXZhdGVfa2V5IjogIi0tLS0tQkVHSU4gUFJJVkFURSBLRVktLS0tLVxuTUlJRXZnSUJBREFOQmdrcWhraUc5dzBCQVFFRkFBU0NCS2d3Z2dTa0FnRUFBb0lCQVFDTU5iQzOISXVEZTlWXG5DSnpSbGZZMk1PMHVnWnNYOHAzSWE2QmpRV1hQbFhvMEUxRzRWWlBVRGtnaUxyMDJad1JhUzZLRUFaWHNDZDFlXG5ZcXE3aFJZSzR6VWVuZXdydnZRaEZkbkdXMFlsRS9uRjEyRjlMWXQvZGZxb1I4T1VwbXRUZ08zbW9aNGJDVnRMXG40NloveGdpMWh2TjRMTnZJdUkvUW9KZjZNQTQ5OTJLbTAvY3RIdGlkZVVFQlFqelhNZmZXWU10NWhDRW81czZkXG5vWEl5Z3o1L1ZHdUFtTGtPUWdRVXprRjNYOUl0Ti9yVjJuMlF4Y3NzL25HTmd5c2l6MkFlR1BoUHFIZXBxMTBzXG5GWFFoYkFnNytRMGU0MkZmMGdEd0xuUDVrM3RWVWNDbVl1NWNqT3RBS2dzZ3pGdmF3TFRESkNRb2R6ckE0VnFyXG51N254TzVLM0FnTUJBQUVDZ2dFQUYrR01UODFtcDl1VVd3a084ZHprMTBsOTJpZHd3dm5maTM0c3FWSWtyTUNUXG5UUFBBRVBZRU9Ld3ZNUWhaM2FhRVZtTjhtOHdBU1JBek1iNm1IUFM1TjNmekc0SnRTTjBnOTg2a1VGN3RLRDhyXG4ycGQyL1NGQWdHM3NLRlR5K1Jyek9OQm5oajgzL010cE53cnlEZ0thbDF1dXV2Z2h4OHNyV0FrZWZDeFZbmRpZGxcbkFDOXI2WnNGc2JGNm5QRlM3b0RESWwzSktHM3NpSmpwenUrbkFmSG5Nai9pYzlacXZKRUNhN2pJVHJscC93ckRzXG5yeFFNQmVtaTI5SWlRNndmOXRHUUJFRkZjY3dFNGIwTE85SDRTdVYwSWd0WkRGYnI2OTVTZnhhN0ZKSDhNV2w3XG5LRXRaeWtZbWoweHhMV1U2dHZtR3V4cLHmpmTm9CNThwQTh6MkNQSlFnUUtCZ1FERXM5cjNMVW02Um44V0JIRGdcbm1JNHB0bGUzQThrcHV1dngyUTBTbHdRWjdWSmZvZE82ZXdkZDVxZk4wWnRXeWo4VURNTUpUTGlSQWtVbGtJWWVcbmNzUGNJd3hrVjNCd1Riam9iT0JIM0lGOE1MaHA2VHh4NG9KZ0JMbW1SeDEveDhuNmVvdktBTVByVmZYR0ZkcG1cbnpHbktTTTYyc3JhWGpGaVlZUkVhWXNGdEFRS0JnUURBM1MzbmNiZjd6aWo5S2pwTnZOSTlqT1Y1eXBjaU1QMnVcbk14dWxpaWJKZFg0Ui9EazNZbTd2Q3MvM0NXNHNJUVhUNWhhaXRyK3Y2OE1WMXBGV3NSdFpESkUwK1ZDR3dFQmFcbm5MR3A0N0MwSWNKYk5jZzN5Tkdmb0Fha29tL0tpaEJmbEYxSDFvQ2Q2blNwVXJrWTFCRjhRcVJaNHo0ZCtoYW9cbks3QnR0TjBqUndLQmdRQ044ZkE0WU5FTWdBQ1RqZ1k3bk5JK2FZRUJLWEl4VTlkT2dNZTV5Rk5KYjExdVRNVmQyXG5BYVFlU2YyYjAvK1NFTjZXSEdOK1NZUUN1SzFuWHpTNXNqM09sT2d6WExvQ0FNUkh6WkhIcWNNekdJRnJ4R2pmXG5FZ0xSUVd1cWJuaEdKcW1GZkh0MTZUbDRrUTZMeEdkWHVYazZCWEpPZXdheXRBK1czcTBWNm1BRTBRS0JnUUNpXG5BdXJGeW55QVZYc0FDRklUN1hNMjZ6bjF0bDZCQldDRXprQUNMbXhvdlg4YkFxTFp5S0Zod3RaeU1nVFBveW52XG5HQkNadlNbHVWU0hWMmg1MXRZZVdnYWNKbmR3WmFMa24ya3Y5UU0xc0tSR25UbFVQM2lpaTlxejJjemF6ZTFVMmVmcFxuTW91dZGhoaGpDWW5ZbHpRdXNTN0RFSVJaVWhCalJDdDJOOFVzVTB1VWp3S0JnRjR5RHVkeXQ2clpucW44dFF4bVxuVEJbcEpLY0NzRzRvdHRvdHRFTjg0N2pDcG01alY1akNRSW5VQm5lQzEvNUpTUGdWa081bHpTUXdFRm9wYkwvUGlcbm82WFpnUk82N0dPTGdIdUpYTzl6dm9RRm1yTE05VTA2OVd5RnViTjZJUGNTVi9CSHpONUJCU0dtTVZ0Qm81MGNcbnM3V2pjTmVGa2JrZXNDME1mWVNVZVFvY1xuLS0tLS1FTkQgUFJJVkFURSBLRVktLS0tLVxuIiwNCiAgImNsaWVudF9lbWFpbCI6ICJmaXJlYmFzZS1hZG1pbnNkay1mYnN2Y0BwYXdzcG9ydC1jZmQzMy5pYW0uZ3NlcnZpY2VhY2NvdW50LmNvbSIsDQogICJjbGllbnRfaWQiOiAiMTEwNTk0OTU1MjI4NDAwNzM5NTEyIiwNCiAgImF1dGhfdXJpIjogImh0dHBzOi8vYWNjb3VudHMuZ29vZ2xlLmNvbS9vL29hdXRoMi9hdXRoIiwNCiAgInRva2VuX3VyaSI6ICJodHRwczovL29hdXRoMi5nb29nbGVhcGlzLmNvbS90b2tlbiIsDQogICJhdXRoX3Byb3ZpZGVyX3g1MDlfY2VydF91cmwiOiAiaHR0cHM6Ly93d3cuZ29vZ2xlYXBpcy5jb20vb2F1dGgyL3YxL2NlcnRzIiwNCiAgImNsaWVudF94NTA5X2NlcnRfdXJsIjogImh0dHBzOi8vd3d3Lmdvb2dsZWFwaXMuY29tL3JvYm90L3YxL21ldGFkYXRhL3g1MDkvZmlyZWJhc2UtYWRtaW5zZGstZmJzdmMlNDBwYXdzcG9ydC1jZmQzMy5pYW0uZ3NlcnZpY2VhY2NvdW50LmNvbSIsDQogICJ1bml2ZXJzZV9kb21haW4iOiAiZ29vZ2xlYXBpcy5jb20iDQp9DQo='"
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
