
# --- Configuration ---
$InputFile = "C:\temp\new-6th-grade-google.csv" # Path to your CSV file
$googleWorkspaceDomain = "collegebound.elhaynes.org"         # Your primary Google Workspace domain (e.g., example.com)
$gamPath = "C:\GAM7\gam.exe" 

# --- CSV Column Headers (Ensure these match your CSV exactly) ---
# Your CSV should have columns: 'firstname', 'lastname', 'ou', 'password'

# --- Script Start ---

# Import the CSV file
if (-not (Test-Path $InputFile)) {
    Write-Error "CSV file not found at '$InputFile'. Please ensure the path is correct."
    exit
}
$usersToCreate = Import-Csv -Path $InputFile

Write-Host "Starting Google Workspace user creation process..." -ForegroundColor Cyan
Write-Host "Processing $($usersToCreate.Count) users from CSV: '$InputFile'" -ForegroundColor Cyan

foreach ($user in $usersToCreate) {
    # Extract data from CSV, trimming whitespace
    $firstName = $user.firstname.Trim()
    $lastName = $user.lastname.Trim()
    $ou = $user.ou.Trim()
    $password = $user.password.Trim()

    # Construct Google Workspace primary email address 
    $primaryEmail = ($firstName + $lastName).ToLower() + "@" + $googleWorkspaceDomain

    # Construct full name for Google Workspace profile
    $fullName = "$firstName $lastName"

    Write-Host "`n--- Processing User: $fullName ($primaryEmail) ---" -ForegroundColor DarkCyan

    # Validate essential fields
    if ([string]::IsNullOrWhiteSpace($firstName) -or `
        [string]::IsNullOrWhiteSpace($lastName) -or `
        [string]::IsNullOrWhiteSpace($ou) -or `
        [string]::IsNullOrWhiteSpace($password)) {
        Write-Warning "Skipping user '$fullName' due to missing required data in CSV (firstname, lastname, ou, or password)."
        continue # Skip to the next user
    }

    # --- Check if user already exists in Google Workspace ---
    Write-Host "Checking if user '$primaryEmail' already exists..." -ForegroundColor Gray
    try {
        # GAM command to check user existence
        # 'gam info user <email>' will return an error if user doesn't exist,
        # or user info if they do. We capture the output and check for success.
        $gamCheckArgs = "info user $primaryEmail"
        $gamCheckResult = & $gamPath $gamCheckArgs 2>&1 # Capture both stdout and stderr

        if ($gamCheckResult | Select-String "User: $primaryEmail" -Quiet) {
            Write-Warning "User '$primaryEmail' already exists in Google Workspace. Skipping creation."
            continue # Skip to the next user
        }
        # If 'gam info user' fails because the user doesn't exist, it will output an error.
        # We assume if the above Select-String doesn't find the user, they don't exist.
    }
    catch {
        Write-Warning "Error checking user existence for '$primaryEmail': $($_.Exception.Message). Attempting creation anyway."
        # This catch block is more for unexpected GAM errors, not "user not found" which is expected.
    }


    # --- Create the Google Workspace user using GAM ---
    Write-Host "Attempting to create user '$primaryEmail'..." -ForegroundColor Yellow
    try {
        # GAM command to create a user
        # - PasswordNeverExpires is not a direct GAM option for new users, but default is usually not to expire immediately.
        # - force_send_welcome_email false: Prevents sending a welcome email immediately.
        # - changepassword on next login off: User is not forced to change password on first login.
        # - agreed_to_terms true: User has agreed to terms (often required for new users).
        # - suspended false: User is not suspended upon creation.

        $gamCreateArgs = @(
            "create user",
            $primaryEmail,
            "firstname", "`"$firstName`"",
            "lastname", "`"$lastName`"",
            "password", "`"$password`"",
            "ou", "`"$ou`"",
            "fullname", "`"$fullName`"",
            "changepassword", "on", "next", "login", "off", # User WILL NOT be forced to change password
            "agreed_to_terms", "true",
            "suspended", "false",
            "force_send_welcome_email", "false" # Set to 'true' if you want welcome emails sent
        )

        # Execute the GAM command
        $gamResult = & $gamPath $gamCreateArgs 2>&1 # Capture both stdout and stderr

        # Check for success or failure based on GAM's output
        if ($gamResult | Select-String "User: $primaryEmail created" -Quiet) {
            Write-Host "✅ Successfully created user: $primaryEmail" -ForegroundColor Green
        } elseif ($gamResult | Select-String "ERROR" -Quiet) {
            Write-Error "❌ Failed to create user '$primaryEmail'. GAM output: $($gamResult | Out-String)"
        } else {
            Write-Warning "❓ Unexpected GAM output for user '$primaryEmail'. Please review manually. GAM output: $($gamResult | Out-String)"
        }
    }
    catch {
        Write-Error "❌ An error occurred while trying to execute GAM for user '$primaryEmail': $($_.Exception.Message)"
    }
}

Write-Host "`nGoogle Workspace user creation process completed." -ForegroundColor Cyan