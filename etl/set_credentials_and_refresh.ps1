# Sets anonymous credentials on every Web datasource of a published dataset, then refreshes it.
#
#   powershell -File etl/set_credentials_and_refresh.ps1 -ModelId <guid>
#
# Split out of publish_to_service.ps1 because the datasources endpoint returns 404 for up to a
# minute or two after a definition lands - the dataset is still provisioning, not missing - and
# an updateDefinition restarts that clock. Retrying is the whole job.
#
# Every partition is a literal per-file raw.githubusercontent URL, so the dataset registers one
# Web datasource per CSV (18 of them here). All of them need anonymous credentials before the
# first refresh, or it fails with "credentials not specified".

param(
    [Parameter(Mandatory = $true)][string]$ModelId,
    [int]$MaxWaitSeconds = 600
)

$PBI = "https://analysis.windows.net/powerbi/api"
$ErrorActionPreference = "Continue"

$sources = $null
$deadline = (Get-Date).AddSeconds($MaxWaitSeconds)
while ((Get-Date) -lt $deadline) {
    $raw = & az rest --method get --resource $PBI `
        --url "https://api.powerbi.com/v1.0/myorg/datasets/$ModelId/datasources" `
        --query "value[].{id:datasourceId,gw:gatewayId,url:connectionDetails.url}" -o json 2>$null
    if ($raw) {
        $sources = $raw | ConvertFrom-Json
        if ($sources) { break }
    }
    Write-Output "  datasources not ready yet, waiting..."
    Start-Sleep -Seconds 15
}
if (-not $sources) { throw "datasources never appeared for $ModelId" }
Write-Output "$($sources.Count) datasources"

$cred = (@{ credentialData = @() } | ConvertTo-Json -Compress)
$patched = 0
foreach ($s in $sources) {
    $patch = Join-Path $env:TEMP "cred.json"
    @{
        credentialDetails = @{
            credentialType      = "Anonymous"
            credentials         = $cred
            encryptedConnection = "NotEncrypted"
            encryptionAlgorithm = "None"
            privacyLevel        = "Public"
        }
    } | ConvertTo-Json -Depth 5 | Set-Content $patch -Encoding utf8
    & az rest --method patch --resource $PBI `
        --url "https://api.powerbi.com/v1.0/myorg/gateways/$($s.gw)/datasources/$($s.id)" `
        --headers "Content-Type=application/json" --body "@$patch" 2>&1 | Out-Null
    Remove-Item $patch -ErrorAction SilentlyContinue
    $patched++
}
Write-Output "anonymous credentials set on $patched datasources"

Write-Output "Refresh"
& az rest --method post --resource $PBI `
    --url "https://api.powerbi.com/v1.0/myorg/datasets/$ModelId/refreshes" `
    --headers "Content-Type=application/json" --body '{\"notifyOption\":\"NoNotification\"}' 2>&1 | Out-Null

for ($i = 0; $i -lt 80; $i++) {
    Start-Sleep -Seconds 15
    $r = & az rest --method get --resource $PBI `
        --url "https://api.powerbi.com/v1.0/myorg/datasets/$ModelId/refreshes?`$top=1" `
        --query "value[0].{status:status,end:endTime,error:serviceExceptionJson}" -o json 2>$null |
        ConvertFrom-Json
    if (-not $r) { continue }
    if ($r.status -eq "Completed") { Write-Output "  refresh completed $($r.end)"; exit 0 }
    if ($r.status -eq "Failed") { Write-Output "  refresh FAILED: $($r.error)"; exit 1 }
    if ($i % 4 -eq 0) { Write-Output "  status: $($r.status)" }
}
Write-Output "  refresh still running after 20 minutes"
