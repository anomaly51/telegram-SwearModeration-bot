# Deployments

The canonical source is `anomaly51/telegram-SwearModeration-bot`. Push or merge changes into `main`.
CI tests/builds the bot, publishes its immutable image digest, and commits
`apps/telegram-swearmoderation-bot/values/prod.yaml` in `anomaly51/general-1-argocd`.
Argo CD deploys production automatically and CI verifies the exact rollout.

This bot has only production: no dev/staging profiles, GitHub Environments or
deployments. A dev push cannot deploy. Pull requests targeting main run checks
and builds without deployment credentials. **Promote production is not used.**
There is no scheduled synchronization from developer repositories.

GitHub OIDC obtains scoped credentials from Vault. CI uses a short-lived GitHub
App token to commit GitOps and a read-only Argo token to verify deployment.
Production tokens, database settings and the chart pin are retained.
