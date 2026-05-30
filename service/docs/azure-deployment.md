# Azure Deployment Guide — Llull Service

## Prerequisites

- Azure CLI (`az`) installed and logged in: `az login`
- Docker installed and running
- Bash or PowerShell

---

## 1. Set Variables

```bash
# Customize these
RESOURCE_GROUP="rg-llull"
LOCATION="westus2"
ACR_NAME="llullregistry"          # Must be globally unique
ENVIRONMENT_NAME="llull-env"
APP_NAME="llull-api"
SUBSCRIPTION_ID=$(az account show --query id -o tsv)
```

---

## 2. Create Resource Group and ACR

```bash
# Resource group
az group create --name $RESOURCE_GROUP --location $LOCATION

# Azure Container Registry
az acr create \
  --resource-group $RESOURCE_GROUP \
  --name $ACR_NAME \
  --sku Basic \
  --admin-enabled true
```

---

## 3. Build and Push Docker Image

```bash
# Build locally and push to ACR
az acr build \
  --registry $ACR_NAME \
  --image llull:latest \
  --file service/Dockerfile \
  service/

# Or push manually:
ACR_LOGIN_SERVER=$(az acr show --name $ACR_NAME --query loginServer -o tsv)
docker build -t $ACR_LOGIN_SERVER/llull:latest service/
az acr login --name $ACR_NAME
docker push $ACR_LOGIN_SERVER/llull:latest
```

---

## 4. Create Container App Environment

```bash
# Install Container Apps extension
az extension add --name containerapp --upgrade

az containerapp env create \
  --name $ENVIRONMENT_NAME \
  --resource-group $RESOURCE_GROUP \
  --location $LOCATION
```

---

## 5. Deploy Container App

```bash
ACR_CREDENTIALS=$(az acr credential show --name $ACR_NAME --query "{username:username,password:passwords[0].value}" -o json)
ACR_USERNAME=$(echo $ACR_CREDENTIALS | jq -r .username)
ACR_PASSWORD=$(echo $ACR_CREDENTIALS | jq -r .password)
ACR_SERVER=$(az acr show --name $ACR_NAME --query loginServer -o tsv)

az containerapp create \
  --name $APP_NAME \
  --resource-group $RESOURCE_GROUP \
  --environment $ENVIRONMENT_NAME \
  --image $ACR_SERVER/llull:latest \
  --registry-server $ACR_SERVER \
  --registry-username $ACR_USERNAME \
  --registry-password $ACR_PASSWORD \
  --target-port 8000 \
  --ingress external \
  --min-replicas 1 \
  --max-replicas 5 \
  --cpu 1.0 \
  --memory 2.0Gi \
  --env-vars \
    AUTH_ENABLED=true \
    LLM_PROVIDER=anthropic \
    STORAGE_BACKEND=azure \
    DATABASE_URL="sqlite+aiosqlite:///./data/llull.db"
```

---

## 6. Configure AAD App Registration

```bash
# Create app registration
APP_ID=$(az ad app create \
  --display-name "Llull API" \
  --sign-in-audience AzureADMyOrg \
  --query appId -o tsv)

# Create service principal
az ad sp create --id $APP_ID

# Get tenant ID
TENANT_ID=$(az account show --query tenantId -o tsv)

# Update Container App with AAD config
az containerapp update \
  --name $APP_NAME \
  --resource-group $RESOURCE_GROUP \
  --set-env-vars \
    AAD_TENANT_ID=$TENANT_ID \
    AAD_CLIENT_ID=$APP_ID
```

---

## 7. Configure Azure Key Vault for Secrets

```bash
VAULT_NAME="llull-vault"

# Create Key Vault
az keyvault create \
  --name $VAULT_NAME \
  --resource-group $RESOURCE_GROUP \
  --location $LOCATION

# Add secrets
az keyvault secret set --vault-name $VAULT_NAME --name "llm-api-key" --value "your-api-key"
az keyvault secret set --vault-name $VAULT_NAME --name "storage-connection-string" --value "your-connection-string"

# Grant Container App identity access to Key Vault
IDENTITY_ID=$(az containerapp identity assign \
  --name $APP_NAME \
  --resource-group $RESOURCE_GROUP \
  --system-assigned \
  --query principalId -o tsv)

az keyvault set-policy \
  --name $VAULT_NAME \
  --object-id $IDENTITY_ID \
  --secret-permissions get list

# Reference Key Vault secrets in Container App
az containerapp update \
  --name $APP_NAME \
  --resource-group $RESOURCE_GROUP \
  --set-env-vars \
    "LLM_API_KEY=secretref:llm-api-key" \
    "AZURE_STORAGE_CONNECTION_STRING=secretref:storage-connection-string"
```

---

## 8. Configure Azure Blob Storage

```bash
STORAGE_ACCOUNT="llullstorage"
CONTAINER_NAME="llull-sources"

# Create storage account
az storage account create \
  --name $STORAGE_ACCOUNT \
  --resource-group $RESOURCE_GROUP \
  --location $LOCATION \
  --sku Standard_LRS

# Get connection string
STORAGE_CONN=$(az storage account show-connection-string \
  --name $STORAGE_ACCOUNT \
  --resource-group $RESOURCE_GROUP \
  --query connectionString -o tsv)

# Create container
az storage container create \
  --name $CONTAINER_NAME \
  --connection-string $STORAGE_CONN

# Update Key Vault with connection string
az keyvault secret set \
  --vault-name $VAULT_NAME \
  --name "storage-connection-string" \
  --value $STORAGE_CONN

# Update Container App
az containerapp update \
  --name $APP_NAME \
  --resource-group $RESOURCE_GROUP \
  --set-env-vars \
    AZURE_STORAGE_CONTAINER=$CONTAINER_NAME \
    STORAGE_BACKEND=azure
```

---

## Verify Deployment

```bash
# Get the app URL
APP_URL=$(az containerapp show \
  --name $APP_NAME \
  --resource-group $RESOURCE_GROUP \
  --query properties.configuration.ingress.fqdn -o tsv)

# Health check
curl https://$APP_URL/health
# Expected: {"status": "ok"}

# API docs
echo "API docs: https://$APP_URL/docs"
```

---

## Notes

- SQLite is used for simplicity. For production scale, consider migrating to Azure SQL or PostgreSQL (update `DATABASE_URL` and SQLAlchemy driver).
- The Container App mounts an ephemeral filesystem by default — SQLite data will be lost on restart. Mount Azure Files for persistence.
- sentence-transformers model downloads on first run — consider pre-loading in the Docker image for faster cold starts.
