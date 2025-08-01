# Input file
$InputFile = "c:\temp\2025alum.csv"
$NewOU = "/2025_Alumni"

# Check if the input file exists
if (-Not (Test-Path $InputFile)) {
    Write-Host "Error: File '$InputFile' not found. Exiting script."
    exit
}

# Read usernames from the CSV file and move to HS Exited OU
Import-Csv -Path $InputFile | ForEach-Object {
    $username = $_.username

    # Check if the username contains the specific domain
    if ($username -like "*@collegebound.elhaynes.org") {
	## if ($username -like "**@elhaynes.org") {
        Write-Host "Moving user: $username"
        & gam update user $username org $NewOU
        
    } else {
        Write-Host "Skipping user: $username (does not match domain)"
    }
}
