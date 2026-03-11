cp -r /mnt/c/Users/user/AppData/Roaming/gcloud ~/gcloud-config
export GITHUB_ORG=hannixminji
export GITHUB_REPO=pawsport
export PROJECT_ID=pawsport-api
export PATH="$HOME:/c/Users/user/AppData/Local/Google/Cloud SDK/google-cloud-sdk/bin:$PATH"
export CLOUDSDK_CONFIG=$HOME/gcloud-config
bash setup-gcp.sh
