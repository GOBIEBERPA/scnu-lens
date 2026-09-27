# SCNU Lens 백엔드(8001)·프론트(3000)를 창 없이 켠다. 이미 켜져 있는 것은 건드리지 않는다.
# 로그인할 때 작업 스케줄러("SCNU Lens")가 이 파일을 실행한다. 직접 실행해도 된다.
#   끄기: stop-scnu-lens.ps1
#   로그: logs\backend.log, logs\frontend.log

$root = Split-Path -Parent $MyInvocation.MyCommand.Path
$logs = Join-Path $root "logs"
New-Item -ItemType Directory -Force $logs | Out-Null

function Test-Listening([int]$port) {
    [bool](Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue)
}

if (-not (Test-Listening 8001)) {
    Start-Process -FilePath (Join-Path $root "backend\.venv\Scripts\python.exe") `
        -ArgumentList "-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", "8001" `
        -WorkingDirectory (Join-Path $root "backend") -WindowStyle Hidden `
        -RedirectStandardOutput (Join-Path $logs "backend.log") -RedirectStandardError (Join-Path $logs "backend.err.log")
}

# 이미 빌드해 둔 화면(.next)을 띄운다. 코드를 고쳤으면 frontend에서 npm run build를 먼저 한다.
if (-not (Test-Listening 3000)) {
    Start-Process -FilePath "cmd.exe" -ArgumentList "/c", "npm", "run", "start", "--", "-p", "3000" `
        -WorkingDirectory (Join-Path $root "frontend") -WindowStyle Hidden `
        -RedirectStandardOutput (Join-Path $logs "frontend.log") -RedirectStandardError (Join-Path $logs "frontend.err.log")
}
