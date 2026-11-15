<#
  PulsoRed - despliegue completo en Azure (PowerShell 5.1+).  Uso:   .\infra\deploy.ps1
  Idempotente: se puede volver a ejecutar. Región por defecto: westus2 (la suscripción solo permite
  westus2, canadacentral, brazilsouth, chilecentral, westus).
  Salidas (con secretos, NO versionar): infra\outputs.local.json
#>
param(
  [string]$Region = 'westus2',
  [string]$RG = 'rg-pulsored',
  [string]$Suffix = '',
  [switch]$NoKeyVaultRefs,      # si las referencias a Key Vault fallan: guarda los secretos directo en app settings
  [switch]$SkipFrontend,
  [switch]$SkipBackend
)
$ErrorActionPreference = 'Stop'
$root = Split-Path $PSScriptRoot -Parent
$state = Join-Path $PSScriptRoot 'state.json'
$outFile = Join-Path $PSScriptRoot 'outputs.local.json'

function Step($t) { Write-Host "`n=== $t" -ForegroundColor Cyan }
function Az { # ejecuta az y falla si el código de salida != 0 (los avisos por stderr no cuentan)
  $prev = $ErrorActionPreference; $ErrorActionPreference = 'Continue'
  $o = & az.cmd @args 2>&1 | ForEach-Object { "$_" }
  $code = $LASTEXITCODE; $ErrorActionPreference = $prev
  if ($code -ne 0) { throw "az $($args -join ' ') falló:`n$($o -join "`n")" }
  return ($o | Where-Object { $_ -notmatch '^(WARNING|Warning)' }) -join "`n"
}
function AzTry { # true si el comando terminó bien (sirve para "¿existe?" y "intentar sin abortar")
  $prev = $ErrorActionPreference; $ErrorActionPreference = 'Continue'
  & az.cmd @args 2>&1 | Out-Null
  $code = $LASTEXITCODE; $ErrorActionPreference = $prev
  return ($code -eq 0)
}

# ---------- sufijo único (se conserva entre ejecuciones) ----------
if (-not $Suffix) {
  if (Test-Path $state) { $Suffix = (Get-Content $state -Raw | ConvertFrom-Json).suffix }
  else { $Suffix = ('pr' + (Get-Random -Minimum 1000 -Maximum 9999)) }
}
@{ suffix = $Suffix; region = $Region; rg = $RG } | ConvertTo-Json | Set-Content $state
$n = @{
  cosmos = "pulsored-cosmos-$Suffix"; sb = "pulsored-sb-$Suffix"; kv = "pulsored-kv-$Suffix"
  st = ("pulsoredst$Suffix").ToLower(); law = "pulsored-law-$Suffix"; ai = "pulsored-ai-$Suffix"
  func = "pulsored-func-$Suffix"; swa = "pulsored-web-$Suffix"; acs = "pulsored-acs-$Suffix"; email = "pulsored-email-$Suffix"
}
$out = @{}
if (Test-Path $outFile) { (Get-Content $outFile -Raw | ConvertFrom-Json).PSObject.Properties | ForEach-Object { $out[$_.Name] = $_.Value } }

Step "0. Sesión y proveedores"
$acct = Az account show -o json | ConvertFrom-Json
Write-Host "Suscripción: $($acct.name)  Región: $Region  Sufijo: $Suffix"
Az config set extension.use_dynamic_install=yes_without_prompt extension.dynamic_install_allow_preview=true | Out-Null
foreach ($p in 'Microsoft.DocumentDB','Microsoft.Web','Microsoft.ServiceBus','Microsoft.KeyVault','Microsoft.Communication','Microsoft.Insights','Microsoft.OperationalInsights','Microsoft.Storage') { Az provider register --namespace $p | Out-Null }

Step "1. Grupo de recursos"
Az group create -n $RG -l $Region -o none

Step "2. Cosmos DB (free tier; si no, serverless)"
if (-not (AzTry cosmosdb show -n $n.cosmos -g $RG -o none)) {
  $created = AzTry cosmosdb create -n $n.cosmos -g $RG --locations "regionName=$Region" failoverPriority=0 isZoneRedundant=False `
    --default-consistency-level Session --enable-free-tier true -o none
  if (-not $created -and -not (AzTry cosmosdb show -n $n.cosmos -g $RG -o none)) {
    Write-Host "Free tier no disponible -> serverless" -ForegroundColor Yellow
    Az cosmosdb create -n $n.cosmos -g $RG --locations "regionName=$Region" failoverPriority=0 isZoneRedundant=False `
      --default-consistency-level Session --capabilities EnableServerless -o none
    $out.cosmosMode = 'serverless'
  } else { $out.cosmosMode = 'free-tier' }
}
$serverless = (Az cosmosdb show -n $n.cosmos -g $RG --query "capabilities[?name=='EnableServerless'] | length(@)" -o tsv) -ne '0'
if (-not (AzTry cosmosdb sql database show -a $n.cosmos -g $RG -n pulsored -o none)) {
  if ($serverless) { Az cosmosdb sql database create -a $n.cosmos -g $RG -n pulsored -o none }
  else { Az cosmosdb sql database create -a $n.cosmos -g $RG -n pulsored --throughput 1000 -o none }   # 1000 RU/s compartidos (gratis)
}
$containers = @(
  @('reports','/zone_id'), @('incidents','/zone_id'), @('incident_users','/incident_id'), @('history','/entity_id'),
  @('infra_events','/zone_id'), @('notifications','/incident_id'), @('zones','/id'), @('leases','/id'))
