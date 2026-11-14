param([string]$Database,[string]$User,[string]$HostName,[int]$Port,[switch]$ReportsOnly)
$ErrorActionPreference='Stop'
$python=Join-Path $PSScriptRoot '.venv/Scripts/python.exe'
if(-not (Test-Path -LiteralPath $python)){
  throw 'Create .venv and install requirements.txt first. See the Python setup section in README.md.'
}
$etlArguments=@((Join-Path $PSScriptRoot 'etl.py'))
if($PSBoundParameters.ContainsKey('Database')){ $etlArguments+=@('--database',$Database) }
if($PSBoundParameters.ContainsKey('User')){ $etlArguments+=@('--user',$User) }
if($PSBoundParameters.ContainsKey('HostName')){ $etlArguments+=@('--host',$HostName) }
if($PSBoundParameters.ContainsKey('Port')){ $etlArguments+=@('--port',"$Port") }
if($ReportsOnly){ $etlArguments+='--reports-only' }
& $python @etlArguments
if($LASTEXITCODE -ne 0){throw 'ETL failed. See the error above and meta.etl_log for details.'}
