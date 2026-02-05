# 1. Define the list of printers to be installed
$PrinterList = @(
    @{
        Name     = "GA [PS] 5th Floor Copier"
        IP       = "192.168.200.70"
        Driver   = "Kyocera CS 8003i KX"
        InfPath  = "C:\Drivers\Kyocera\K8003i.inf" # Path to the driver file
    },
    @{
        Name     = "GA [PS] 3rd Floor"
        IP       = "192.168.200.68"
        Driver   = "Kyocera CS 8003i KX"
        InfPath  = "C:\Drivers\Kyocera\K8003i.inf"
    },
     @{
        Name     = "GA [PS] 4th Floor"
        IP       = "192.168.200.69"
        Driver   = "Kyocera CS 8003i KX"
        InfPath  = "C:\Drivers\Kyocera\K8003i.inf"
    }
    # Add more blocks here as needed
)

foreach ($Printer in $PrinterList) {
    Write-Host "--- Processing: $($Printer.Name) ---" -ForegroundColor Blue

    # 2. Add Driver to the Store (if not already present)
    if (!(Get-PrinterDriver -Name $Printer.Driver -ErrorAction SilentlyContinue)) {
        Write-Host "Adding Driver: $($Printer.Driver)..." -ForegroundColor Cyan
        # This installs the driver into the Windows Driver Store using the .inf file
        pnputil.exe /add-driver $Printer.InfPath /install
        Add-PrinterDriver -Name $Printer.Driver
    }

    # 3. Create Port
    $PortName = "IP_" + $Printer.IP
    if (!(Get-PrinterPort -Name $PortName -ErrorAction SilentlyContinue)) {
        Write-Host "Creating Port: $PortName..." -ForegroundColor Cyan
        Add-PrinterPort -Name $PortName -PrinterHostAddress $Printer.IP
    }

    # 4. Install Printer
    if (!(Get-Printer -Name $Printer.Name -ErrorAction SilentlyContinue)) {
        Write-Host "Installing Printer: $($Printer.Name)..." -ForegroundColor Cyan
        Add-Printer -Name $Printer.Name -DriverName $Printer.Driver -PortName $PortName
        Write-Host "Successfully installed $($Printer.Name)!" -ForegroundColor Green
    } else {
        Write-Host "$($Printer.Name) is already installed." -ForegroundColor Yellow
    }
    Write-Host ""
}