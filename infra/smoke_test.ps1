<#
  Prueba de humo contra el despliegue real. Uso: .\infra\smoke_test.ps1
  Cubre: health, intake idempotente, consulta pública, seguridad, eventos AWS, y 10 usuarios -> incidente -> orquestación.
#>
$ErrorActionPreference = 'Stop'
$o = Get-Content (Join-Path $PSScriptRoot 'outputs.local.json') -Raw | ConvertFrom-Json
$api = $o.apiBase; $tok = $o.operatorToken; $key = $o.functionKey
$run = [int](Get-Date -UFormat %s)
$fail = 0
function Check($name, $cond, $info = '') { if ($cond) { Write-Host "  OK   $name" -ForegroundColor Green } else { Write-Host "  FAIL $name $info" -ForegroundColor Red; $script:fail++ } }
function Call($method, $path, $body = $null, $headers = @{}) {
  try {
    $p = @{ Uri = "$api/api$path"; Method = $method; Headers = $headers; UseBasicParsing = $true; ContentType = 'application/json'; TimeoutSec = 60 }
    if ($body) { $p.Body = ($body | ConvertTo-Json -Depth 5) }
    $r = Invoke-WebRequest @p
    return @{ code = [int]$r.StatusCode; json = ($r.Content | ConvertFrom-Json) }
  } catch {
    $c = 0; $j = $null
    if ($_.Exception.Response) { $c = [int]$_.Exception.Response.StatusCode }
    return @{ code = $c; json = $j }
  }
}
function Report($i, $zone) {
  @{ idempotency_key = "smoke-$run-$i-key"; user_document = ("S{0}{1:D4}" -f ($run % 100000), $i); phone = ("+5197{0:D7}" -f $i); email = "smoke$i@example.com"
     zone_id = $zone; occurred_at = (Get-Date).ToUniversalTime().ToString('o'); problem_type = 'SIN_DATOS'; description = "prueba de humo $i" }
}

Write-Host "`n[1] Salud y seguridad"
$r = Call GET '/health'; Check 'GET /health = 200' ($r.code -eq 200)
Check 'GET /incidents sin token = 401' ((Call GET '/incidents').code -eq 401)
Check 'GET /incidents con token = 200' ((Call GET '/incidents' $null @{ 'x-operator-token' = $tok }).code -eq 200)
Check 'POST /infra/events sin llave = 401' ((Call POST '/infra/events' @{ event_id = 'x' }).code -eq 401)

Write-Host "`n[2] Intake idempotente"
$rep = Report 0 'Z04'
$a = Call POST '/reports' $rep; $b = Call POST '/reports' $rep
Check 'primer POST = 202' ($a.code -eq 202)
Check 'repetido = 200 y mismo id' ($b.code -eq 200 -and $b.json.report_id -eq $a.json.report_id)
$g = Call GET "/reports/$($a.json.report_id)"
Check 'consulta pública = 200 sin PII' ($g.code -eq 200 -and ($g.json | ConvertTo-Json -Depth 6) -notmatch 'smoke0@|S\d{5}0000')
Check 'esquema inválido = 400' ((Call POST '/reports' @{ zone_id = 'Z99' }).code -eq 400)

Write-Host "`n[3] Eventos de AWS (idempotencia)"
$ev = @{ event_id = "smoke-evt-$run"; event_type = 'ANTENNA_DOWN'; antenna_id = 'A-SMOKE'; zone_id = 'Z12'; occurred_at = (Get-Date).ToUniversalTime().ToString('o'); severity = 'HIGH' }
$h = @{ 'x-functions-key' = $key }
Check 'evento nuevo = 202' ((Call POST '/infra/events' $ev $h).code -eq 202)
Check 'evento repetido = 200 duplicate' ((Call POST '/infra/events' $ev $h).code -eq 200)

Write-Host "`n[4] 10 usuarios distintos en Z12 -> incidente colectivo (espera hasta 90 s)"
1..10 | ForEach-Object { Call POST '/reports' (Report (100 + $_) 'Z12') | Out-Null }
$inc = $null
foreach ($i in 1..18) {
  Start-Sleep 5
  $l = Call GET '/incidents?zone_id=Z12' $null @{ 'x-operator-token' = $tok }
  if ($l.code -eq 200 -and $l.json.items.Count -ge 1) { $inc = $l.json.items[0]; break }
}
Check 'incidente creado por el correlador' ($null -ne $inc)
if ($inc) {
  Write-Host "     $($inc.incident_id) usuarios=$($inc.users_affected) prioridad=$($inc.priority_score) ($($inc.priority_level)) origen=$($inc.origin)"
  Check 'usuarios_afectados >= 10' ($inc.users_affected -ge 10)
  Start-Sleep 10
  $d = Call GET "/incidents/$($inc.incident_id)" $null @{ 'x-operator-token' = $tok }
  Check 'IA/reglas aplicada (orquestación corrió)' ($d.code -eq 200 -and $d.json.ai_source)
  Check 'historial presente' ($d.json.history.Count -ge 3)
  Write-Host "     estado=$($d.json.status)  (la orquestación espera al operador o a la antena según el caso)"
}
Write-Host ""
if ($fail -eq 0) { Write-Host "TODO OK" -ForegroundColor Green } else { Write-Host "$fail comprobación(es) fallaron" -ForegroundColor Red; exit 1 }
