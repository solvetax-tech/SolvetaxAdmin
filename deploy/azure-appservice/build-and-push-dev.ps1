# Build monorepo image with VITE_PUBLIC_API_KEY baked in, push to GHCR :dev
# Usage (from repo root):
#   .\deploy\azure-appservice\build-and-push-dev.ps1
# Prerequisite: docker login ghcr.io -u YOUR_GITHUB_USER

$ErrorActionPreference = "Stop"
$Root = Resolve-Path (Join-Path $PSScriptRoot "..\..")
$EnvFile = Join-Path $Root ".env"

if (-not (Test-Path $EnvFile)) {
    Write-Error "Missing .env at $EnvFile"
}

$publicKey = $null
Get-Content $EnvFile | ForEach-Object {
    if ($_ -match '^\s*PUBLIC_API_KEY=(.+)$') {
        $publicKey = $matches[1].Trim().Trim('"').Trim("'")
    }
}

if ([string]::IsNullOrWhiteSpace($publicKey)) {
    Write-Error "PUBLIC_API_KEY not set in .env"
}

$image = "ghcr.io/solvetax-tech/solvetaxadmin"
$tag = "dev"
$stamp = Get-Date -Format "yyyyMMdd-HHmm"

Write-Host "Building ${image}:${tag} (also tagging ${tag}-${stamp})..."
Set-Location $Root

docker build `
    --build-arg "VITE_API_URL=" `
    --build-arg "VITE_PUBLIC_API_KEY=$publicKey" `
    -t "${image}:${tag}" `
    -t "${image}:${tag}-${stamp}" `
    -f Dockerfile .

Write-Host "Pushing ${image}:${tag} and ${image}:${tag}-${stamp}..."
docker push "${image}:${tag}"
docker push "${image}:${tag}-${stamp}"

Write-Host ""
Write-Host "Done. In Azure Deployment Center set image tag to: dev"
Write-Host "Or pin rollback tag: dev-${stamp}"
