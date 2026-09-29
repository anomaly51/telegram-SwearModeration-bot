# Deployments

Code is synchronized from `Gamubells/telegram-SwearModeration-bot`, branch `master`,
into this repository's `main` by **Sync upstream** (every 5 minutes, or Run workflow).
GitHub may delay scheduled runs. The sync creates a normal merge commit and keeps
our `.github/` workflows and this deployment guide. Application-code conflicts fail
for manual resolution; the sync never force-pushes. CI is explicitly dispatched after
the merge because a push made with `GITHUB_TOKEN` does not trigger push workflows.
The developer repository is read-only to our GitHub account, so its webhook cannot
be configured here. Production continues to require **Promote production**.

Push `dev` to build and update `telegram-swearmoderation-bot/values/dev.yaml` in `anomaly51/general-1-argocd`.
Push `main` to build and update `staging.yaml`. Argo CD deploys these environments automatically.
A missing values profile means build/publish only; CI never creates an environment implicitly.
Pull requests build on hosted runners without production credentials and do not deploy.

Production: open GitOps → Actions → Promote production → Run workflow. Select `telegram-swearmoderation-bot` and
the full GitOps commit of your tested, healthy staging release. Start with dry_run=true.
For applications without staging, use source_commit instead (the full main SHA built by CI).
Promotion copies immutable image digests and the pinned chart, retains production settings,
then explicitly synchronizes Argo CD and checks health. It does not rebuild images.

GitHub Actions authenticates to Vault using OIDC. Vault supplies registry credentials and a
GitHub App private key; Actions obtains a temporary write token scoped to the GitOps repository.
Do not add personal tokens or production deployment credentials to this repository.
