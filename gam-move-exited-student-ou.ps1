# Input file
$InputFile = "c:\temp\HS-to-delete-07-21-2025.csv"
$NewOU = "/Student Disabled"
$License = "1010310008"

# Check if the input file exists
if (-Not (Test-Path $InputFile)) {
    Write-Host "Error: File '$InputFile' not found. Exiting script."
    exit
}

# Read usernames from the CSV file and move to Student Exited OU
Import-Csv -Path $InputFile | ForEach-Object {
    $username = $_.username

    # Check if the username contains the specific domain
    if ($username -like "*@collegebound.elhaynes.org") {
	## if ($username -like "**@elhaynes.org") {
        Write-Host "Moving user: $username"
        & gam update user $username org $NewOU
		Write-Host "Suspending account: $username"
		& gam update user $username suspended on
		Write-Host "Deleting License: $username"
        & gam user $username delete license $License
        
    } else {
        Write-Host "Skipping user: $username (does not match domain)"
    }
}
