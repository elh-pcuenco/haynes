# Requires the Active Directory module to be installed.
# Install-Module -Name ActiveDirectory

# CSV path and domain name
$InputFile = "C:\temp\new-6th-grade.csv"
$emailDomain = "collegebound.elhaynes.org" # This will be used for the EmailAddress attribute
$upnDomain = "elhaynes.org"            # This will be used for the UserPrincipalName (User Logon Name)

if (-Not (Test-Path $InputFile)) {
    Write-Host "Error: File '$InputFile' not found. Exiting script."
    exit
}

# Import the CSV
$students = Import-Csv -Path $InputFile

foreach ($student in $students) {
    $firstName = $student.'First Name'.Trim()
    $lastName = $student.'Last Name'.Trim()
    $ou = $student.'OU'.Trim()

    # Display Name: FirstName LastName (with space)
    $displayName = "$firstName $lastName"

    # Username (SamAccountName): firstname + lastname, lowercase, max 20 characters
    $username = ($firstName + $lastName).ToLower()
    if ($username.Length -gt 20) {
        $username = $username.Substring(0, 20)
    }

    # Email Address
    $email = "$username@$emailDomain"

    # User Principal Name
    $userPrincipalName = "$username@$upnDomain"

    # Password: 5 random digits + first name
    $rand = -join ((0..9) | Get-Random -Count 5)
    $password = "$rand$firstName"
    $securePassword = ConvertTo-SecureString $password -AsPlainText -Force

    Write-Host ("Attempting to process: {0} (Username: {1}, UPN: {2})" -f $displayName, $username, $userPrincipalName) -ForegroundColor Cyan

    # --- Check if account already exists ---
    # We use -ErrorAction SilentlyContinue so Get-ADUser returns $null if not found,
    # rather than throwing an error. The try/catch is primarily for other, unexpected errors.
    try {
        $existingUser = Get-ADUser -Identity $username -ErrorAction SilentlyContinue
        if ($existingUser) {
            Write-Host ("⚠️ Account already exists for {0} (Username: {1}). Skipping creation." -f $displayName, $username) -ForegroundColor Yellow
            continue # Move to the next student in the loop
        }
    }
    catch {
        # If an error occurs during the check (e.g., AD is unreachable), log it but still try to create.
        Write-Host ("❌ Error checking for existing user {0}: {1}" -f $username, $_.Exception.Message) -ForegroundColor Red
    }

    # Create user
    try {
        $createdUser = New-ADUser `
            -Name $displayName `
            -GivenName $firstName `
            -Surname $lastName `
            -DisplayName $displayName `
            -SamAccountName $username `
            -UserPrincipalName $userPrincipalName ` # Changed to use $userPrincipalName
            -Path $ou `
            -AccountPassword $securePassword `
            -Enabled $true `
            -PasswordNeverExpires $true `
            -CannotChangePassword $true `
            -PassThru # Added -PassThru to get the created user object

        # --- Set EmailAddress separately after user creation ---
        if ($createdUser) {
            try {
                Set-ADUser -Identity $createdUser -EmailAddress $email
                Write-Host ("   Email address set for {0}: {1}" -f $displayName, $email) -ForegroundColor DarkGreen
            }
            catch {
                Write-Host ("   ❌ Failed to set email address for {0}: {1}" -f $displayName, $_.Exception.Message) -ForegroundColor Red
            }
        }

        Write-Host ("✅ Created: {0} | Username: {1} | UPN: {2} | Email: {3} | Password: {4} | OU: {5}" -f $displayName, $username, $userPrincipalName, $email, $password, $ou) -ForegroundColor Green
    }
    catch {
        Write-Host ("❌ Failed to create user {0} (Username: {1}): {2}" -f $displayName, $username, $_.Exception.Message) -ForegroundColor Red
    }
}
