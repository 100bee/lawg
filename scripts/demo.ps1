$ErrorActionPreference = "Stop"

$health = $null
for ($attempt = 0; $attempt -lt 20; $attempt++) {
    try {
        $health = Invoke-RestMethod -Uri "http://localhost:8000/api/health"
        break
    }
    catch {
        Start-Sleep -Seconds 1
    }
}

if ($null -eq $health) {
    throw "Backend did not become ready within 20 seconds."
}

Write-Host "API status: $($health.status) / provider: $($health.provider)"

$seed = Invoke-RestMethod -Method Post -Uri "http://localhost:8000/api/documents/seed"
Write-Host "Documents: $($seed.documents.Count), indexed: $($seed.indexed), skipped: $($seed.skipped)"

$evaluation = Invoke-RestMethod -Method Post -Uri "http://localhost:8000/api/evaluations/run"
Write-Host "Recall@5: $([math]::Round($evaluation.recall_at_k * 100, 1))%"
Write-Host "MRR: $([math]::Round($evaluation.mrr, 3))"
Write-Host "Refusal accuracy: $([math]::Round($evaluation.refusal_accuracy * 100, 1))%"
