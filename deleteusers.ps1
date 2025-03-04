# Input file
$InputFile = "output0219.csv"

# Check if the input file exists
if (-Not (Test-Path $InputFile)) {
    Write-Host "Error: File '$InputFile' not found. Exiting script."
    exit
}

# Read usernames from the CSV file and delete accounts with the specified domain
Import-Csv -Path $InputFile | ForEach-Object {
    $username = $_.username

    # Check if the username contains the specific domain
    if ($username -like "*@collegebound.elhaynes.org") {
        Write-Host "Deleting user: $username"
        gam delete user $username
        
    } else {
        Write-Host "Skipping user: $username (does not match domain)"
    }
}
