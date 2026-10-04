# Limitations and Roadmap

The known limitations of the AION MVP and the planned order of post-MVP work.

## Current limitations (MVP)

| Area | Limitation | Impact | Planned fix |
|---|---|---|---|
| Security | Local accounts only (no SSO/MFA); in-memory login lockout | weaker than an identity provider | OIDC login with MFA |
| Security | Docker sandbox is opt-in (`AION_SANDBOX=docker`); containers share the host kernel | default `local` mode runs patches on the host | make Docker the default; gVisor/Firecracker |
| Security | Redaction is pattern-based | names/addresses not detected | ML-based PII detection |
| Languages | Only Python tracebacks and Python `ast` function ranges | other stacks give weaker correlation | parsers for Java/Node/Go traces; tree-sitter for function ranges |
| Detection | Fixed thresholds; logs only | misses latency/CPU problems; needs tuning | EWMA/z-scores; metrics (Prometheus) input |
| Correlation | Hand-tuned weights; can't see causes outside the stack (config, data) | some incidents mis-ranked | learn weights from history; config/infra change feeds |
| Validation | Staging is a local process with in-memory data; replays only GET requests | environment-specific bugs missed | real staging; recorded-traffic replay with data snapshots |
| Deployment | Fast-forward of one branch; no canary, no automatic rollback | a bad deploy needs a manual revert | canary + metrics gate + automated rollback |
| Scale | One worker thread, SQLite, one AION instance | one investigation at a time | job queue + PostgreSQL + multiple workers |
| Retrieval | Lexical past-incident search; no docs/runbooks | less institutional knowledge | vector index over runbooks/postmortems |
| Data | Logs stored in SQLite forever | DB grows | retention policy; external log store |
| Audit | Append-only by API, not cryptographically | DB admin could alter history | hash-chained audit rows |

## Roadmap after the MVP (suggested order)

1. **Authentication + roles** for approve/deploy.
2. **Sandboxed validation** (Docker) and **secret redaction** in prompts.
3. **Real CI integration** behind the runner interface (push branch → GitHub Actions → poll checks) and open a **pull request** for the fix instead of direct fast-forward.
4. **Rollback**: one-click `git revert` of an AION deployment; then automatic rollback on failed verification.
5. **Metrics-based detection** and a canary step.
6. **More languages** (Java, Node.js).
7. **Knowledge retrieval** (runbooks/postmortems) with a vector index — where semantic search genuinely helps.
8. **Evaluation harness**: a set of seeded bugs to measure RCA accuracy and patch success rate per model.
