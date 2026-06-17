param(
    [string]$Goals = "goals/GOALS.example.md",
    [switch]$DryRun
)

$argsList = @("-m", "overnight_app_maker", "--goals", $Goals)
if ($DryRun) {
    $argsList += "--dry-run"
}

python @argsList
