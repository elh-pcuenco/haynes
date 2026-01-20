# 1. Prompt the user for input using a popup box
$SearchName = Read-Host -Prompt "Enter the name to search for (e.g., Alexia Ramos)"

# 2. Build the filter string with wildcards
$FilterString = "Name -like '*$SearchName*'"

try {
    # 3. Get the user(s) with all properties (*) 
    # and pipe them to a GridView window for easy viewing
    Get-ADUser -Filter $FilterString -Properties * | 
    Select-Object * | 
    Out-GridView -Title "Search Results for: $SearchName"
}
catch {
    Write-Error "An error occurred while searching Active Directory. Ensure you have the RSAT module installed and a connection to the domain."
}