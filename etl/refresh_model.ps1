# Refreshes the model inside the running Power BI Desktop over its local XMLA endpoint.
#
# A PBIP opens with its partitions in NoData - the definition loads but no rows do - so the report
# renders as empty containers until this runs. `powerbi-desktop reload` re-applies the model
# definition and wipes the data again, so refresh *after* any reload, never before.
#
#   powershell -File etl/refresh_model.ps1
#
# Run it as a background job if you script around it: closing the ADOMD connection can hang the
# shell for several minutes.

$ErrorActionPreference = "Stop"

# The analysis services engine Desktop hosts listens on a random local port.
$msmdsrv = Get-CimInstance Win32_Process -Filter "Name='msmdsrv.exe'"
if (-not $msmdsrv) { throw "msmdsrv.exe is not running - open the PBIP in Desktop first." }

$port = $null
foreach ($proc in $msmdsrv) {
    $conn = Get-NetTCPConnection -State Listen -OwningProcess $proc.ProcessId -ErrorAction SilentlyContinue |
            Where-Object { $_.LocalAddress -eq "127.0.0.1" } | Select-Object -First 1
    if ($conn) { $port = $conn.LocalPort; break }
}
if (-not $port) { throw "could not find the local XMLA port for msmdsrv.exe" }
Write-Output "XMLA endpoint: localhost:$port"

# Add-Type fails silently on this assembly; LoadFrom is required. Note the mismatch: Desktop 2.157
# ships the file as Microsoft.PowerBI.AdomdClient.dll while the types inside it are still under the
# Microsoft.AnalysisServices.AdomdClient namespace. Older builds ship the AnalysisServices filename,
# so both are tried.
$pkg = (Get-AppxPackage -Name "*PowerBIDesktop*").InstallLocation
$adomd = @("Microsoft.PowerBI.AdomdClient.dll", "Microsoft.AnalysisServices.AdomdClient.dll") |
         ForEach-Object { Join-Path $pkg "bin\$_" } |
         Where-Object { Test-Path $_ } | Select-Object -First 1
if (-not $adomd) { throw "no ADOMD client assembly found in $pkg\bin" }
[void][Reflection.Assembly]::LoadFrom($adomd)

# AdomdConnection.Databases is null here, so the catalog GUID has to come from a DMV. Without an
# Initial Catalog the refresh command fails with "database is not specified".
# The engine starts listening before it has mounted the model, so immediately after Desktop opens a
# file the catalog list is briefly empty. Poll rather than failing on the race.
$catalog = $null
foreach ($attempt in 1..30) {
    try {
        $probe = New-Object Microsoft.AnalysisServices.AdomdClient.AdomdConnection("Data Source=localhost:$port")
        $probe.Open()
        $cmd = $probe.CreateCommand()
        $cmd.CommandText = "SELECT [CATALOG_NAME] FROM `$SYSTEM.DBSCHEMA_CATALOGS"
        $reader = $cmd.ExecuteReader()
        if ($reader.Read()) { $catalog = $reader.GetString(0) }
        $reader.Close()
        $probe.Close()
    } catch { }
    if ($catalog) { break }
    Start-Sleep -Seconds 5
}
if (-not $catalog) { throw "no catalog on localhost:$port after 150s - is the model still loading?" }
Write-Output "Catalog: $catalog"

$conn = New-Object Microsoft.AnalysisServices.AdomdClient.AdomdConnection(
    "Data Source=localhost:$port;Initial Catalog=$catalog")
$conn.Open()
$refresh = $conn.CreateCommand()
$refresh.CommandTimeout = 600
$refresh.CommandText = "{""refresh"":{""type"":""full"",""objects"":[{""database"":""$catalog""}]}}"
$refresh.ExecuteNonQuery() | Out-Null
Write-Output "Refresh complete."

# Prove rows actually landed rather than trusting the command's silence.
$check = $conn.CreateCommand()
$check.CommandText = @"
EVALUATE
ROW(
    "Rows", COUNTROWS('Prudential'),
    "Banks", COUNTROWS('Bank'),
    "Items", COUNTROWS('Item'),
    "Quarters", COUNTROWS('Period'),
    "As at", [As At],
    "CET1 ratio", FORMAT([CET1 Ratio], "0.00%"),
    "Avg of banks", FORMAT([CET1 Ratio, Average of Banks], "0.00%")
)
"@
$r = $check.ExecuteReader()
if ($r.Read()) {
    for ($i = 0; $i -lt $r.FieldCount; $i++) {
        Write-Output ("  {0,-14} {1}" -f $r.GetName($i), $r.GetValue($i))
    }
}
$r.Close()
$conn.Close()
