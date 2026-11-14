param([string]$Database='olist_dw',[string]$User='postgres',[string]$HostName='localhost',[int]$Port=5432,[switch]$ReportsOnly)
$ErrorActionPreference='Stop'
# Read literal KEY=VALUE settings; never execute the contents of .env.
$connection=@{}
$envFile=Join-Path $PSScriptRoot '.env'
if(Test-Path -LiteralPath $envFile){
  foreach($line in Get-Content -LiteralPath $envFile){
    if($line -match '^\s*(PGHOST|PGPORT|PGDATABASE|PGUSER|PGPASSWORD)\s*=(.*)$'){
      $key=$Matches[1]
      $value=$Matches[2].Trim()
      if($value.Length -ge 2 -and (($value.StartsWith('"') -and $value.EndsWith('"')) -or ($value.StartsWith("'") -and $value.EndsWith("'")))){
        $value=$value.Substring(1,$value.Length-2)
      }
      $connection[$key]=$value
    }
  }
}
if(-not $PSBoundParameters.ContainsKey('Database') -and $connection['PGDATABASE']){ $Database=$connection['PGDATABASE'] }
if(-not $PSBoundParameters.ContainsKey('User') -and $connection['PGUSER']){ $User=$connection['PGUSER'] }
if(-not $PSBoundParameters.ContainsKey('HostName') -and $connection['PGHOST']){ $HostName=$connection['PGHOST'] }
if(-not $PSBoundParameters.ContainsKey('Port') -and $connection['PGPORT']){ $Port=[int]$connection['PGPORT'] }
$psql=Join-Path 'C:\Program Files\PostgreSQL\18\bin' 'psql.exe'
if (-not (Test-Path $psql)) { $psql=(Get-Command psql -ErrorAction Stop).Source }
Push-Location $PSScriptRoot
$previousPassword=$env:PGPASSWORD
try {
  if($connection['PGPASSWORD']){ $env:PGPASSWORD=$connection['PGPASSWORD'] }
  if($ReportsOnly){
    & $psql -X -v ON_ERROR_STOP=1 -U $User -h $HostName -p $Port -d $Database -f sql/04_views.sql
    if($LASTEXITCODE -ne 0){throw 'Reporting update failed'}
    & $psql -X -v ON_ERROR_STOP=1 -U $User -h $HostName -p $Port -d $Database -f sql/05_validate.sql
    if($LASTEXITCODE -ne 0){throw 'Warehouse validation failed'}
    return
  }
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
  if($LASTEXITCODE -ne 0){throw 'Warehouse validation failed'}
} finally {
  $env:PGPASSWORD=$previousPassword
  Pop-Location
}
