
$Computer = "ELH-SL-11179"
$LocalUpgradeScript = "C:\scripts\Win11-upgrade.ps1"   # your already-built script
$LocalISO = "c:\iso\SW_DVD9_Win_Pro_11_22H2.26_64BIT_English_Pro_Ent_EDU_N_MLF_X23-92698.ISO"                        # source ISO

# 1) Open a remoting session
$session = New-PSSession -ComputerName $Computer

# 2) Stage files on the remote laptop
Invoke-Command -Session $session -ScriptBlock { New-Item -ItemType Directory -Path "C:\Temp" -Force | Out-Null }
Copy-Item $LocalUpgradeScript -Destination "C:\Temp\Win11-Upgrade.ps1" -ToSession $session
Copy-Item $LocalISO           -Destination "C:\Temp\Win11.iso" -ToSession $session

# 3) Create a scheduled task that runs as SYSTEM and starts in 5 minutes
Invoke-Command -Session $session -ScriptBlock {
  $action = New-ScheduledTaskAction -Execute "powershell.exe" -Argument '-ExecutionPolicy Bypass -File "C:\Temp\Win11-Upgrade.ps1" -Source "C:\Temp\Win11.iso"'
  $trigger = New-ScheduledTaskTrigger -Once -At (Get-Date).AddMinutes(5)
  $principal = New-ScheduledTaskPrincipal -UserId "SYSTEM" -RunLevel Highest
  Register-ScheduledTask -TaskName "Win11Upgrade" -Action $action -Trigger $trigger -Principal $principal -Force | Out-Null
  Start-ScheduledTask -TaskName "Win11Upgrade"
  "Task created and started."
}

# Watch progress / logs later
# Invoke-Command -Session $session -ScriptBlock { Get-Content C:\Windows11-Upgrade.log -Tail 200 -Wait }
