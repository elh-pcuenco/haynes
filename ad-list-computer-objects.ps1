# Output file path
$OutputFile = "C:\Temp\ADComputers_LastLogon.csv"

# Get all computers with LastLogonTimestamp
Get-ADComputer -Filter * -Properties LastLogonTimestamp | Select-Object `
    Name,
    OperatingSystem,
    OperatingSystemVersion,
    Enabled,
    @{Name="LastLogonDate";Expression={
        if ($_.LastLogonTimestamp) {
            [DateTime]::FromFileTime($_.LastLogonTimestamp)
        } else {
            $null
        }
    }} | Export-Csv -Path $OutputFile -NoTypeInformation -Encoding UTF8

Write-Host "Export completed. File saved to $OutputFile"
