# Analytics-engine PPL IT Compatibility Report

The analytics-compatibility report measures what fraction of the SQL plugin's existing PPL integration tests pass when every PPL query is forced through the analytics-engine route (Calcite → Substrait → DataFusion) instead of the legacy V2 engine.

The output is a markdown report at `integ-test/build/reports/analytics-compatibility/REPORT.md` containing a Summary table, failures-by-category breakdown (Correctness / Unsupported / Stability), an Out-of-scope section, top-25 failure buckets, and a top-15 detailed breakdown (every failing `Class.test` per bucket). The Correctness drill-down (grouped-by-message + top-10 Appendix) lives in the sibling `CORRECTNESS_REPORT.md`.

This doc is the runbook: setup, the commands, what to do when it crashes, and how to read the result.

---

## 1. Prerequisites

Two checked-out worktrees:

| Worktree | Repo | Why |
|---|---|---|
| `~/IdeaProjects/sql-ppl-coverage-bundle` | `opensearch-project/sql` | Drives the report task; contains the test set and report tooling. |
| `~/IdeaProjects/OpenSearch-search-fix` | `opensearch-project/OpenSearch` | Runs the OpenSearch cluster (with all analytics-engine plugins) the tests execute against. |

Both should be on top of (a recent) `upstream/main`, optionally with extra PRs cherry-picked or merged.

Toolchain:

- **JDK 21** (Temurin) for the SQL plugin build and the report task.
- **JDK 25** (Temurin) for the OpenSearch cluster JVM — required by `-Dsandbox.enabled=true` modules.
- **Cargo / Rust toolchain** for `analytics-backend-datafusion`'s native lib (`libopensearch_native.dylib`).
- `mavenLocal` is used as the artifact hand-off path between the OS worktree and the SQL worktree.

---

## 2. The pipeline (4 stages)

### Stage 1 — Sync both repos with `upstream/main`

```bash
# SQL bundle
cd ~/IdeaProjects/sql-ppl-coverage-bundle
git fetch upstream main
git rebase upstream/main

# OpenSearch
cd ~/IdeaProjects/OpenSearch-search-fix
git fetch upstream main
git rebase upstream/main
```

After each rebase, verify the merge-base matches `upstream/main` (a silent rebase failure has bitten us before — the message "Successfully rebased" must actually appear):

```bash
git merge-base HEAD upstream/main   # must equal:
git rev-parse upstream/main
```

If they differ, the rebase didn't take — usually because of unstaged changes blocking it. Commit or stash, then re-run.

### Stage 2 — Publish artifacts to local maven

The SQL plugin depends on the analytics SPI shipped by `sandbox/libs/analytics-api`. When either side moves, both jars need to be republished:

```bash
# In the OpenSearch worktree:
cd ~/IdeaProjects/OpenSearch-search-fix
./gradlew :sandbox:libs:analytics-api:publishToMavenLocal -Dsandbox.enabled=true

# Then the SQL plugin (depends on the fresh analytics-api jar):
cd ~/IdeaProjects/sql-ppl-coverage-bundle
./gradlew publishPluginZipPublicationToMavenLocal -x test -x integTest
```

Order matters — SQL fails to compile if analytics-api hasn't been refreshed first (`BinaryType`, `IpType`, `AggregateFunction` enum members get added periodically).

### Stage 3 — Rebuild the rust native lib (when rust changed)

The analytics-engine route loads `libopensearch_native.dylib` at JVM startup. If any rust source moved, the cluster's `<clinit>` will throw `NoSuchElementException` on `lib.find("<symbol>").orElseThrow()` and refuse to start.

Detect whether a rebuild is needed:

```bash
cd ~/IdeaProjects/OpenSearch-search-fix
find sandbox -name '*.rs' -newer sandbox/libs/dataformat-native/rust/target/release/libopensearch_native.dylib | wc -l
```

If non-zero, rebuild (typical wall time: 10-12 minutes):

```bash
cd ~/IdeaProjects/OpenSearch-search-fix/sandbox/libs/dataformat-native/rust
~/.cargo/bin/cargo build -p opensearch-native-lib --release
```

### Stage 4 — Start the cluster, then run the report

Start the OpenSearch cluster in one terminal:

