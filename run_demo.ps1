 $ErrorActionPreference = "Stop"
 Set-Location $PSScriptRoot
 $env:PYTHONPATH = (Join-Path $PSScriptRoot "src")

 $inputJson  = ".\tests\fixtures\extract_input.json"
 $outDir     = ".\demo_out"
 $imagesJson = Join-Path $outDir "images.json"
 $scoresJson = Join-Path $outDir "scores.json"
 $reportHtml = Join-Path $outDir "report.html"

 New-Item -ItemType Directory -Force -Path $outDir | Out-Null

 function Invoke-Cli {
     param([string[]]$CliArgs)
     try {
         python -m engine.cli @CliArgs
         return $true
     } catch {
         try {
             python .\src\engine\cli.py @CliArgs
             return $true
         } catch {
             return $false
         }
     }
 }

 Write-Host "`n== 1) CLI help ==" -ForegroundColor Cyan
 if (-not (Invoke-Cli @("--help"))) {
     throw "CLI entrypoint not found via 'python -m engine.cli' or 'python .\src\engine\cli.py'"
 }

 Write-Host "`n== 2) Extract ==" -ForegroundColor Cyan
 $out = python -m engine.cli extract $inputJson
 if ($LASTEXITCODE -ne 0) { throw "extract command failed (exit $LASTEXITCODE)" }
 [System.IO.File]::WriteAllText((Resolve-Path $outDir | Join-Path -ChildPath 'images.json'), ($out -join "`n"), [System.Text.UTF8Encoding]::new($false))

 Write-Host "`n== 3) Score ==" -ForegroundColor Cyan
 $out = python -m engine.cli score $imagesJson
 if ($LASTEXITCODE -ne 0) { throw "score command failed (exit $LASTEXITCODE)" }
 [System.IO.File]::WriteAllText((Resolve-Path $outDir | Join-Path -ChildPath 'scores.json'), ($out -join "`n"), [System.Text.UTF8Encoding]::new($false))

 Write-Host "`n== 4) Report ==" -ForegroundColor Cyan
 python -m engine.cli report $scoresJson --output $reportHtml
 if ($LASTEXITCODE -ne 0) { throw "report command failed (exit $LASTEXITCODE)" }

 Write-Host "`n== 5) Results ==" -ForegroundColor Green
 Get-ChildItem $outDir | Select-Object Name, Length, LastWriteTime
 Write-Host "`nHTML report:" (Resolve-Path $reportHtml) -ForegroundColor Yellow

