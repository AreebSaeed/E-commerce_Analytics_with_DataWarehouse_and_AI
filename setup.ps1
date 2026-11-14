param([string]$Database='olist_dw',[string]$User='postgres',[string]$HostName='localhost',[int]$Port=5432)
$ErrorActionPreference='Stop'
$psql=Join-Path 'C:\Program Files\PostgreSQL\18\bin' 'psql.exe'
if (-not (Test-Path $psql)) { $psql=(Get-Command psql -ErrorAction Stop).Source }
Push-Location $PSScriptRoot
try {
  $geo=Test-Path 'data/raw/olist_geolocation_dataset.csv'
  $geoFlag=if($geo){'true'}else{'false'}
  $exists=& $psql -X -v ON_ERROR_STOP=1 -U $User -h $HostName -p $Port -d postgres -tAc "SELECT 1 FROM pg_database WHERE datname='$Database'"
  if($LASTEXITCODE -ne 0){throw 'Could not connect to PostgreSQL. Check username, password, host, and port.'}
  if(-not $exists){ & $psql -X -v ON_ERROR_STOP=1 -U $User -h $HostName -p $Port -d postgres -c "CREATE DATABASE $Database"; if($LASTEXITCODE -ne 0){throw 'Database creation failed'} }
  & $psql -X -v ON_ERROR_STOP=1 -U $User -h $HostName -p $Port -d $Database -f sql/01_schema.sql
  if($LASTEXITCODE -ne 0){throw 'Schema creation failed'}
  & $psql -X -v ON_ERROR_STOP=1 -v "has_geolocation=$geoFlag" -U $User -h $HostName -p $Port -d $Database -f sql/02_load.sql
  if($LASTEXITCODE -ne 0){throw 'Data load failed'}
  & $psql -X -U $User -h $HostName -p $Port -d $Database -c 'SELECT * FROM meta.etl_log ORDER BY run_id DESC LIMIT 1'
  & $psql -X -v ON_ERROR_STOP=1 -U $User -h $HostName -p $Port -d $Database -f sql/05_validate.sql
} finally { Pop-Location }
