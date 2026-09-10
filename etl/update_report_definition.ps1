# Pushes the local PBIR to an existing published report and proves it landed.
#
#   powershell -File etl/update_report_definition.ps1 -WorkspaceId <guid> -ReportId <guid> -ModelId <guid>
#
# updateDefinition is asynchronous and returns 202 with no body, so "no error" is not evidence
# of anything. A publish that silently did not apply looks exactly like a Service render cache,
# and the only way to tell them apart is to read the definition back out and diff a part of it -
# which is what this does.

param(
    [Parameter(Mandatory = $true)][string]$WorkspaceId,
    [Parameter(Mandatory = $true)][string]$ReportId,
    [Parameter(Mandatory = $true)][string]$ModelId,
    [string]$Name = "Bank Capital",
    [string]$ProbePart = "definition/pages/pgOverview/visuals/vStandOvr/visual.json"
)

$ErrorActionPreference = "Continue"
$FABRIC = "https://api.fabric.microsoft.com"
$ROOT = Split-Path $PSScriptRoot -Parent
$sep = [char]92

$staging = Join-Path $env:TEMP "bankcap-report-update"
if (Test-Path $staging) { Remove-Item -Recurse -Force $staging }
Copy-Item -Recurse (Join-Path $ROOT "$Name.Report") $staging
# $env:TEMP is an 8.3 short path while FullName is the long form, so re-read it: the lengths
# differ and Substring would otherwise trim the wrong number of characters off every part path.
$staging = (Get-Item $staging).FullName
Get-ChildItem -Path $staging -Recurse -Force -Directory |
    Where-Object { $_.Name -eq ".pbi" } | Remove-Item -Recurse -Force -ErrorAction SilentlyContinue

# byConnection for the Service; the repo keeps byPath so the PBIP still opens in Desktop.
# WriteAllText with a BOM-less encoder: Set-Content -Encoding utf8 prepends a BOM and the API
# then reports the part as missing.
$pbir = @{
    '$schema'        = "https://developer.microsoft.com/json-schemas/fabric/item/report/definitionProperties/2.0.0/schema.json"
    version          = "4.0"
    datasetReference = @{ byConnection = @{ connectionString = "semanticmodelid=$ModelId" } }
} | ConvertTo-Json -Depth 5
[IO.File]::WriteAllText((Join-Path $staging "definition.pbir"), $pbir, (New-Object Text.UTF8Encoding($false)))

$parts = @()
Get-ChildItem -Path $staging -Recurse -File -Force | ForEach-Object {
    $rel = $_.FullName.Substring($staging.Length + 1).Replace($sep, '/')
    if ($rel -like "*localSettings.json") { return }
    $parts += [ordered]@{
        path        = $rel
        payload     = [Convert]::ToBase64String([IO.File]::ReadAllBytes($_.FullName))
        payloadType = "InlineBase64"
    }
}
Write-Output "$($parts.Count) parts"

$local = $parts | Where-Object { $_.path -eq $ProbePart }
if (-not $local) { throw "probe part $ProbePart not found locally" }
$localProbe = $local.payload

$body = Join-Path $env:TEMP "bankcap-update-body.json"
@{ definition = @{ parts = $parts } } | ConvertTo-Json -Depth 6 -Compress |
    Set-Content $body -Encoding utf8

& az rest --method post --resource $FABRIC `
    --url "$FABRIC/v1/workspaces/$WorkspaceId/reports/$ReportId/updateDefinition" `
    --headers "Content-Type=application/json" --body "@$body" 2>&1 | Out-String | Write-Output
Remove-Item $body -ErrorAction SilentlyContinue

Write-Output "reading the definition back..."
for ($i = 0; $i -lt 30; $i++) {
    Start-Sleep -Seconds 10
    $out = Join-Path $env:TEMP "bankcap-getdef.json"
    & az rest --method post --resource $FABRIC `
        --url "$FABRIC/v1/workspaces/$WorkspaceId/reports/$ReportId/getDefinition" `
        --query "definition.parts[?path=='$ProbePart'].payload | [0]" -o tsv 2>$null |
        Set-Content $out -Encoding ascii
    $remote = (Get-Content $out -Raw -ErrorAction SilentlyContinue)
    Remove-Item $out -ErrorAction SilentlyContinue
    if ($remote) { $remote = $remote.Trim() }
    if ($remote -eq $localProbe) {
        Write-Output "MATCH after $(($i + 1) * 10)s - the published definition is the local one"
        Remove-Item -Recurse -Force $staging -ErrorAction SilentlyContinue
        exit 0
    }
    Write-Output "  not yet ($([int]($remote.Length)) vs $([int]($localProbe.Length)) chars)"
}
Write-Output "definition still differs after 5 minutes"
exit 1
