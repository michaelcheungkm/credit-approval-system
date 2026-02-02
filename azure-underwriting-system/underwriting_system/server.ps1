param(
  [string]$Policies = "..\\..\\underwriting_policies.pdf",
  [string]$HostAddr = "127.0.0.1",
  [int]$Port = 8010
)

Set-Location $PSScriptRoot

if (!(Test-Path ".\\.venv")) {
  python -m venv ".venv"
}

.\\.venv\\Scripts\\python.exe -m pip install -r "..\\requirements.txt"
.\\.venv\\Scripts\\python.exe -m underwriting_system.server --policies $Policies --host $HostAddr --port $Port

