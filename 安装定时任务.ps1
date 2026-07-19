$TaskName = "JobAgent_AutoDailyReport"
$ScriptPath = Join-Path $PSScriptRoot "启动自动日报.bat"
$Action = New-ScheduledTaskAction -Execute $ScriptPath
$Trigger = New-ScheduledTaskTrigger -Daily -At 8am
$Principal = New-ScheduledTaskPrincipal -UserId "$env:USERNAME" -RunLevel Highest
$Settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries
Register-ScheduledTask -TaskName $TaskName -Action $Action -Trigger $Trigger -Principal $Principal -Settings $Settings -Force
Write-Host "定时任务已安装！每天 08:00 自动运行日报。"
Write-Host "任务名: $TaskName"
