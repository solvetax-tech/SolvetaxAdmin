# Apply .env values to Azure App Service (dev)
# Prerequisites: az login, Azure CLI installed
#
#   az login
#   .\deploy\azure-appservice\apply-app-settings.ps1

$ErrorActionPreference = "Stop"

$AppName = "solvetaxadmindevweb"
$ResourceGroup = "solvetaxadmin-dev-web-rg"
$SettingsFile = Join-Path $PSScriptRoot "app-settings.dev.env"

if (-not (Test-Path $SettingsFile)) {
    Write-Error "Missing $SettingsFile"
}

$pairs = @{}
Get-Content $SettingsFile | ForEach-Object {
    $line = $_.Trim()
    if ($line -eq "" -or $line.StartsWith("#")) { return }
    $idx = $line.IndexOf("=")
    if ($idx -lt 1) { return }
    $key = $line.Substring(0, $idx).Trim()
    $val = $line.Substring($idx + 1).Trim()
    $pairs[$key] = $val
}

if ($pairs.Count -eq 0) {
    Write-Error "No settings found in $SettingsFile"
}

Write-Host "Applying $($pairs.Count) settings to $AppName ..."

$settingsArgs = @()
foreach ($kv in $pairs.GetEnumerator()) {
    $settingsArgs += "$($kv.Key)=$($kv.Value)"
}

az webapp config appsettings set `
    --name $AppName `
    --resource-group $ResourceGroup `
    --settings $settingsArgs `
    | Out-Null

Write-Host "Done. Restarting app..."
az webapp restart --name $AppName --resource-group $ResourceGroup | Out-Null
Write-Host "Open: https://${AppName}.azurewebsites.net/health"
