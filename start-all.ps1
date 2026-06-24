# ============================================================
#  TestForge-AI — Lancement de l'application (3 terminaux)
#  Ouvre : 1) Backend FastAPI  2) Serveur MCP Playwright  3) Frontend Angular
#  Usage : clic droit > "Exécuter avec PowerShell"  OU  ./start-all.ps1
# ============================================================

$ErrorActionPreference = "Stop"
$root     = $PSScriptRoot
$backend  = Join-Path $root "backend"
$frontend = Join-Path $root "frontend"
$venvActivate = Join-Path $backend "venv\Scripts\Activate.ps1"

Write-Host "==> TestForge-AI : demarrage des 3 services..." -ForegroundColor Cyan

# --- Verifications de base ---------------------------------------------------
if (-not (Test-Path $venvActivate)) {
    Write-Host "[ERREUR] venv introuvable : $venvActivate" -ForegroundColor Red
    Write-Host "         Cree-le d'abord :" -ForegroundColor Yellow
    Write-Host "         cd backend; python -m venv venv; .\venv\Scripts\Activate.ps1; pip install -r requirements.txt" -ForegroundColor Yellow
    Read-Host "Appuie sur Entree pour quitter"
    exit 1
}
if (-not (Test-Path (Join-Path $backend ".env"))) {
    Write-Host "[ATTENTION] Aucun fichier backend\.env trouve — les cles API sont indispensables." -ForegroundColor Yellow
}
if (-not (Test-Path (Join-Path $frontend "node_modules"))) {
    Write-Host "[ATTENTION] frontend\node_modules absent — lance 'npm install' dans frontend\ d'abord." -ForegroundColor Yellow
}

# --- 1) Backend FastAPI (port 8000) -----------------------------------------
Start-Process powershell -ArgumentList @(
    "-NoExit", "-Command",
    "Set-Location '$backend'; & '$venvActivate'; " +
    "Write-Host '=== BACKEND FastAPI (http://localhost:8000) ===' -ForegroundColor Green; " +
    "uvicorn app.main:app --reload --port 8000"
)

# --- 2) Serveur MCP Playwright (port 8931) ----------------------------------
Start-Process powershell -ArgumentList @(
    "-NoExit", "-Command",
    "Write-Host '=== MCP PLAYWRIGHT (http://localhost:8931) ===' -ForegroundColor Green; " +
    "npx @playwright/mcp@latest --port 8931"
)

# --- 3) Frontend Angular (port 4200) ----------------------------------------
Start-Process powershell -ArgumentList @(
    "-NoExit", "-Command",
    "Set-Location '$frontend'; " +
    "Write-Host '=== FRONTEND Angular (http://localhost:4200) ===' -ForegroundColor Green; " +
    "npm start"
)

Write-Host ""
Write-Host "==> 3 terminaux ouverts :" -ForegroundColor Cyan
Write-Host "    - Backend  : http://localhost:8000" -ForegroundColor Gray
Write-Host "    - MCP      : http://localhost:8931" -ForegroundColor Gray
Write-Host "    - Frontend : http://localhost:4200" -ForegroundColor Gray
Write-Host ""
Write-Host "Laisse les 3 fenetres OUVERTES pendant l'utilisation de l'app." -ForegroundColor Yellow
Write-Host "Pour tout arreter : ferme les 3 fenetres." -ForegroundColor Yellow
