# Calculate cutoff date (5 years ago)
$cutoff = (Get-Date).AddYears(-5)

# Get stale computer objects
$staleComputers = Get-ADComputer -Filter * -Properties LastLogonTimestamp | Where-Object {
    $_.LastLogonTimestamp -and ([DateTime]::FromFileTime($_.LastLogonTimestamp) -lt $cutoff)
}

# Export for review
$staleComputers | Select-Object Name, @{Name="LastLogonDate";Expression={[DateTime]::FromFileTime($_.LastLogonTimestamp)}} |
    Export-Csv "C:\Temp\StaleComputers_Over5Years.csv" -NoTypeInformation

Write-Host "$($staleComputers.Count) computers found with LastLogon over 5 years ago. Exported for review."

