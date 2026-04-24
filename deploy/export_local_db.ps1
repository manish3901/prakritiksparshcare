param(
  [string]$HostName = "localhost",
  [int]$Port = 5432,
  [string]$UserName = "postgres",
  [string]$DatabaseName = "psc_db",
  [string]$OutDir = "deploy\\dumps",
  [string]$PgDumpPath = "pg_dump",
  [string]$PgPassword = ""
)

$ErrorActionPreference = "Stop"

New-Item -ItemType Directory -Force -Path $OutDir | Out-Null

if ($PgPassword -ne "") {
  $env:PGPASSWORD = $PgPassword
}

$ts = Get-Date -Format "yyyyMMdd_HHmmss"
$mainOut = Join-Path $OutDir ("psc_main_{0}.dump" -f $ts)
$couponOut = Join-Path $OutDir ("psc_coupon_{0}.dump" -f $ts)

Write-Host "Exporting MAIN PSC tables (excluding coupon tables) -> $mainOut"
& $PgDumpPath -Fc -h $HostName -p $Port -U $UserName -d $DatabaseName `
  --exclude-table="coupon_*" `
  -f $mainOut

Write-Host "Exporting COUPON tables only -> $couponOut"
& $PgDumpPath -Fc -h $HostName -p $Port -U $UserName -d $DatabaseName `
  -t "coupon_*" `
  -f $couponOut

Write-Host ""
Write-Host "Done."
Write-Host "Main dump  : $mainOut"
Write-Host "Coupon dump: $couponOut"

