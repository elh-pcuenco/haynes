# Define the CSV file path
$csvPath = "C:\Path\To\new_users.csv"

# Import the CSV
$users = Import-Csv -Path $csvPath

foreach ($user in $users) {
    $firstName = $user.'First Name'
    $lastName = $user.'Last Name'
    $displayName = $user.'Display Name'
    $office = $user.'Office'
    $email = $user.'Email'
    $jobTitle = $user.'Job Title'
    $department = $user.'Department'
    $company = $user.'Company'
    $managerName = $user.'Manager Name'

    # Generate username (e.g., jdoe)
    $samAccountName = ($firstName.Substring(0,1) + $lastName).ToLower()

    # Generate initial password (e.g., jd2025@Haynes)
    $password = ($firstName.Substring(0,1) + $lastName.Substring(0,1) + "2025@Haynes")

    # Secure the password
    $securePassword = ConvertTo-SecureString $password -AsPlainText -Force

    # Try to get the manager's DN
    $manager = Get-ADUser -Filter "Name -eq '$managerName'" -Properties DistinguishedName -ErrorAction SilentlyContinue
    $managerDN = $manager.DistinguishedName

    # Define the OU for new users (customize this)
    $ou = "OU=Staff,DC=yourdomain,DC=com"

    # Create the user
    New-ADUser `
        -Name $displayName `
        -GivenName $firstName `
        -Surname $lastName `
        -DisplayName $displayName `
        -SamAccountName $samAccountName `
        -UserPrincipalName "$samAccountName@yourdomain.com" `
        -EmailAddress $email `
        -Office $office `
        -Title $jobTitle `
        -Department $department `
        -Company $company `
        -Manager $managerDN `
        -Path $ou `
        -Enabled $true `
        -AccountPassword $securePassword `
        -ChangePasswordAtLogon $true

    Write-Host "Created user: $displayName ($samAccountName) with password: $password"
}

