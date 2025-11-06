<# 
.SYNOPSIS
  Unattended in-place upgrade from Windows 10 to Windows 11.

.DESCRIPTION
  - Accepts either a path to an ISO file OR a folder/UNC share that contains setup.exe.
  - Performs compatibility checks (TPM 2.0, Secure Boot, disk space, OS).
  - Suspends BitLocker protectors during upgrade.
  - Runs Windows 11 Setup quietly with Dynamic Update enabled.
  - Optionally suppresses automatic reboot (use -NoReboot if you want to control the reboot).
  - Writes a summarized result to C:\Windows11-Upgrade.log and relies on Setup logs too.

.PARAMETER Source
  Path to either a Windows 11 ISO (e.g., C:\ISO\Win11.iso) OR a directory/UNC root that contains setup.exe.

.PARAMETER NoReboot
  If specified, passes /NoReboot to setup so you can reboot on your schedule.

.PARAMETER SkipChecks
  If specified, skips TPM/SecureBoot/disk space checks (NOT recommended). Does NOT set any bypass registry keys.

.EXAMPLE
  .\Win11-upgrade.ps1 -Source "\\fileserver\os\Win11_23H2" 
  .\Win11-upgrade.ps1 -Source "C:\ISO\SW_DVD9_Win_Pro_11_22H2.26_64BIT_English_Pro_Ent_EDU_N_MLF_X23-92698.ISO" -NoReboot

.NOTES
  - Requires Administrator.
  - Ensure language/edition in the media matches the installed OS (to preserve apps/files).
  - Setup logs: C:\$WINDOWS.~BT\Sources\Panther\setuperr.log, setupact.log
#>

[CmdletBinding()]
param(
  [Parameter(Mandatory=$true)]
  [string]$Source,

  [switch]$NoReboot,
  [switch]$SkipChecks
)

#--------------------------- Helper: Logging ---------------------------
$Script:LogFile = 'C:\Windows11-Upgrade.log'
function Write-Log([string]$msg, [string]$level='INFO') {
  $line = "{0} [{1}] {2}" -f (Get-Date -Format s), $level.ToUpper(), $msg
  Write-Host $line
  Add-Content -Path $Script:LogFile -Value $line
}

#--------------------------- Admin check ---------------------------
if (-not ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltinRole]::Administrator)) {
  Write-Host "Please run this script as Administrator." -ForegroundColor Red
  exit 1
}

Write-Log "Starting Windows 11 unattended upgrade script."
Write-Log "Source: $Source"

#--------------------------- OS check ---------------------------
$os = Get-ItemProperty 'HKLM:\SOFTWARE\Microsoft\Windows NT\CurrentVersion'
$build = [int]$os.CurrentBuild
if ($build -lt 19041) {
  Write-Log "Unsupported Windows 10 build ($build). Require 2004/20H2+ for best results." 'WARN'
}

#--------------------------- Compatibility checks ---------------------------
function Test-TPM2 {
  try {
    $tpm = Get-Tpm
    if (-not $tpm -or -not $tpm.TpmPresent -or -not $tpm.TpmReady) { return $false }

    # 1) If SpecVersion is present, trust it
    if ($tpm.PSObject.Properties.Name -contains 'SpecVersion') {
      $sv = ($tpm.SpecVersion -join ',')
      if ($sv -match '\b2\.0\b') { return $true }
    }

    # 2) Win32_Tpm.SpecVersion via CIM
    try {
      $cim = Get-CimInstance -Namespace 'root\cimv2\Security\MicrosoftTpm' -ClassName Win32_Tpm -ErrorAction Stop
      if ($cim.SpecVersion -match '\b2\.0\b') { return $true }
    } catch { }

    # 3) Presence of ManufacturerVersionFull20 is a strong indicator of TPM 2.0
    if ($tpm.PSObject.Properties.Name -contains 'ManufacturerVersionFull20' -and $tpm.ManufacturerVersionFull20) {
      return $true
    }

    return $false
  } catch {
    return $false
  }
}


function Test-SecureBoot {
  try {
    return [bool](Confirm-SecureBootUEFI -ErrorAction Stop)
  } catch {
    # Legacy BIOS or cmdlet not available
    return $false
  }
}

function Get-FreeSpaceGB {
  try {
    $c = Get-PSDrive -Name C -ErrorAction Stop
    return [math]::Round(($c.Free/1GB),1)
  } catch { return 0 }
}

$meetsTPM = Test-TPM2
$meetsSB  = Test-SecureBoot
$freeGB   = Get-FreeSpaceGB
$minGB    = 25

if (-not $SkipChecks) {
  if (-not $meetsTPM) { Write-Log "TPM 2.0 requirement not met." 'ERROR'; exit 0xC1900208 }
  if (-not $meetsSB)  { Write-Log "Secure Boot requirement not met." 'ERROR'; exit 0xC1900208 }
  if ($freeGB -lt $minGB) { Write-Log "Insufficient free space on C:. Have ${freeGB}GB, need >= ${minGB}GB." 'ERROR'; exit 0xC1900200 }
} else {
  Write-Log "SkipChecks specified: bypassing TPM/Secure Boot/disk checks (not recommended)." 'WARN'
}

