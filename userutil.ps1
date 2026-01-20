# Ensure the AD Module is loaded
if (!(Get-Module -ListAvailable ActiveDirectory)) {
    Write-Error "Active Directory module not found."
    return
}

# 1. YOUR CUSTOM FIELDS (Synced here)
$ViewFields = "DisplayName", "SamAccountName", "EmailAddress", "Title", "Department", "Enabled", "LastLogonDate", "LockedOut", "MemberOf"

function Show-Menu {
    Clear-Host
    Write-Host "================ AD TECH UTILITY TOOL ================" -ForegroundColor Cyan
    Write-Host "1. Search User (Synced View)"
    Write-Host "2. Unlock a User Account"
    Write-Host "3. Reset User Password"
    Write-Host "Q. Quit"
    Write-Host "======================================================"
}

do {
    Show-Menu
    $Selection = Read-Host "Select an option"

    switch ($Selection) {
        "1" {
            $Name = Read-Host "Enter name to search"
            
            # 2. We pass the variable to -Properties so it fetches EVERYTHING you want
            $Results = Get-ADUser -Filter "Name -like '*$Name*'" -Properties $ViewFields 
            
            if ($Results) {
                $Results | Select-Object @(
                    # We list your fields here
                    "DisplayName", "SamAccountName", "EmailAddress", "Title", "Department", "Enabled", "LastLogonDate", "LockedOut",
                    # This special block cleans up the "MemberOf" list so it's readable
                    @{Name="Groups"; Expression={$_.MemberOf -replace '^CN=([^,]+).+$','$1' -join '; '}}
                ) | Out-GridView -Title "Search Results for $Name" 
            } else {
                Write-Host "No users found." -ForegroundColor Red
                Start-Sleep -Seconds 2
            }
        }
        
        "2" {
            $Name = Read-Host "Enter name to unlock"
            # Reusing your $ViewFields here ensures the Tech sees the same columns when picking a user
            $User = Get-ADUser -Filter "Name -like '*$Name*'" -Properties $ViewFields | 
                    Select-Object $ViewFields | 
                    Out-GridView -Title "Select user to UNLOCK" -OutputMode Single
            
            if ($User) {
                Unlock-ADAccount -Identity $User.SamAccountName
                Write-Host "Successfully processed unlock for $($User.DisplayName)" -ForegroundColor Green
                Start-Sleep -Seconds 2
            }
        }

        "3" {
            $Name = Read-Host "Enter name for Password Reset"
            $User = Get-ADUser -Filter "Name -like '*$Name*'" -Properties $ViewFields | 
                    Select-Object $ViewFields | 
                    Out-GridView -Title "Select user for PASSWORD RESET" -OutputMode Single
            
            if ($User) {
                $NewPass = Read-Host "Enter new password" -AsSecureString
                Set-ADAccountPassword -Identity $User.SamAccountName -NewPassword $NewPass -Reset
                Set-ADUser -Identity $User.SamAccountName -ChangePasswordAtLogon $true
                Write-Host "Password reset for $($User.DisplayName)." -ForegroundColor Green
                Start-Sleep -Seconds 2
            }
        }
    }
} while ($Selection -ne "Q")