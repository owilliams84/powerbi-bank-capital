# Publishes the semantic model and the report to a Power BI workspace via the Fabric REST API.
#
#   powershell -File etl/publish_to_service.ps1 -WorkspaceId <guid>
#   powershell -File etl/publish_to_service.ps1 -WorkspaceId <guid> -SkipRefresh
#
# Works against a personal ("My workspace") as well as a shared one - the Fabric item APIs accept
# a workspace of type Personal, which is not obvious from the documentation.
#
# The model reads its CSVs from raw.githubusercontent over anonymous HTTPS, so the published
# dataset refreshes in the Service with no on-premises gateway. That is the whole reason the data
# is committed to the repo.
#
# Auth comes from the Azure CLI: `az login` first, as the account that owns the workspace.

param(
    [Parameter(Mandatory = $true)][string]$WorkspaceId,
    [string]$Name = "Bank Capital",
    [switch]$SkipRefresh
)

$ErrorActionPreference = "Stop"
$ROOT = Split-Path $PSScriptRoot -Parent
$FABRIC = "https://api.fabric.microsoft.com"
$PBI = "https://analysis.windows.net/powerbi/api"

function Get-Parts {
    <#
      Builds the definition parts array.

      Paths MUST use forward slashes - the Fabric API rejects the backslashes Windows produces
      with a MissingDefinitionParts error that names no part, which is very hard to diagnose.
    #>
    param([string]$Folder, [string[]]$Exclude = @())
    $folderFull = (Get-Item $Folder).FullName
    $parts = @()
    Get-ChildItem -Path $folderFull -Recurse -File -Force | ForEach-Object {
        $rel = $_.FullName.Substring($folderFull.Length + 1).Replace('\', '/')
        foreach ($x in $Exclude) { if ($rel -like $x) { return } }
        $parts += [ordered]@{
            path        = $rel
            payload     = [Convert]::ToBase64String([IO.File]::ReadAllBytes($_.FullName))
            payloadType = "InlineBase64"
        }
    }
    return $parts
}

function Find-Item {
    param([string]$Kind, [string]$DisplayName)
    return (& az rest --method get --resource $FABRIC `
        --url "$FABRIC/v1/workspaces/$WorkspaceId/$Kind" `
        --query "value[?displayName=='$DisplayName'] | [0].id" -o tsv 2>$null)
}

function Publish-Item {
    <#
      Create or update, then wait for the item to actually exist.

      Creation is asynchronous and `az rest` does not surface the x-ms-operation-id header without
      --verbose, so there is no operation to poll. Polling for the item itself is both simpler and
      more honest: query until it appears. Without the wait the script reports failure while the
      create is still running - and a retry then produces a duplicate item with the same name.
    #>
    param([string]$Kind, [string]$DisplayName, $Parts)
    $existing = Find-Item -Kind $Kind -DisplayName $DisplayName
    $body = Join-Path $env:TEMP "publish-$Kind.json"
    try {
        if ($existing) {
            Write-Host "  $Kind '$DisplayName' exists ($existing) - updating definition"
            @{ definition = @{ parts = $Parts } } | ConvertTo-Json -Depth 6 -Compress |
                Set-Content $body -Encoding utf8
            $url = "$FABRIC/v1/workspaces/$WorkspaceId/$Kind/$existing/updateDefinition"
        } else {
            Write-Host "  creating $Kind '$DisplayName'"
            @{ displayName = $DisplayName; definition = @{ parts = $Parts } } |
                ConvertTo-Json -Depth 6 -Compress | Set-Content $body -Encoding utf8
            $url = "$FABRIC/v1/workspaces/$WorkspaceId/$Kind"
        }
        $prev = $ErrorActionPreference
        $ErrorActionPreference = "Continue"
        $out = & az rest --method post --resource $FABRIC --url $url `
            --headers "Content-Type=application/json" --body "@$body" 2>&1 | Out-String
        $ErrorActionPreference = $prev
        if ($out -match '"errorCode"|"message"\s*:\s*"[^"]*[Ee]rror') {
            throw "$Kind publish rejected: $out"
        }
        if ($existing) {
            # updateDefinition is asynchronous too; give it a moment before anything downstream
            # (credentials, refresh) queries the item.
            Start-Sleep -Seconds 10
            return $existing
        }

        # Five minutes, not two. A report with 65 parts routinely takes over two minutes to
        # appear, and a premature "did not appear" is worse than a slow success: the obvious
        # response is to run the script again, and that creates a second item with the same name.
        for ($i = 0; $i -lt 100; $i++) {
            Start-Sleep -Seconds 3
            $id = Find-Item -Kind $Kind -DisplayName $DisplayName
            if ($id) { return $id }
        }
        throw "$Kind '$DisplayName' did not appear within 5 minutes. Check the workspace before " +
              "re-running - the create may still be in flight, and a second run would duplicate it."
    } finally {
        Remove-Item $body -ErrorAction SilentlyContinue
    }
}

# ---------------------------------------------------------------- semantic model
Write-Output "Semantic model"
$modelParts = Get-Parts -Folder (Join-Path $ROOT "$Name.SemanticModel") `
    -Exclude @(".pbi/*", "*/.pbi/*", "*cache.abf", "*localSettings.json", "diagramLayout.json")
Write-Output "  $($modelParts.Count) parts"
$modelId = Publish-Item -Kind "semanticModels" -DisplayName $Name -Parts $modelParts
Write-Output "  semanticModelId = $modelId"

# ---------------------------------------------------------------- report
# The local definition.pbir uses byPath so the PBIP opens in Desktop; the Fabric API rejects
# byPath, so the parts are built from a temp copy with byConnection swapped in. The repo keeps its
# local form and is never left in a state that only works against the Service.
Write-Output "Report"
$staging = Join-Path $env:TEMP "publish-report-staging"
if (Test-Path $staging) { Remove-Item -Recurse -Force $staging }
Copy-Item -Recurse (Join-Path $ROOT "$Name.Report") $staging
# $env:TEMP is an 8.3 short path (C:\Users\OMARWI~1\...) while FullName is the long form, so the
# two differ in length. Re-reading the long form here is what stops Get-Parts trimming the wrong
# number of characters and leaving a fragment of the folder name on every part.
$staging = (Get-Item $staging).FullName
Get-ChildItem -Path $staging -Recurse -Force -Directory |
    Where-Object { $_.Name -eq ".pbi" } | Remove-Item -Recurse -Force -ErrorAction SilentlyContinue

# WriteAllText with a BOM-less encoder on purpose: Windows PowerShell's `Set-Content -Encoding
# utf8` prepends a byte-order mark, and the Fabric API then fails to parse the part - reporting it
# as MissingDefinitionParts: definition.pbir, which sends you looking for a file that is present.
$pbir = @{
    '$schema'        = "https://developer.microsoft.com/json-schemas/fabric/item/report/definitionProperties/2.0.0/schema.json"
    version          = "4.0"
    datasetReference = @{ byConnection = @{ connectionString = "semanticmodelid=$modelId" } }
} | ConvertTo-Json -Depth 5
[IO.File]::WriteAllText((Join-Path $staging "definition.pbir"), $pbir, (New-Object Text.UTF8Encoding($false)))

$reportParts = Get-Parts -Folder $staging -Exclude @("*localSettings.json")
Write-Output "  $($reportParts.Count) parts"
$reportId = Publish-Item -Kind "reports" -DisplayName $Name -Parts $reportParts
Write-Output "  reportId = $reportId"
Remove-Item -Recurse -Force $staging -ErrorAction SilentlyContinue

# ---------------------------------------------------------------- credentials
# Each partition is a literal per-file URL, so the dataset registers one Web datasource per CSV.
# They all need anonymous credentials set before the first refresh, or it fails with
# "credentials not specified".
Write-Output "Datasource credentials"
$sources = & az rest --method get --resource $PBI `
    --url "https://api.powerbi.com/v1.0/myorg/datasets/$modelId/datasources" `
    --query "value[].{id:datasourceId,gw:gatewayId,url:connectionDetails.url}" -o json 2>$null | ConvertFrom-Json
if (-not $sources) {
    Write-Output "  none reported yet (the dataset may still be provisioning)"
} else {
    $cred = (@{ credentialData = @() } | ConvertTo-Json -Compress)
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
        $prev = $ErrorActionPreference; $ErrorActionPreference = "Continue"
        & az rest --method patch --resource $PBI `
            --url "https://api.powerbi.com/v1.0/myorg/gateways/$($s.gw)/datasources/$($s.id)" `
            --headers "Content-Type=application/json" --body "@$patch" 2>&1 | Out-Null
        $ErrorActionPreference = $prev
        Remove-Item $patch -ErrorAction SilentlyContinue
        Write-Output "  anonymous -> $($s.url)"
    }
}

# ---------------------------------------------------------------- refresh
if (-not $SkipRefresh) {
    Write-Output "Refresh"
    $prev = $ErrorActionPreference; $ErrorActionPreference = "Continue"
    & az rest --method post --resource $PBI `
        --url "https://api.powerbi.com/v1.0/myorg/datasets/$modelId/refreshes" `
        --headers "Content-Type=application/json" --body '{\"notifyOption\":\"NoNotification\"}' 2>&1 | Out-Null
    $ErrorActionPreference = $prev
    for ($i = 0; $i -lt 40; $i++) {
        Start-Sleep -Seconds 6
        $r = & az rest --method get --resource $PBI `
            --url "https://api.powerbi.com/v1.0/myorg/datasets/$modelId/refreshes?`$top=1" `
            --query "value[0].{status:status,end:endTime,error:serviceExceptionJson}" -o json 2>$null | ConvertFrom-Json
        if (-not $r) { continue }
        if ($r.status -eq "Completed") { Write-Output "  refresh completed $($r.end)"; break }
        if ($r.status -eq "Failed") { throw "refresh failed: $($r.error)" }
    }
}

Write-Output ""
Write-Output "Published to workspace $WorkspaceId"
Write-Output "  model  $modelId"
Write-Output "  report $reportId"
