# Input file
$InputFile = "c:\temp\HS-to-delete-07-21-2025.csv"
$targetOU = "OU=Students,OU=Disabled Users,DC=elhaynes,DC=org"

# Import Active Directory module
Import-Module ActiveDirectory

# Check if the input file exists
if (-Not (Test-Path $InputFile)) {
    Write-Host "Error: File '$InputFile' not found. Exiting script."
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
