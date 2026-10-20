# SPDX-License-Identifier: GPL-3.0-only
# PYTHON is an executable path, never shell code.
$ErrorActionPreference = 'Stop'
$projectDirectory = $PSScriptRoot
$pythonArguments = @()
$interpreter = $null
try {
    if ($env:PYTHON) {
        $interpreter = (Get-Command -Name $env:PYTHON -CommandType Application -ErrorAction Stop).Source
    } elseif (Test-Path -LiteralPath (Join-Path $projectDirectory '.venv\Scripts\python.exe') -PathType Leaf) {
        $interpreter = Join-Path $projectDirectory '.venv\Scripts\python.exe'
    } else {
        $launcher = Get-Command -Name 'py.exe' -CommandType Application -ErrorAction SilentlyContinue
        if ($launcher) {
            # A launcher may be installed without any registered interpreter.
            $launcherAvailable = $false
            try {
                & $launcher.Source -3 -c 'import sys; sys.exit(sys.version_info < (3, 10))' 2>$null
                $launcherAvailable = $LASTEXITCODE -eq 0
            } catch { }
            if ($launcherAvailable) {
                $interpreter = $launcher.Source
                $pythonArguments = @('-3')
            }
        }
        if (-not $interpreter) {
            $interpreter = (Get-Command -Name 'python.exe' -CommandType Application -ErrorAction Stop).Source
        }
    }
    & $interpreter @pythonArguments -c 'import sys; sys.exit(sys.version_info < (3, 10))'
    if ($LASTEXITCODE -ne 0) {
        [Console]::Error.WriteLine('Python 3.10+ is required. Set PYTHON to a supported python.exe, or recreate .venv with that Python.')
        exit 1
    }
    & $interpreter @pythonArguments (Join-Path $projectDirectory 'app.py') @args
    exit $LASTEXITCODE
} catch {
    [Console]::Error.WriteLine('Unable to start Python 3.10+. Install Python, create .venv, or set PYTHON to its executable path.')
    [Console]::Error.WriteLine($_.Exception.Message)
    exit 1
}