foreach ($c in $containers) {
  if (-not (AzTry cosmosdb sql container show -a $n.cosmos -g $RG -d pulsored -n $c[0] -o none)) {
    $extra = @(); if ($c[0] -eq 'infra_events') { $extra = @('--ttl', '-1') }   # TTL por documento (30 días)
    Az cosmosdb sql container create -a $n.cosmos -g $RG -d pulsored -n $c[0] -p $c[1] @extra -o none
  }
}
$cosmosConn = (Az cosmosdb keys list -n $n.cosmos -g $RG --type connection-strings --query "connectionStrings[0].connectionString" -o tsv).Trim()

Step "3. Service Bus (Basic) y colas con dead-letter"
if (-not (AzTry servicebus namespace show -n $n.sb -g $RG -o none)) { Az servicebus namespace create -n $n.sb -g $RG -l $Region --sku Basic -o none }
foreach ($q in 'notifications','analytics-export') {
  if (-not (AzTry servicebus queue show --namespace-name $n.sb -g $RG -n $q -o none)) {
    Az servicebus queue create --namespace-name $n.sb -g $RG -n $q --max-delivery-count 10 --lock-duration PT2M -o none
  }
}
$sbConn = (Az servicebus namespace authorization-rule keys list --namespace-name $n.sb -g $RG -n RootManageSharedAccessKey --query primaryConnectionString -o tsv).Trim()

Step "4. Storage, Log Analytics y Application Insights"
if (-not (AzTry storage account show -n $n.st -g $RG -o none)) { Az storage account create -n $n.st -g $RG -l $Region --sku Standard_LRS --allow-blob-public-access false -o none }
if (-not (AzTry monitor log-analytics workspace show -g $RG -n $n.law -o none)) { Az monitor log-analytics workspace create -g $RG -n $n.law -l $Region -o none }
$lawId = (Az monitor log-analytics workspace show -g $RG -n $n.law --query id -o tsv).Trim()
if (-not (AzTry monitor app-insights component show -a $n.ai -g $RG -o none)) {
  Az monitor app-insights component create -a $n.ai -g $RG -l $Region --workspace $lawId --kind web -o none
}
$aiConn = (Az monitor app-insights component show -a $n.ai -g $RG --query connectionString -o tsv).Trim()

Step "5. Function App (Python 3.12, Consumption, identidad administrada)"
if (-not (AzTry functionapp show -n $n.func -g $RG -o none)) {
  Az functionapp create -n $n.func -g $RG --storage-account $n.st --consumption-plan-location $Region `
    --runtime python --runtime-version 3.12 --functions-version 4 --os-type Linux `
    --app-insights $n.ai --assign-identity '[system]' -o none
}
$principal = (Az functionapp identity show -n $n.func -g $RG --query principalId -o tsv).Trim()
$funcHost = (Az functionapp show -n $n.func -g $RG --query defaultHostName -o tsv).Trim()

Step "6. Key Vault y secretos"
if (-not (AzTry keyvault show -n $n.kv -g $RG -o none)) { Az keyvault create -n $n.kv -g $RG -l $Region --enable-rbac-authorization true -o none }
$kvId = (Az keyvault show -n $n.kv -g $RG --query id -o tsv).Trim()
$me = (Az ad signed-in-user show --query id -o tsv).Trim()
[void](AzTry role assignment create --assignee-object-id $me --assignee-principal-type User --role 'Key Vault Secrets Officer' --scope $kvId -o none)
[void](AzTry role assignment create --assignee-object-id $principal --assignee-principal-type ServicePrincipal --role 'Key Vault Secrets User' --scope $kvId -o none)
Start-Sleep 30   # propagación de RBAC
if (-not $out.operatorToken) { $out.operatorToken = -join ((48..57) + (65..90) + (97..122) | Get-Random -Count 40 | ForEach-Object { [char]$_ }) }
$secrets = @{ 'cosmos-connection' = $cosmosConn; 'servicebus-connection' = $sbConn; 'operator-token' = $out.operatorToken }
foreach ($k in $secrets.Keys) { Az keyvault secret set --vault-name $n.kv -n $k --value $secrets[$k] -o none }

function Setting($secretName, $value) {
  if ($NoKeyVaultRefs) { return $value }
  return "@Microsoft.KeyVault(SecretUri=https://$($n.kv).vault.azure.net/secrets/$secretName/)"
}

