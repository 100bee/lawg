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

$comparison = Invoke-RestMethod -Method Post -Uri "http://localhost:8000/api/evaluations/compare"
foreach ($result in $comparison.results) {
    Write-Host "[$($result.retrieval_mode)] Recall@5: $([math]::Round($result.recall_at_k * 100, 1))%, MRR: $([math]::Round($result.mrr, 3)), Refusal: $([math]::Round($result.refusal_accuracy * 100, 1))%, Latency: $([math]::Round($result.average_retrieval_ms, 1))ms"
}
Write-Host "Recommended mode: $($comparison.recommended_mode)"
