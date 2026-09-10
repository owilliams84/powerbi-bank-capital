# Runs a DAX query against the model inside the running Power BI Desktop, over its local XMLA
# endpoint, and prints the result as a table.
#
#   powershell -File etl/query_model.ps1 -DaxFile etl\checks\overview.dax
#
# -DaxFile rather than -Dax: inline DAX loses its double quotes passing through
# `powershell -File`, so ROW("x", 1) arrives as ROW(x, 1) and fails to parse.

param(
    [Parameter(Mandatory = $true)][string]$DaxFile,
    [switch]$Csv
)

$ErrorActionPreference = "Stop"

$msmdsrv = Get-CimInstance Win32_Process -Filter "Name='msmdsrv.exe'"
if (-not $msmdsrv) { throw "msmdsrv.exe is not running - open the PBIP in Desktop first." }

$port = $null
foreach ($proc in $msmdsrv) {
    $conn = Get-NetTCPConnection -State Listen -OwningProcess $proc.ProcessId -ErrorAction SilentlyContinue |
            Where-Object { $_.LocalAddress -eq "127.0.0.1" } | Select-Object -First 1
    if ($conn) { $port = $conn.LocalPort; break }
}
if (-not $port) { throw "could not find the local XMLA port for msmdsrv.exe" }

$pkg = (Get-AppxPackage -Name "*PowerBIDesktop*").InstallLocation
$adomd = @("Microsoft.PowerBI.AdomdClient.dll", "Microsoft.AnalysisServices.AdomdClient.dll") |
         ForEach-Object { Join-Path $pkg "bin\$_" } |
         Where-Object { Test-Path $_ } | Select-Object -First 1
[void][Reflection.Assembly]::LoadFrom($adomd)

# The catalog GUID has to come from a DMV; AdomdConnection.Databases is null here.
$catalog = $null
foreach ($attempt in 1..30) {
    try {
        $probe = New-Object Microsoft.AnalysisServices.AdomdClient.AdomdConnection("Data Source=localhost:$port")
        $probe.Open()
        $cmd = $probe.CreateCommand()
        $cmd.CommandText = "SELECT [CATALOG_NAME] FROM `$SYSTEM.DBSCHEMA_CATALOGS"
        $rdr = $cmd.ExecuteReader()
        if ($rdr.Read()) { $catalog = $rdr.GetString(0) }
        $rdr.Close(); $probe.Close()
    } catch { }
    if ($catalog) { break }
    Start-Sleep -Seconds 5
}
if (-not $catalog) { throw "no catalog mounted after 150s - the model has not loaded" }

$dax = [IO.File]::ReadAllText((Resolve-Path $DaxFile).Path)

$cn = New-Object Microsoft.AnalysisServices.AdomdClient.AdomdConnection(
    "Data Source=localhost:$port;Initial Catalog=$catalog")
$cn.Open()
try {
    $cmd = $cn.CreateCommand()
    $cmd.CommandText = $dax
    $cmd.CommandTimeout = 600
    $reader = $cmd.ExecuteReader()
    $cols = @()
    for ($i = 0; $i -lt $reader.FieldCount; $i++) { $cols += $reader.GetName($i) }
    $rows = @()
    while ($reader.Read()) {
        $row = [ordered]@{}
        for ($i = 0; $i -lt $reader.FieldCount; $i++) {
            $row[$cols[$i]] = $reader.GetValue($i)
        }
        $rows += [pscustomobject]$row
    }
    $reader.Close()
    if ($Csv) { $rows | ConvertTo-Csv -NoTypeInformation }
    else { $rows | Format-Table -AutoSize | Out-String -Width 400 }
} finally {
    $cn.Close()
}