Step "7. Communication Services + Email (si falla, queda email simulado)"
$acsConn = ''; $acsSender = ''
try {
  if (-not (AzTry communication show -n $n.acs -g $RG -o none)) { Az communication create -n $n.acs -g $RG --location global --data-location unitedstates -o none }
  if (-not (AzTry communication email show -n $n.email -g $RG -o none)) { Az communication email create -n $n.email -g $RG --location global --data-location unitedstates -o none }
  if (-not (AzTry communication email domain show --domain-name AzureManagedDomain --email-service-name $n.email -g $RG -o none)) {
    Az communication email domain create --domain-name AzureManagedDomain --email-service-name $n.email -g $RG --location global --domain-management AzureManaged -o none
  }
  $domId = (Az communication email domain show --domain-name AzureManagedDomain --email-service-name $n.email -g $RG --query id -o tsv).Trim()
  $fromDomain = (Az communication email domain show --domain-name AzureManagedDomain --email-service-name $n.email -g $RG --query mailFromSenderDomain -o tsv).Trim()
  Az communication update -n $n.acs -g $RG --linked-domains $domId -o none
  $acsConn = (Az communication list-key --name $n.acs -g $RG --query primaryConnectionString -o tsv).Trim()
  $acsSender = "DoNotReply@$fromDomain"
  Az keyvault secret set --vault-name $n.kv -n 'acs-connection' --value $acsConn -o none
  Write-Host "ACS listo. Remitente: $acsSender"
} catch {
  Write-Host "ACS no se pudo automatizar ($($_.Exception.Message.Split("`n")[0])). Email queda SIMULADO; se puede completar desde el portal luego." -ForegroundColor Yellow
}

Step "8. App settings de la Function App"
$settings = @(
  "COSMOS=$(Setting 'cosmos-connection' $cosmosConn)", "SB=$(Setting 'servicebus-connection' $sbConn)",
  "OPERATOR_TOKEN=$(Setting 'operator-token' $out.operatorToken)", "COSMOS_DB=pulsored",
  "USERS_THRESHOLD=10", "OPERATOR_WAIT_MIN=120", "RECOVERY_POLL_MIN=5", "COOLDOWN_MIN=30"
)
if ($acsConn) { $settings += "ACS_CONNECTION_STRING=$(Setting 'acs-connection' $acsConn)"; $settings += "ACS_SENDER=$acsSender" }
Az functionapp config appsettings set -n $n.func -g $RG --settings @settings -o none

if (-not $SkipBackend) {
  Step "9. Publicar backend"
  Push-Location (Join-Path $root 'backend')
  try {
    $ErrorActionPreference = 'Continue'
    & func azure functionapp publish $n.func --python
    $code = $LASTEXITCODE; $ErrorActionPreference = 'Stop'
    if ($code -ne 0) { throw 'func publish falló' }
  } finally { Pop-Location }
}

Step "10. Frontend (Static Web Apps, plan Free)"
$swaHost = ''
if (-not $SkipFrontend) {
  if (-not (AzTry staticwebapp show -n $n.swa -g $RG -o none)) { Az staticwebapp create -n $n.swa -g $RG -l $Region --sku Free -o none }
  $swaHost = (Az staticwebapp show -n $n.swa -g $RG --query defaultHostname -o tsv).Trim()
  $tmp = Join-Path $env:TEMP "pulsored-web-$Suffix"
  if (Test-Path $tmp) { Remove-Item $tmp -Recurse -Force }
  Copy-Item (Join-Path $root 'frontend') $tmp -Recurse
  @{ apiBase = "https://$funcHost" } | ConvertTo-Json | Set-Content (Join-Path $tmp 'config.json') -Encoding utf8
  $tok = (Az staticwebapp secrets list -n $n.swa -g $RG --query properties.apiKey -o tsv).Trim()
  $ErrorActionPreference = 'Continue'
  & swa deploy $tmp --deployment-token $tok --env production
  $code = $LASTEXITCODE; $ErrorActionPreference = 'Stop'
  if ($code -ne 0) { throw 'swa deploy falló' }
  [void](AzTry functionapp cors add -n $n.func -g $RG --allowed-origins "https://$swaHost" -o none)
}

Step "11. Llave de función (para AWS) y salidas"
$fkey = (Az functionapp keys list -n $n.func -g $RG --query functionKeys.default -o tsv).Trim()
$out.resourceGroup = $RG; $out.region = $Region; $out.suffix = $Suffix; $out.names = $n
$out.apiBase = "https://$funcHost"; $out.siteUrl = if ($swaHost) { "https://$swaHost" } else { '' }
$out.infraEventsUrl = "https://$funcHost/api/infra/events"; $out.functionKey = $fkey
$out.acsSender = $acsSender
($out | ConvertTo-Json -Depth 5) | Set-Content $outFile -Encoding utf8

Write-Host "`nLISTO." -ForegroundColor Green
Write-Host "API:        https://$funcHost/api/health"
Write-Host "Sitio:      $($out.siteUrl)"
Write-Host "Eventos AWS: $($out.infraEventsUrl)   (llave en infra\outputs.local.json -> functionKey)"
Write-Host "Siguiente:  .\infra\smoke_test.ps1"
