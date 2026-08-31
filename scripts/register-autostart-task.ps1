# Run once from an elevated PowerShell (right-click -> Run as Administrator).
$action = New-ScheduledTaskAction -Execute "powershell.exe" -Argument "-NoProfile -ExecutionPolicy Bypass -File `"C:\Dev\drugTest\scripts\start-services.ps1`""
$trigger = New-ScheduledTaskTrigger -AtLogOn
$principal = New-ScheduledTaskPrincipal -UserId $env:USERNAME -LogonType Interactive -RunLevel Highest
$settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -StartWhenAvailable
Register-ScheduledTask -TaskName "drugTest-autostart" -Action $action -Trigger $trigger -Principal $principal -Settings $settings -Description "Auto-restart drugtest docker compose + cloudflared at logon"
