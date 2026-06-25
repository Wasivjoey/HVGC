<#
.SYNOPSIS
    Deletes inactive (stale) local user profiles ON THE COMPUTER WHERE IT RUNS.

.DESCRIPTION
    Designed to be deployed to each machine and run locally - e.g. as a GPO
    startup/scheduled-task script, an SCCM/Intune package, or a logon script.
    It does NOT connect to other computers.

    It enumerates local user profiles via Win32_UserProfile and removes any whose
    last-use time is older than a threshold (default 90 days). It uses the CIM
    Delete method (not a raw folder delete) so the registry ProfileList entry and
    NTUSER.DAT are cleaned up correctly.

    Safely skips:
        - Special / system profiles (LocalSystem, defaultuser0, etc.)
        - Currently loaded profiles (a logged-on user)
        - A protected/exclusion list (admins, service accounts, etc.)

    Supports -WhatIf / -Confirm. ALWAYS test with -WhatIf first.

.PARAMETER InactiveDays
    Age threshold in days. Profiles not used within this many days are deleted.
    Default = 90.

.PARAMETER ExcludeUser
    Profile folder names (usually the SAM account) to always keep, on top of the
    built-in system/special protection.

.PARAMETER LogPath
    CSV log of every profile evaluated and the action taken.
    Default goes to C:\ProgramData so it survives under SYSTEM/GPO context.

.EXAMPLE
    .\Remove-InactiveUserProfiles-Local.ps1 -WhatIf
    Show what would be deleted on THIS machine.

.EXAMPLE
    .\Remove-InactiveUserProfiles-Local.ps1 -InactiveDays 60 -ExcludeUser svc_backup -Confirm:$false
    Delete profiles idle > 60 days, keep svc_backup, no prompts (for unattended/GPO use).

.NOTES
    Must run elevated (Administrator / SYSTEM). For GPO/scheduled-task use, run with
    -Confirm:$false so it does not block on a prompt.
#>

[CmdletBinding(SupportsShouldProcess = $true, ConfirmImpact = 'High')]
param(
    [ValidateRange(1, 3650)]
    [int] $InactiveDays = 90,

    [string[]] $ExcludeUser = @(),

    [string] $LogPath = "$env:ProgramData\InactiveProfileCleanup\Cleanup_$(Get-Date -Format 'yyyyMMdd_HHmmss').csv"
)

# --- Must be elevated to delete profiles ---
$identity  = [Security.Principal.WindowsIdentity]::GetCurrent()
$principal = New-Object Security.Principal.WindowsPrincipal($identity)
if (-not $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
    throw "This script must be run elevated (as Administrator or SYSTEM)."
}

# Profiles that must never be touched, regardless of age.
$ProtectedProfiles = @(
    'Administrator', 'Default', 'Default User', 'Public', 'All Users',
    'defaultuser0', 'WDAGUtilityAccount'
) + $ExcludeUser

$cutoff  = (Get-Date).AddDays(-$InactiveDays)
$results = [System.Collections.Generic.List[object]]::new()

Write-Host "Computer : $env:COMPUTERNAME"
Write-Host "Removing profiles idle since before: $($cutoff.ToString('yyyy-MM-dd')) ($InactiveDays days)"
Write-Host ("-" * 60)

# Special = False drops system/service profiles; Loaded = True means in use right now.
$profiles = Get-CimInstance -ClassName Win32_UserProfile -Filter 'Special = False'

foreach ($profile in $profiles) {
    $folder   = Split-Path $profile.LocalPath -Leaf
    $lastUsed = $profile.LastUseTime   # DateTime via CIM

    $action = 'Kept'
    $reason = ''

    if ($profile.Loaded) {
        $reason = 'Currently logged on'
    }
    elseif ($ProtectedProfiles -contains $folder) {
        $reason = 'Protected/excluded'
    }
    elseif (-not $lastUsed) {
        $reason = 'No LastUseTime - skipped for safety'
    }
    elseif ($lastUsed -ge $cutoff) {
        $reason = "Active ($([int]((Get-Date) - $lastUsed).TotalDays)d)"
    }
    else {
        # Candidate for deletion.
        $idleDays = [int]((Get-Date) - $lastUsed).TotalDays
        if ($PSCmdlet.ShouldProcess("$env:COMPUTERNAME\$folder", "Delete profile (idle $idleDays days)")) {
            try {
                Remove-CimInstance -InputObject $profile -ErrorAction Stop
                $action = 'Deleted'
                $reason = "Idle $idleDays days"
                Write-Host "DELETED $folder (idle $idleDays days)" -ForegroundColor Yellow
            }
            catch {
                $action = 'Error'
                $reason = $_.Exception.Message
                Write-Warning "Failed to delete $folder : $($_.Exception.Message)"
            }
        }
        else {
            $action = 'WhatIf'
            $reason = "Would delete (idle $idleDays days)"
        }
    }

    $results.Add([pscustomobject]@{
        Computer = $env:COMPUTERNAME
        User     = $folder
        LastUsed = if ($lastUsed) { $lastUsed.ToString('yyyy-MM-dd HH:mm') } else { 'Unknown' }
        Status   = $action
        Reason   = $reason
    })
}

# Output + log.
$results | Format-Table -AutoSize
try {
    $logDir = Split-Path $LogPath -Parent
    if (-not (Test-Path $logDir)) { New-Item -Path $logDir -ItemType Directory -Force | Out-Null }
    $results | Export-Csv -Path $LogPath -NoTypeInformation -Encoding UTF8
    Write-Host "`nLog written to: $LogPath" -ForegroundColor Cyan
}
catch {
    Write-Warning "Could not write log to $LogPath : $($_.Exception.Message)"
}

$deleted     = ($results | Where-Object Status -eq 'Deleted').Count
$wouldDelete = ($results | Where-Object Status -eq 'WhatIf').Count
Write-Host "Done. Deleted: $deleted  |  Would-delete (WhatIf): $wouldDelete  |  Evaluated: $($results.Count)"
