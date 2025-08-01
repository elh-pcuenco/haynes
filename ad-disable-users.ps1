# Load AD module (requires RSAT installed)
Import-Module ActiveDirectory

# Input CSV path and destination OU DN
$InputFile = "C:\temp\exited-staff-7-23.csv"
$targetOU = "OU=Staff,OU=Disabled Users,DC=elhaynes,DC=org"

# Check if file exists
if (-Not (Test-Path $InputFile)) {
    Write-Error "File not found: $InputFile"
    exit
}

# Read CSV and process each user
Import-Csv -Path $InputFile | ForEach-Object {
    $email = $_.username
    $samAccountName = $email.Split("@")[0]

    try {
        $user = Get-ADUser -Filter { SamAccountName -eq $samAccountName } -ErrorAction Stop

        # Disable the account
        Disable-ADAccount -Identity $user.DistinguishedName

        # Move to the target OU
        Move-ADObject -Identity $user.DistinguishedName -TargetPath $targetOU

        Write-Host "Disabled and moved user: $($user.SamAccountName)"
    }
    catch {
        Write-Warning "User not found or error processing '$email'"
    }
}



