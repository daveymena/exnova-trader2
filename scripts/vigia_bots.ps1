# Vigia: relanza lo que se haya caido, por ejemplo tras un reinicio del servidor.
# No relanza el bot real si alcanzo un tope (bot\data\REAL_FINALIZADO) o si se pidio
# detenerlo (bot\data\PARAR_REAL). Tarea programada: BotsIQ_Vigia, cada 5 min.
$raiz = 'C:\Users\Administrator\Documents\trading\exnova-trader2'
Set-Location $raiz
$env:PYTHONIOENCODING = 'utf-8'
$d = Join-Path $raiz 'bot\data'
$py = Join-Path $raiz '.venv\Scripts\python.exe'
$sello = (Get-Date).ToString('yyyyMMdd_HHmmss')

function Anotar($texto) { "$((Get-Date).ToUniversalTime().ToString('yyyy-MM-dd HH:mm:ss')) UTC $texto" | Out-File (Join-Path $d 'vigia.log') -Append -Encoding utf8 }

function Vivo($patron) {
    return @(Get-CimInstance Win32_Process -Filter "Name like 'python%'" | Where-Object { $_.CommandLine -match $patron }).Count -gt 0
}

function Lanzar($nombre, $argumentos) {
    $p = Start-Process $py -ArgumentList $argumentos -WorkingDirectory $raiz -WindowStyle Hidden -PassThru `
        -RedirectStandardOutput (Join-Path $d "$nombre.$sello.out.log") -RedirectStandardError (Join-Path $d "$nombre.$sello.err.log")
    Anotar "lanzado $nombre pid $($p.Id)"
}

$detenido = (Test-Path (Join-Path $d 'REAL_FINALIZADO')) -or (Test-Path (Join-Path $d 'PARAR_REAL'))
if (-not $detenido -and -not (Vivo 'scripts.gemma_live.*--real')) {
    # Tanda de 5 operaciones, se detiene en la primera perdida; REAL_OPS guarda las ya hechas
    $cuenta = Join-Path $d 'REAL_OPS'
    $hechas = if (Test-Path $cuenta) { [int](Get-Content $cuenta -Raw) } else { 0 }
    Lanzar 'gemma_real' @('-u', 'scripts\gemma_live.py', '--real', '--confirmo-real', '--amount', '2', '--max-open', '1',
        '--max-ops', '5', '--ops-hechas', "$hechas", '--parar-al-perder', '--con-madrugada',
        '--stop-perdida', '10', '--stop-ganancia', '20', '--saldo-base', '89.83')
}
if (-not (Vivo 'scripts.ciclo_mejora')) { Lanzar 'ciclo_mejora' @('-u', 'scripts\ciclo_mejora.py') }
if (-not (Vivo 'scripts.medir_gemma')) { Lanzar 'valor_gemma' @('-u', 'scripts\medir_gemma.py', '--bucle') }
