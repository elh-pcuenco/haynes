# Input and output file names
$InputFile = "ms.csv"
$OutputFile = "output.ms.csv"

# Write header to output file
"username,suspended,creationTime,lastloginTime" | Set-Content -Path $OutputFile

# Read usernames from input file (skip the header)
Import-Csv -Path $InputFile | ForEach-Object {
    $username = $_.username

    # Fetch user details using GAM
    $userInfo = gam info user $username | Out-String | ForEach-Object { $_.Trim() }

    # Parse the suspended and creationTime values
    $suspended = if ($userInfo -match "Suspended:\s+(True|False)") { $Matches[1] } else { "N/A" }
    $creationTime = if ($userInfo -match "Creation Time:\s+(.*)") { $Matches[1].Trim() } else { "N/A" }
	$lastloginTime = if ($userInfo -match "Last login time:\s+(.*)") { $Matches[1].Trim() } else { "N/A" }

    # Format the row
    $row = "$username,$suspended,$creationTime,$lastloginTime"

    # Append the row to the output file
    $row | Add-Content -Path $OutputFile
}
