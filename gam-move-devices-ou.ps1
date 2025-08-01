# Define the path to your CSV file and the new OU
$InputFile = "C:\Path\To\Your\chromebooks.csv"
$newOU = "/Archived/Chromebooks"  

# Check if the file exists
if (-Not (Test-Path $InputFile)) {
    Write-Host "CSV file not found at: $InputFile"
    exit
}

# Import the serial numbers
$serials = Import-Csv -Path $InputFile

# Loop through each serial and run the GAM command
foreach ($device in $serials) {
    $serial = $device.serial.Trim()

    if ($serial -ne "") {
        Write-Host "Moving device with serial: $serial"
        & gam update cros id:$serial org "$newOU"
    } else {
        Write-Host "Skipping empty serial entry"
    }
}
