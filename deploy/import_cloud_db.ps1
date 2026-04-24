param(
  [string]$HostName,
  [int]$Port = 5432,
  [string]$UserName,
  [string]$DatabaseName,
  [string]$DumpFile,
  [string]$PgRestorePath = "pg_restore",
  [string]$PgPassword = ""
)

$ErrorActionPreference = "Stop"

if (-not $HostName -or -not $UserName -or -not $DatabaseName -or -not $DumpFile) {
  throw "Usage: import_cloud_db.ps1 -HostName <host> -UserName <user> -DatabaseName <db> -DumpFile <path>"
}

if ($PgPassword -ne "") {
  $env:PGPASSWORD = $PgPassword
}

Write-Host "Importing $DumpFile -> $DatabaseName@$HostName:$Port"

# -c: drop objects before recreating them (fresh restore)
& $PgRestorePath -c -h $HostName -p $Port -U $UserName -d $DatabaseName $DumpFile

Write-Host "Done."

