# Kidlock Windows Installer
# Run as Administrator: powershell -ExecutionPolicy Bypass -File install-windows.ps1

$ErrorActionPreference = "Stop"
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$TaskName = "Kidlock"
$VenvDir = "$ScriptDir\.venv"

Write-Host "=== Kidlock Windows Installer ===" -ForegroundColor Cyan

# Check for Python
$python = Get-Command python -ErrorAction SilentlyContinue
if (-not $python) {
    Write-Host "Error: Python not found. Please install Python 3.x" -ForegroundColor Red
    exit 1
}

# Create virtual environment
Write-Host "Creating virtual environment..."
& python -m venv $VenvDir

# Install dependencies in venv
Write-Host "Installing Python dependencies..."
& "$VenvDir\Scripts\pip.exe" install -r "$ScriptDir\requirements.txt"

# Create config directory
$ConfigDir = "$env:LOCALAPPDATA\kidlock"
if (-not (Test-Path $ConfigDir)) {
    New-Item -ItemType Directory -Path $ConfigDir -Force | Out-Null
}

# Copy example config if needed
$ConfigFile = "$ConfigDir\config.yaml"
if (-not (Test-Path $ConfigFile)) {
    Write-Host "Creating config from example..."
    Copy-Item "$ScriptDir\config.example.yaml" $ConfigFile
    Write-Host "Please edit $ConfigFile with your MQTT settings" -ForegroundColor Yellow
}

# Get venv Python path
$VenvPython = "$VenvDir\Scripts\python.exe"

# Create scheduled task (runs at user logon with highest privileges)
Write-Host "Creating scheduled task..."

# Remove existing task if present
$existingTask = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
if ($existingTask) {
    Write-Host "Removing existing task..."
    Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
}

# Create the action
$action = New-ScheduledTaskAction `
    -Execute $VenvPython `
    -Argument "-m agent.main --config `"$ConfigFile`"" `
    -WorkingDirectory $ScriptDir

# Create the trigger (at logon)
$trigger = New-ScheduledTaskTrigger -AtLogOn

# Create settings
$settings = New-ScheduledTaskSettingsSet `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -StartWhenAvailable `
    -RestartCount 3 `
    -RestartInterval (New-TimeSpan -Minutes 1)

# Create principal (run with highest privileges for screen lock)
$principal = New-ScheduledTaskPrincipal `
    -UserId $env:USERNAME `
    -LogonType Interactive `
    -RunLevel Highest

# Register the task
Register-ScheduledTask `
    -TaskName $TaskName `
    -Action $action `
    -Trigger $trigger `
    -Settings $settings `
    -Principal $principal `
    -Description "Kidlock Parental Control Agent"

Write-Host ""
Write-Host "=== Installation Complete ===" -ForegroundColor Green
Write-Host ""
Write-Host "Next steps:" -ForegroundColor Cyan
Write-Host "1. Edit config: notepad $ConfigFile"
Write-Host "2. Test manually: $VenvPython -m agent.main -c `"$ConfigFile`" -v"
Write-Host "3. Start task: Start-ScheduledTask -TaskName $TaskName"
Write-Host "4. Check task: Get-ScheduledTask -TaskName $TaskName"
Write-Host ""
Write-Host "The task will automatically start at next logon."
