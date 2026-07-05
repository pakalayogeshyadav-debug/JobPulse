# Data Validation Architecture

The JobPulse Validation Layer acts as the critical gatekeeper between the Transformation and Loading phases. It adheres to a strict "Fail the row, not the pipeline" philosophy.

## Pipeline Integration
```text
Extract -> Transform -> VALIDATE -> Load
```

## How It Works
1. **Vectorized Rules**: The engine uses pure Pandas vectorization to ensure operations take milliseconds, avoiding `.iterrows()` bottlenecks.
2. **Rule Registry**: Rules are automatically registered. To add a new rule, inherit from `BaseValidationRule` and use the `@RuleRegistry.register` decorator.
3. **Severity Levels**:
   - `CRITICAL`: Crashes the pipeline immediately (e.g., missing critical schema columns).
   - `ERROR`: Flags the row as `is_valid = False`. The row is removed before loading.
   - `WARNING`: Flags the row internally but allows it to proceed into the Data Warehouse.
   
## Implemented Rules
- `RequiredFieldsRule`
- `LocationValidationRule`
- `SalaryValidationRule`
- `ExperienceValidationRule`
- `DateValidationRule`
- `DuplicateDetectionRule` (Uses SHA-256 Content Hashing)
- `SkillValidationRule` (Collects unknown skills)

## Output Artifacts
On every run, the pipeline generates:
- An updated `reports/validation_report.html` 
- Appends KPIs to `data/validation_history.csv`
- Embeds validation metrics directly into the console `ETLReport`.
