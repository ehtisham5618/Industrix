# Contributing to industrix

## 🛡️ Mandatory Branching Architecture & Quality Gates

This repository follows a strict 3-tier protected branching architecture:

```
[feature/{task-id}-{slug}] (Intern Working Branch)
             │
             ▼ Push & Open PR
        [staging] (Pre-Production / Default Branch)
             │
             ├── Automated CI (Syntax, Lint, Imports)
             ├── Peer Review by Squad Partner
             └── Amelia / Evelyn AI Quality Gate Approval & Merge
             │
             ▼ Validated
          [main] (Production / Golden Rollback Backup)
```

### 1. Developer Setup
Before your first push, configure the local git hooks:
```bash
git config core.hooksPath .githooks
```

### 2. Workflow Rules
1. Never commit or push directly to `main` or `staging`. Direct pushes will be rejected client-side and blocked by GitHub Actions.
2. Branch off `staging` for all features:
   ```bash
   git checkout staging
   git pull origin staging
   git checkout -b feature/<task-id>-<short-description>
   ```
3. Push to your feature branch and open a Pull Request targeting `staging`.
4. Ensure your PR is linked to its ClickUp Task ID.
5. Daily EOD Git commit & PR proof-of-work deadline is strictly **11:45 PM PKT**.
