# Phase 1: List EVERY running Streamlit process
Write-Host "=========================="
Write-Host "PHASE 1 - Streamlit Processes"
Write-Host "=========================="
Get-WmiObject Win32_Process | Where-Object { $_.CommandLine -match "streamlit" } | Select-Object ProcessId, ExecutablePath, CommandLine, @{Name="StartTime";Expression={$_.ConvertToDateTime($_.CreationDate)}} | Format-List

# Phase 2: List every listening TCP port
Write-Host "=========================="
Write-Host "PHASE 2 - TCP Ports"
Write-Host "=========================="
Get-NetTCPConnection | Where-Object { $_.State -eq 'Listen' -and @(8501, 8502, 5432, 8080, 3000, 8000, 5000) -contains $_.LocalPort } | Select-Object LocalPort, OwningProcess | Format-Table -AutoSize

# Map Process ID to Name
Write-Host "Port Owners:"
$ports = Get-NetTCPConnection | Where-Object { $_.State -eq 'Listen' -and @(8501, 8502, 5432, 8080, 3000, 8000, 5000) -contains $_.LocalPort }
foreach ($p in $ports) {
    $proc = Get-Process -Id $p.OwningProcess -ErrorAction SilentlyContinue
    Write-Host "Port $($p.LocalPort) -> PID $($p.OwningProcess) ($($proc.Name))"
}

# Phase 6: Docker Verification attempt via Process
Write-Host "=========================="
Write-Host "PHASE 6 - Docker Check"
Write-Host "=========================="
Get-Process | Where-Object { $_.Name -match "docker" -or $_.Name -match "postgres" } | Select-Object Id, Name | Format-Table -AutoSize
