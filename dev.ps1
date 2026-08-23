# Starts backend and frontend in separate windows.
$root = $PSScriptRoot
Start-Process powershell -ArgumentList @(
  '-NoExit','-Command',"Set-Location '$root\backend'; uv run uvicorn app.main:app --reload"
)
Start-Process powershell -ArgumentList @(
  '-NoExit','-Command',"Set-Location '$root\frontend'; npm run dev"
)
Write-Host 'backend  http://127.0.0.1:8000/api/health'
Write-Host 'frontend http://localhost:5173'
