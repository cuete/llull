// main.bicep — Azure Container Apps (consumption, scale-to-zero) for Llull.
// One container serves both the FastAPI backend and the built React frontend.
// SQLite DB + local uploads persist on a mounted Azure Files share.
//
// Self-contained in its own resource group: this template also creates the
// Container Apps Environment and its Log Analytics workspace, so the app lands at
// https://<appName>.<env default domain>.
//
// maxReplicas is pinned to 1: SQLite is a single-writer store, so this app must
// never scale out past one instance (scale-to-zero when idle is fine).

@description('Container app name (becomes <name>.<env default domain>).')
param appName string

@description('Azure region.')
param location string = resourceGroup().location

@description('Full container image reference, e.g. ghcr.io/cuete/llull:<sha>.')
param containerImage string

@description('Container registry server.')
param registryServer string = 'ghcr.io'

@description('Container registry username (GitHub username/org for GHCR).')
param registryUsername string = ''

@description('Container registry password (a GitHub PAT with read:packages, for GHCR). Leave empty when the image is public.')
@secure()
param registryPassword string = ''

@description('LLM provider API key (an Anthropic API key with the default llmProvider).')
@secure()
param llmApiKey string

@description('Perplexity API key, used for the fact-check/source-rating feature. Leave empty to disable.')
@secure()
param perplexityApiKey string = ''

@description('Microsoft identity platform app registration client ID (not secret, but kept as a param for clarity).')
param aadClientId string

@description('LLM provider name.')
param llmProvider string = 'anthropic'

@description('LLM model identifier.')
param llmModel string = 'claude-sonnet-5-5'

@description('LLM base URL override (e.g. OpenRouter with llmProvider=openai). Leave empty for the provider default.')
param llmBaseUrl string = ''

@description('Allowed CORS origins, JSON array as a string. Defaults to the app\'s own origin.')
param corsOrigins string = ''

var storageAccountName = 'stllull${uniqueString(resourceGroup().id)}'
var fileShareName = 'llull-data'
var storageMountName = 'llull-data-mount'
var usePrivateRegistry = !empty(registryPassword)
var usePerplexity = !empty(perplexityApiKey)
var effectiveCorsOrigins = empty(corsOrigins)
  ? '["https://${appName}.${containerAppEnv.properties.defaultDomain}"]'
  : corsOrigins

resource logAnalytics 'Microsoft.OperationalInsights/workspaces@2023-09-01' = {
  name: '${appName}-logs'
  location: location
  properties: {
    sku: { name: 'PerGB2018' }
    retentionInDays: 30
  }
  tags: { managedby: 'claude-deploy' }
}

resource containerAppEnv 'Microsoft.App/managedEnvironments@2024-03-01' = {
  name: '${appName}-env'
  location: location
  properties: {
    appLogsConfiguration: {
      destination: 'log-analytics'
      logAnalyticsConfiguration: {
        customerId: logAnalytics.properties.customerId
        sharedKey: logAnalytics.listKeys().primarySharedKey
      }
    }
  }
  tags: { managedby: 'claude-deploy' }
}

resource storageAccount 'Microsoft.Storage/storageAccounts@2023-01-01' = {
  name: storageAccountName
  location: location
  sku: { name: 'Standard_LRS' }
  kind: 'StorageV2'
  properties: {
    minimumTlsVersion: 'TLS1_2'
    allowBlobPublicAccess: false
  }
  tags: { managedby: 'claude-deploy' }
}

resource fileService 'Microsoft.Storage/storageAccounts/fileServices@2023-01-01' = {
  parent: storageAccount
  name: 'default'
}

resource fileShare 'Microsoft.Storage/storageAccounts/fileServices/shares@2023-01-01' = {
  parent: fileService
  name: fileShareName
  properties: {
    shareQuota: 5
  }
}

resource envStorage 'Microsoft.App/managedEnvironments/storages@2024-03-01' = {
  parent: containerAppEnv
  name: storageMountName
  properties: {
    azureFile: {
      accountName: storageAccount.name
      accountKey: storageAccount.listKeys().keys[0].value
      shareName: fileShare.name
      accessMode: 'ReadWrite'
    }
  }
}

resource containerApp 'Microsoft.App/containerApps@2024-03-01' = {
  name: appName
  location: location
  properties: {
    managedEnvironmentId: containerAppEnv.id
    configuration: {
      ingress: {
        external: true
        targetPort: 8000
        transport: 'auto'
      }
      registries: usePrivateRegistry
        ? [
            {
              server: registryServer
              username: registryUsername
              passwordSecretRef: 'registry-password'
            }
          ]
        : []
      secrets: concat(
        [
          { name: 'llm-api-key', value: llmApiKey }
        ],
        usePrivateRegistry ? [{ name: 'registry-password', value: registryPassword }] : [],
        usePerplexity ? [{ name: 'perplexity-api-key', value: perplexityApiKey }] : []
      )
    }
    template: {
      containers: [
        {
          name: 'llull'
          image: containerImage
          resources: {
            cpu: json('1.0')
            memory: '2Gi'
          }
          env: concat(
            [
              { name: 'AUTH_ENABLED', value: 'true' }
              { name: 'AAD_TENANT_ID', value: 'consumers' }
              { name: 'AAD_CLIENT_ID', value: aadClientId }
              { name: 'DATABASE_URL', value: 'sqlite+aiosqlite:////app/data/llull.db' }
              { name: 'LOCAL_STORAGE_PATH', value: '/app/data/uploads' }
              { name: 'STORAGE_BACKEND', value: 'local' }
              { name: 'LLM_PROVIDER', value: llmProvider }
              { name: 'LLM_MODEL', value: llmModel }
              { name: 'LLM_API_KEY', secretRef: 'llm-api-key' }
              { name: 'CORS_ORIGINS', value: effectiveCorsOrigins }
              { name: 'READ_ONLY', value: 'false' }
            ],
            empty(llmBaseUrl) ? [] : [{ name: 'LLM_BASE_URL', value: llmBaseUrl }],
            usePerplexity ?[{ name: 'PERPLEXITY_API_KEY', secretRef: 'perplexity-api-key' }] : []
          )
          volumeMounts: [
            { volumeName: 'data', mountPath: '/app/data' }
          ]
        }
      ]
      volumes: [
        {
          name: 'data'
          storageType: 'AzureFile'
          storageName: envStorage.name
          // nobrl: SQLite's byte-range locks fail over SMB ("database is locked");
          // safe here because maxReplicas is 1, so there is only ever one writer.
          mountOptions: 'nobrl'
        }
      ]
      scale: {
        minReplicas: 0
        maxReplicas: 1
      }
    }
  }
  tags: { managedby: 'claude-deploy' }
}

output appUrl string = 'https://${containerApp.properties.configuration.ingress.fqdn}'
output appName string = containerApp.name
