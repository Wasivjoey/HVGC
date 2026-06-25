<#
.SYNOPSIS
    Deletes inactive (stale) local user profiles from one or more domain computers.

.DESCRIPTION
    For each target computer, this script enumerates local user profiles via the
    Win32_UserProfile CIM class and removes any whose last-use time is older than a
    given threshold (default 90 days). It safely skips:
        - Special / system profiles (LocalSystem, NetworkService, defaultuser0, etc.)
        - Currently loaded profiles (a logged-on user)
        - A configurable exclusion list (e.g. service accounts, admins)

    Profiles are removed with the CIM Delete method (NOT a raw folder delete), so the
    registry ProfileList entry and NTUSER.DAT are cleaned up correctly.

    Runs with -WhatIf / -Confirm support. ALWAYS test with -WhatIf first.

.PARAMETER ComputerName
    One or more computers to clean. Defaults to the local machine.

.PARAMETER SearchBase
    Optional AD organizational-unit DN. When supplied, the script pulls enabled
    computer objects from that OU (requires the ActiveDirectory module) instead of
    using -ComputerName.

.PARAMETER InactiveDays
    Age threshold in days. Profiles not used within this many days are candidates
    for deletion. Default = 90.

.PARAMETER ExcludeUser
    SAM account names (or profile folder names) to always keep, in addition to the
    built-in system/special profile protection.

.PARAMETER LogPath
    CSV log file recording every profile evaluated and the action taken.

.PARAMETER Credential
    Credential used for the remote CIM sessions.

.EXAMPLE
    .\Remove-InactiveUserProfiles.ps1 -ComputerName PC01,PC02 -InactiveDays 60 -WhatIf

    Show what WOULD be deleted on PC01 and PC02 for profiles idle > 60 days.

.EXAMPLE
    .\Remove-InactiveUserProfiles.ps1 -SearchBase "OU=Workstations,DC=corp,DC=local" -ExcludeUser svc_backup,helpdesk -Confirm:$false

    Clean every enabled workstation in the OU, keeping two named accounts, no prompts.

.NOTES
    Run as a domain admin (or an account with local admin on the targets).
    Requires PowerShell remoting/WinRM and the WMI service on the targets.
#>

[CmdletBinding(SupportsShouldProcess = $true, ConfirmImpact = 'High')]
param(
    [Parameter(ValueFromPipeline = $true)]
    [string[]] $ComputerName = $env:COMPUTERNAME,

    [string] $SearchBase,

    [ValidateRange(1, 3650)]
    [int] $InactiveDays = 90,

    [string[]] $ExcludeUser = @(),

    [string] $LogPath = "$PSScriptRoot\InactiveProfileCleanup_$(Get-Date -Format 'yyyyMMdd_HHmmss').csv",

    [System.Management.Automation.PSCredential] $Credential
)

# Profiles that must never be touched, regardless of age.
$ProtectedProfiles = @(
    'Administrator', 'Default', 'Default User', 'Public', 'All Users',
    'defaultuser0', 'WDAGUtilityAccount'
) + $ExcludeUser

$cutoff   = (Get-Date).AddDays(-$InactiveDays)
$results  = [System.Collections.Generic.List[object]]::new()

# Resolve targets from AD if an OU was supplied.
if ($SearchBase) {
    Write-Verbose "Querying Active Directory for enabled computers under: $SearchBase"
    try {
        Import-Module ActiveDirectory -ErrorAction Stop
        $ComputerName = Get-ADComputer -SearchBase $SearchBase -Filter 'Enabled -eq $true' |
            Select-Object -ExpandProperty Name
    }
    catch {
        throw "Failed to query AD ($SearchBase): $($_.Exception.Message)"
    }
}

Write-Host "Targets: $($ComputerName -join ', ')"
Write-Host "Removing profiles idle since before: $($cutoff.ToString('yyyy-MM-dd')) ($InactiveDays days)"
Write-Host ("-" * 60)

foreach ($computer in $ComputerName) {

    if (-not (Test-Connection -ComputerName $computer -Count 1 -Quiet)) {
        Write-Warning "[$computer] unreachable - skipping."
        $results.Add([pscustomobject]@{
            Computer = $computer; User = ''; LastUsed = ''; Status = 'Unreachable'
        })
        continue
    }

    # Build a CIM session (DCOM falls back better to older OSes than WSMan).
    $sessionParams = @{ ComputerName = $computer; ErrorAction = 'Stop' }
    if ($Credential) { $sessionParams.Credential = $Credential }

    try {
        $cim = New-CimSession @sessionParams
    }
    catch {
        Write-Warning "[$computer] could not open CIM session: $($_.Exception.Message)"
        $results.Add([pscustomobject]@{
            Computer = $computer; User = ''; LastUsed = ''; Status = "CIM error: $($_.Exception.Message)"
        })
        continue
    }

    try {
        # Special=false drops system/service profiles; Loaded=true means in use right now.
        $profiles = Get-CimInstance -CimSession $cim -ClassName Win32_UserProfile -Filter 'Special = False'

        foreach ($profile in $profiles) {
            $folder   = Split-Path $profile.LocalPath -Leaf
            $lastUsed = $profile.LastUseTime   # already a DateTime via CIM

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
                if ($PSCmdlet.ShouldProcess("$computer\$folder", "Delete profile (idle $idleDays days)")) {
                    try {
                        Remove-CimInstance -InputObject $profile -ErrorAction Stop
                        $action = 'Deleted'
                        $reason = "Idle $idleDays days"
                        Write-Host "[$computer] DELETED $folder (idle $idleDays days)" -ForegroundColor Yellow
                    }
                    catch {
                        $action = 'Error'
                        $reason = $_.Exception.Message
                        Write-Warning "[$computer] failed to delete $folder : $($_.Exception.Message)"
                    }
                }
                else {
                    $action = 'WhatIf'
                    $reason = "Would delete (idle $idleDays days)"
                }
            }

            $results.Add([pscustomobject]@{
                Computer = $computer
                User     = $folder
                LastUsed = if ($lastUsed) { $lastUsed.ToString('yyyy-MM-dd HH:mm') } else { 'Unknown' }
                Status   = $action
                Reason   = $reason
            })
        }
    }
    catch {
        Write-Warning "[$computer] enumeration failed: $($_.Exception.Message)"
    }
    finally {
        Remove-CimSession $cim -ErrorAction SilentlyContinue
    }
}

# Output + log.
$results | Format-Table -AutoSize
try {
    $results | Export-Csv -Path $LogPath -NoTypeInformation -Encoding UTF8
    Write-Host "`nLog written to: $LogPath" -ForegroundColor Cyan
}
catch {
    Write-Warning "Could not write log to $LogPath : $($_.Exception.Message)"
}

$deleted = ($results | Where-Object Status -eq 'Deleted').Count
$wouldDelete = ($results | Where-Object Status -eq 'WhatIf').Count
Write-Host "Done. Deleted: $deleted  |  Would-delete (WhatIf): $wouldDelete  |  Evaluated: $($results.Count)"
