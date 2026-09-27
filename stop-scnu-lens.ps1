# SCNU Lens 백엔드(8001)·프론트(3000)를 끈다. 자동 실행 등록은 그대로 둔다.
#   자동 실행까지 없애려면: Unregister-ScheduledTask -TaskName "SCNU Lens" -Confirm:$false

foreach ($port in 8001, 3000) {
    $owner = Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue | Select-Object -First 1 -ExpandProperty OwningProcess
    if ($owner) {
        # 프론트는 cmd → npm → node로 이어져 있어 자식까지 함께 끈다.
        & taskkill.exe /PID $owner /T /F | Out-Null
        Write-Output "포트 $port 종료"
    }
}