```bash
cd ~/IdeaProjects/OpenSearch-search-fix
JAVA_HOME=~/.local/share/mise/installs/java/temurin-25.0.1+8.0.LTS \
  ./gradlew :run -Dsandbox.enabled=true \
  -PinstalledPlugins="['opensearch-job-scheduler:3.7.0.0-SNAPSHOT', 'arrow-base', 'arrow-flight-rpc', 'analytics-engine', 'parquet-data-format', 'analytics-backend-datafusion', 'analytics-backend-lucene', 'composite-engine', 'opensearch-sql-plugin:3.7.0.0-SNAPSHOT']"
```

Wait for `cluster-manager node changed` and verify it's GREEN:

```bash
curl -s http://localhost:9200/_cluster/health
```

Also verify that *our* worktree owns port 9300 (not some other cluster from another worktree):

```bash
lsof -nP -iTCP:9300 -sTCP:LISTEN | awk 'NR>1{print $2}' | head -1 | \
  while read pid; do ps -p $pid -o command | grep -oE 'opensearch.path.home=[^ ]*'; done
```

The path must point at `~/IdeaProjects/OpenSearch-search-fix/build/testclusters/runTask-0/...`. If it points anywhere else, kill that other JVM first (see "Pitfalls" below).

In a second terminal, launch the report:

```bash
cd ~/IdeaProjects/sql-ppl-coverage-bundle
./gradlew :integ-test:analyticsCompatibilityReport \
  -Dtests.rest.cluster=localhost:9200 \
  -Dtests.cluster=localhost:9300 \
  -Dtests.clustername=runTask \
  -Dhttps=false \
  -PclusterLog=~/IdeaProjects/OpenSearch-search-fix/build/testclusters/runTask-0/logs/runTask.log
```

Typical runtime: **10-13 minutes** end-to-end. Output: `integ-test/build/reports/analytics-compatibility/REPORT.md`.

---

## 3. Regenerate the report from existing XMLs (no test run)

After tweaking the report-generation logic in `integ-test/build.gradle` (exclusions, formatting, new sections), regenerate against the most recent test results in ~15 seconds:

```bash
cd ~/IdeaProjects/sql-ppl-coverage-bundle
./gradlew :integ-test:analyticsCompatibilityReport -x :integ-test:analyticsCompatibilityTest \
  -PclusterLog=~/IdeaProjects/OpenSearch-search-fix/build/testclusters/runTask-0/logs/runTask.log
```

The `-x :integ-test:analyticsCompatibilityTest` skips test execution; the report just walks `integ-test/build/test-results/analyticsCompatibility/TEST-*.xml`.

---

## 4. What the report contains

| Section | Purpose |
|---|---|
| Summary | Total tests / in-scope / passed / failed / skipped / pass-rate / out-of-scope / runtime. |
| Failures by category | Splits in-scope failures into three buckets: *Correctness* (test-side AssertionError on response), *Unsupported* (declared limitation — `IllegalStateException`, `UnsupportedOperationException`, `SubstraitConversionException`, Calcite Litmus.THROW `AssertionError`, "No backend supports …" messages), and *Stability* (engine bug — `NullPointerException`, `IndexOutOfBoundsException`, `ClassCastException`, `IllegalArgumentException`, etc.). Classifier lives in `integ-test/build.gradle` around line 1650. |
| Out of scope | Lists every excluded class and message-pattern with its counts. Adjusted via `OUT_OF_SCOPE_CLASSES` and `OUT_OF_SCOPE_MESSAGE_PATTERNS` in `integ-test/build.gradle`. |
| Top 25 failure buckets | Failures grouped by normalized message, ordered by count. |
| Top 15 detailed breakdown | For each of the top 15, every failing `Class.test` enumerated. |

---

## 5. Pitfalls (in priority order)

### "No tests found for given includes" — stale Gradle build cache

Symptom: report task fails in ~17s with `> No tests found for given includes: [**/*IT.class]...`.

Cause: Gradle's build cache restored a stale `compileTestJava` output that's missing `org/opensearch/sql/calcite/` and `org/opensearch/sql/ppl/` packages. The filter then matches zero classes.

Fix:

```bash
cd ~/IdeaProjects/sql-ppl-coverage-bundle
rm -rf integ-test/build/classes/java/test
./gradlew :integ-test:compileTestJava --rerun-tasks --no-build-cache
```

Verify `integ-test/build/classes/java/test/org/opensearch/sql/calcite/remote/` now contains `*.class` files.

### Cluster crashes mid-run, ~1.2% pass rate, ~4-minute runtime

Symptom: pass rate is in the low single digits, runtime is far shorter than usual (~4 min instead of ~10 min). Usually means the cluster died early and every subsequent request got `Connection refused`.

