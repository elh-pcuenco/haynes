# Input and output file names
$InputFile = "users0219.csv"
$OutputFile = "output0219.csv"

# Input and output file names
#$InputFile = "users.csv"
#$OutputFile = "output.csv"

# Write header to output file
"username,suspended,creationTime" | Set-Content -Path $OutputFile

# Read usernames from input file (skip the header)
Import-Csv -Path $InputFile | ForEach-Object {
    $username = $_.username

    # Fetch user details using GAM
    $userInfo = gam info user $username | Out-String | ForEach-Object { $_.Trim() }

    # Parse the suspended and creationTime values
    $suspended = if ($userInfo -match "Suspended:\s+(True|False)") { $Matches[1] } else { "N/A" }
    $creationTime = if ($userInfo -match "Creation Time:\s+(.*)") { $Matches[1].Trim() } else { "N/A" }

    # Format the row
    $row = "$username,$suspended,$creationTime"

    # Append the row to the output file
    $row | Add-Content -Path $OutputFile
}
