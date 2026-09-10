# Parses the TMDL semantic model with the same serializer Power BI Desktop uses, and prints
# the exact TmdlFormatException (document + line number) when it fails.
#
# Worth having, because Desktop's own failure mode for a malformed TMDL folder is to open a
# blank "Untitled" window with no error dialog at all - which looks identical to a slow load.
#
#   powershell -File etl/check_tmdl.ps1

$ErrorActionPreference = "Stop"
$pkg = (Get-AppxPackage -Name "*PowerBIDesktop*").InstallLocation
$bin = Join-Path $pkg "bin"

foreach ($d in @(
    "Microsoft.AnalysisServices.Server.Core.dll",
    "Microsoft.AnalysisServices.Server.Tabular.dll",
    "Microsoft.AnalysisServices.Server.Tabular.Json.dll")) {
    [void][Reflection.Assembly]::LoadFrom((Join-Path $bin $d))
}
# TmdlSerializer lives in Microsoft.PowerBI.Tabular.dll, not in the AnalysisServices assemblies.
$a = [Reflection.Assembly]::LoadFrom((Join-Path $bin "Microsoft.PowerBI.Tabular.dll"))
$t = $a.GetType("Microsoft.AnalysisServices.Tabular.TmdlSerializer")

$folder = Join-Path $PSScriptRoot "..\Bank Capital.SemanticModel\definition"
$folder = (Resolve-Path $folder).Path

try {
    $db = $t.GetMethod("DeserializeDatabaseFromFolder", [Type[]]@([string])).Invoke($null, @($folder))
    Write-Output "TMDL OK - database '$($db.Name)', $($db.Model.Tables.Count) tables"
    foreach ($tbl in $db.Model.Tables) {
        Write-Output ("  {0,-16} columns={1,-3} measures={2}" -f $tbl.Name, $tbl.Columns.Count, $tbl.Measures.Count)
    }
    Write-Output "  relationships=$($db.Model.Relationships.Count)"
    exit 0
} catch {
    $e = $_.Exception
    while ($e.InnerException) { $e = $e.InnerException }
    Write-Output "TMDL PARSE FAILED"
    Write-Output $e.Message
    exit 1
}