Don't restart blindly — find the root cause:

1. Tail the cluster log for the fatal exception:
   ```bash
   grep -A30 "OpenSearchUncaughtExceptionHandler" \
     ~/IdeaProjects/OpenSearch-search-fix/build/testclusters/runTask-0/logs/opensearch.stdout.log | tail -40
   ```
2. Classify by stack:
   - `Litmus.THROW` AssertionError in `Aggregate.typeMatchesInferred` / `Project.isValid` → catch-site missing somewhere on the planner path. Look in `UnifiedQueryPlanner.plan()` and `DefaultPlanExecutor.execute` / `doExecute`.
   - `NativeBridge.<clinit>` `NoSuchElementException` → stale rust dylib missing a new symbol. Rebuild rust.
   - `Guice` injection failure → missing feature flag (`opensearch.experimental.feature.transport.stream.enabled=true`) or wrong plugin order.
   - `BindException: Address already in use` → another OpenSearch JVM holds 9200/9300 (see below).
3. Fix the source code, then wipe and restart:
   ```bash
   rm -rf ~/IdeaProjects/OpenSearch-search-fix/build/testclusters/runTask-0
   ```

### Port conflict (another worktree's cluster owns 9200/9300)

Symptom: cluster reports GREEN but the report numbers look contaminated. The `lsof` check from Stage 4 shows a path that isn't our worktree.

Fix: kill the foreign JVM + its gradle wrapper:

```bash
ps -ef | grep -E "OpenSearch.*runTask|gradlew :run" | grep -v grep
# kill <gradle-pid> <opensearch-pid>
```

Then wipe + restart our cluster.

### `Field [BinaryType]` / `Field [IpType]` compile errors during SQL publish

Symptom: `:core:compileJava` fails with `cannot find symbol: class BinaryType` in `OpenSearchTypeFactory.java`.

Cause: the SQL plugin source references a class that exists in OpenSearch's `analytics-api` source, but the locally-published `analytics-api-*.jar` is stale (predates the new class).

Fix: re-run Stage 2 from the top — publish `analytics-api` first, then the SQL plugin.

### Cluster JVM survives but reports an early `BindException`

Symptom: the cluster log shows `BindException: Address already in use` near the top, but `curl` still reports GREEN. This means a *different* JVM is answering on the same port.

Same fix as "Port conflict" — find and kill the foreign JVM.

---

## 6. Tuning the report

All knobs live in `integ-test/build.gradle` at the top of the `analyticsCompatibilityReport` task body:

| Knob | What it controls |
|---|---|
| `OUT_OF_SCOPE_CLASSES` | Whole IT classes excluded from the pass-rate denominator. |
| `OUT_OF_SCOPE_MESSAGE_PATTERNS` | Substring patterns matched against failure body; matching tests excluded. |
| `UNSUPPORTED_EXC_SIMPLE` / `STABILITY_EXC_SIMPLE` / `UNSUPPORTED_MSG_HINTS` | Per-category exception/message classifier sets (Failures-by-category table). |
| `TOP_BUCKETS` | Top-N buckets shown in the headline table (default 25). |
| `DETAIL_BUCKETS` | Top-N buckets shown with full failing-tests list (default 15). |

Don't forget to commit the build.gradle change before pushing.

---

## 7. Pushing report-tooling changes to the fork

When local report-tooling commits are ready to share:

```bash
cd ~/IdeaProjects/sql-ppl-coverage-bundle
git push ahkcs feature/ppl-coverage-bundle --force-with-lease
```

`--force-with-lease` is required because the branch is regularly rebased onto `upstream/main`; it refuses to overwrite if the remote has unseen commits.

---

## 8. Where to look in the source

| What | Where |
|---|---|
| Report task definition | `integ-test/build.gradle` — task `analyticsCompatibilityReport` |
| Test execution task | `integ-test/build.gradle` — task `analyticsCompatibilityTest` |
| XML output | `integ-test/build/test-results/analyticsCompatibility/TEST-*.xml` |
| Report markdown | `integ-test/build/reports/analytics-compatibility/REPORT.md` |
| Force-routing toggle (cluster-side) | `plugin/.../rest/RestUnifiedQueryAction.java` — checks `CALCITE_ANALYTICS_FORCE_ROUTING` setting |
| Cluster log (used for origin attribution) | `~/IdeaProjects/OpenSearch-search-fix/build/testclusters/runTask-0/logs/runTask.log` |
