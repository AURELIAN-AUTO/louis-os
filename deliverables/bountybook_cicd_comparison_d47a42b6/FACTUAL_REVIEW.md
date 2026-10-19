# CI/CD comparison — factual review

Reviewed on 2026-10-19. This is a revision of the existing deliverable, not a new
mission, external submission, acceptance or payment. The JSON generation date is
the real revision date; the requested information period is separately 2024-2025.
The former `generated_at=2025-12-31` was not evidence of generation in 2025.

## Evidence and boundaries

| Claim | Official evidence read | Review result |
|---|---|---|
| GitHub Free, 2,000 private-repository minutes; public standard runners free | https://docs.github.com/en/billing/concepts/product-billing/github-actions | Current documentation supports the distinction; exact historical prices are not fully archived in this dossier. |
| GitLab Free, 400 compute minutes; CE open source | https://docs.gitlab.com/ci/pipelines/compute_minutes/ and https://docs.gitlab.com/development/licensing/ | Distinguish the MIT-licensed Community Edition from enterprise features and the hosted service. Historical tariff precision remains limited. |
| CircleCI, up to 6,000 free monthly minutes | https://circleci.com/blog/deploy-spring-boot-aws-elastic-beanstalk/ (updated May 8, 2025) and https://circleci.com/pricing/ | A dated official 2025 article supports the advertised maximum. Minutes depend on resource/credit rates; do not call it a universal executor quota. |
| Jenkins parallel/matrix jobs, Docker and stored credentials | https://www.jenkins.io/doc/book/pipeline/syntax/ ; https://www.jenkins.io/doc/book/pipeline/docker/ ; https://www.jenkins.io/doc/book/using/using-credentials/ | Self-hosted software, with no vendor minute quota. Infrastructure is not free. Docker and credential functionality depend on relevant plugins. |
| Drone matrix-like configurations | https://docs.drone.io/starlark/overview/ ; https://docs.drone.io/config/pipeline/multi-platform/ ; https://0-8-0.docs.drone.io/matrix-builds/ | Modern configurations can generate multiple pipelines with Starlark/Jsonnet. The legacy 0.8 native matrix syntax must not be conflated with modern YAML; server support is required. |

The listing explicitly permits **check official pricing** where uncertain.
That wording is now present for retrospective GitHub/GitLab/CircleCI pricing.
This review does not claim a complete point-in-time archival audit. Booleans for
open source refer to the documented community editions, not all commercial
features. `matrix_builds=true` for Drone includes generated configurations,
and that interpretation is explicitly disclosed in its notes.

## Submission boundary

- The listing and its 7 USDC reward are not newly revalidated by this document.
- Authorization for HTTP-server job `19a16071` does not authorize this CI/CD job.
- Revalidate openness, exact files and scope, effective platform access and
  existing job-specific authority before any claim/submission.
- No new wallet connection, signing, funding, asset transfer or KYC is permitted.
- Validation proves schema, traceability and hash integrity only. A platform
  receipt, acceptance and payment each require separate evidence.