#--------------------------- Locate/prepare setup.exe ---------------------------
$mounted = $null
$setupPath = $null

if (Test-Path $Source) {
  if ($Source.ToLower().EndsWith('.iso')) {
    Write-Log "Mounting ISO $Source ..."
    $mounted = Mount-DiskImage -ImagePath $Source -PassThru
    Start-Sleep -Seconds 2
    $vol = ($mounted | Get-Volume)
    if (-not $vol.DriveLetter) { 
      # sometimes the association lags; re-query
      Start-Sleep -Seconds 2
      $vol = ($mounted | Get-Volume)
    }
    if (-not $vol.DriveLetter) { Write-Log "Could not get drive letter for mounted ISO." 'ERROR'; exit 2 }
    $drive = $vol.DriveLetter + ":\"
    $setupPath = Join-Path $drive 'setup.exe'
  } else {
    $setupPath = Join-Path (Resolve-Path $Source) 'setup.exe'
  }
} else {
  Write-Log "Source path not found: $Source" 'ERROR'
  exit 2
}

if (-not (Test-Path $setupPath)) {
  Write-Log "setup.exe not found at $setupPath" 'ERROR'
  if ($mounted) { Dismount-DiskImage -ImagePath $Source -ErrorAction SilentlyContinue }
  exit 2
}
Write-Log "Using setup at: $setupPath"

#--------------------------- BitLocker handling ---------------------------
function Suspend-BitLockerIfNeeded {
  try {
    $bl = manage-bde -status C: 2>$null
    if ($bl -match 'Protection Status:\s+Protection On') {
      Write-Log "BitLocker is ON. Suspending protectors for up to 3 reboots ..."
      manage-bde -protectors -disable C: -RebootCount 3 | Out-Null
      return $true
    }
    return $false
  } catch {
    Write-Log "Could not query/suspend BitLocker: $($_.Exception.Message)" 'WARN'
    return $false
  }
}
$bitLockerSuspended = Suspend-BitLockerIfNeeded

#--------------------------- Build setup arguments ---------------------------
$logCopyDir = 'C:\Windows11-SetupLogs'
New-Item -ItemType Directory -Force -Path $logCopyDir | Out-Null

$args = @(
  '/auto', 'upgrade',               # In-place upgrade with default retention (apps/files)
  '/quiet',                         # No UI
  '/eula','accept',
  '/dynamicupdate', 'enable',       # Get latest setup updates/drivers
  '/migratedrivers', 'all',
  '/telemetry', 'disable',
  '/copylogs', $logCopyDir
)

if ($NoReboot) {
  $args += @('/noreboot')
  Write-Log "NoReboot selected: upgrade will complete staging and wait for manual reboot."
} else {
  Write-Log "Automatic reboots will occur during upgrade."
}

# Optional: If you want setup to always suspend BitLocker via setup switch as well:
$args += @('/bitlocker', 'alwayssuspend')

Write-Log ("Setup arguments: " + ($args -join ' '))

#--------------------------- Kick off setup ---------------------------
Write-Log "Launching Windows 11 setup (silent). This can take a while; device may reboot multiple times."
$proc = Start-Process -FilePath $setupPath -ArgumentList $args -PassThru -Wait

$exitCode = $proc.ExitCode
Write-Log "Setup exited with code: $exitCode"

# Common exit codes (best-effort; consult Panther logs for details)
$codeMap = @{
  0            = 'Success (or success pending reboot if /noreboot).'
  0xC1900200   = 'Compatibility issue: system does not meet minimum requirements.'
  0xC1900208   = 'Incompatible app/driver or requirement block.'
  0xC1900107   = 'Cleanup required from previous installation (restart and try again).'
  0xC1900101   = 'Driver error during upgrade (rollback).'
  0x80070020   = 'Sharing violation (file in use).'
  0x80070070   = 'Insufficient disk space.'
}

if ($codeMap.ContainsKey($exitCode)) {
  Write-Log "Result: $($codeMap[$exitCode])"
} else {
  Write-Log "Result: Unknown code. Check setup logs in $logCopyDir and Panther folder."
}

#--------------------------- Post steps ---------------------------
if ($mounted) {
  Write-Log "Dismounting ISO."
  Dismount-DiskImage -ImagePath $Source -ErrorAction SilentlyContinue
}

if (-not $NoReboot -and $exitCode -eq 0) {
  Write-Log "Upgrade staging complete; the system may reboot automatically to continue."
}

if ($NoReboot -and $exitCode -eq 0) {
  Write-Log "Reboot is required to finalize the upgrade. You can reboot now or schedule it."
}

# Return the setup exit code as the script exit code for orchestration tools
exit $exitCode
## test in git hub
## test2 in git hub

