# Graph Report - forge  (2026-10-05)

## Corpus Check
- 36 files · ~6,617 words
- Verdict: corpus is large enough that graph structure adds value.

## Summary
- 362 nodes · 597 edges · 24 communities (16 shown, 8 thin omitted)
- Extraction: 78% EXTRACTED · 22% INFERRED · 0% AMBIGUOUS · INFERRED: 132 edges (avg confidence: 0.66)
- Token cost: 0 input · 0 output

## Community Hubs (Navigation)
- [[_COMMUNITY_contracts.py|contracts.py]]
- [[_COMMUNITY_ToolRegistry|ToolRegistry]]
- [[_COMMUNITY_api.py|api.py]]
- [[_COMMUNITY_Repository|Repository]]
- [[_COMMUNITY_TaskType|TaskType]]
- [[_COMMUNITY_LocalRepositoryScanner|LocalRepositoryScanner]]
- [[_COMMUNITY_init_db|init_db]]
- [[_COMMUNITY_base.py|base.py]]
- [[_COMMUNITY_Phase 1 architecture|Phase 1 architecture]]
- [[_COMMUNITY_provider.py|provider.py]]
- [[_COMMUNITY_test_api.py|test_api.py]]
- [[_COMMUNITY_client|client]]
- [[_COMMUNITY_test_inspect_accepts_positional_repository_path|test_inspect_accepts_positional_repository_path]]
- [[_COMMUNITY___init__.py|__init__.py]]
- [[_COMMUNITY___init__.py|__init__.py]]
- [[_COMMUNITY___init__.py|__init__.py]]
- [[_COMMUNITY___init__.py|__init__.py]]
- [[_COMMUNITY___init__.py|__init__.py]]
- [[_COMMUNITY___init__.py|__init__.py]]
- [[_COMMUNITY_forge-engineer|forge-engineer]]
- [[_COMMUNITY__Visitor|_Visitor]]
- [[_COMMUNITY_RepositoryProfiler|RepositoryProfiler]]
- [[_COMMUNITY_config.py|config.py]]

## God Nodes (most connected - your core abstractions)
1. `Repository` - 19 edges
2. `TaskType` - 19 edges
3. `TaskStatus` - 18 edges
4. `SqlRepositoryIndexer` - 17 edges
5. `RepositorySearch` - 16 edges
6. `IndexedFile` - 14 edges
7. `CodeSymbol` - 13 edges
8. `ImportRecord` - 13 edges
9. `RepositoryProfile` - 12 edges
10. `search_symbols()` - 11 edges

## Surprising Connections (you probably didn't know these)
- `search()` --indirect_call--> `session()`  [INFERRED]
  src/forge/apps/cli.py → tests/test_repository_intelligence.py
- `register()` --calls--> `Repository`  [INFERRED]
  tests/test_repository_intelligence.py → src/forge/core/models.py
- `test_traversal_enforces_file_count_limit()` --indirect_call--> `ScanLimitError`  [INFERRED]
  tests/test_repository_intelligence.py → src/forge/repository/files.py
- `test_traversal_enforces_file_count_limit()` --calls--> `ScanPolicy`  [INFERRED]
  tests/test_repository_intelligence.py → src/forge/repository/files.py
- `test_traversal_skips_ignored_binary_large_and_symlinked_files()` --calls--> `ScanPolicy`  [INFERRED]
  tests/test_repository_intelligence.py → src/forge/repository/files.py

## Import Cycles
- None detected.

## Communities (24 total, 8 thin omitted)

### Community 0 - "contracts.py"
Cohesion: 0.08
Nodes (29): Protocol, ExecutionResult, Patch, PatchManager, Plan, Path, Contracts for later phases; implementations must report real work., Detected repository identity, tooling, and layout. (+21 more)

### Community 1 - "ToolRegistry"
Cohesion: 0.08
Nodes (20): LocalRepositoryScanner, Path, Read-only local repository identity scanner., Resolve root and validate that its Git metadata is present., Check local Git identity without executing repository code or hooks., Any, Explicit registry of tools available to future agents., Structured tool contract; implementations must enforce their own policy. (+12 more)

### Community 2 - "api.py"
Cohesion: 0.32
Nodes (6): LogRecord, configure_logging(), JsonFormatter, Minimal structured logging without request bodies or source content., Serialize safe log metadata as one JSON object per line., Install a JSON handler on Forge's logger.

### Community 3 - "Repository"
Cohesion: 0.10
Nodes (36): FastAPI, ge, le, max_length, min_length, Query, SessionDependency, create_task() (+28 more)

### Community 4 - "TaskType"
Cohesion: 0.14
Nodes (26): BaseModel, CreateTaskRequest, ImportResponse, IndexUpdateResponse, HTTP request and response schemas., One indexed import statement target., Local path to a Git repository root., Registered repository identity. (+18 more)

### Community 5 - "LocalRepositoryScanner"
Cohesion: 0.06
Nodes (48): DeclarativeBase, index_repository(), Profile and incrementally index a registered repository., IndexUpdate, Measured result of one incremental index update., Base, Base class for persisted records., CodeSymbol (+40 more)

### Community 6 - "init_db"
Cohesion: 0.10
Nodes (24): Argument, Engine, inspect(), Path, Local Forge command line interface., Search indexed symbol definitions., Profile a local Git repository without running its code., Register a local Git repository. (+16 more)

### Community 7 - "base.py"
Cohesion: 0.19
Nodes (11): ABC, AgentConfig, AgentContext, AgentResult, BaseAgent, Base contract for future specialized agents., Agent identity and execution restrictions., Inputs shared with a single agent run. (+3 more)

### Community 8 - "Phase 1 architecture"
Cohesion: 0.10
Nodes (16): Forge architecture through Phase 2, Interfaces and boundaries, Phase 1 acceptance criteria, Security scope, Storage, Incremental index, Phase 2 scope, Profile (+8 more)

### Community 9 - "provider.py"
Cohesion: 0.28
Nodes (7): ModelMessage, ModelProvider, ModelResponse, Vendor-neutral model provider contract., Text response and optional token accounting., Complete a scoped prompt; callers must redact secrets first., One model conversation message.

### Community 10 - "test_api.py"
Cohesion: 0.43
Nodes (7): Path, TestClient, API persistence and validation tests., test_health(), test_index_profile_and_search_endpoints(), test_register_and_queue_task(), test_reject_non_git_root_and_unknown_repository()

### Community 11 - "client"
Cohesion: 0.33
Nodes (5): client(), Path, TestClient, Isolated API database fixtures., Run each API test against a separate SQLite file.

### Community 21 - "_Visitor"
Cohesion: 0.09
Nodes (21): AsyncFunctionDef, ClassDef, FunctionDef, Import, ImportFrom, Session, extract_python(), ExtractedImport (+13 more)

### Community 22 - "RepositoryProfiler"
Cohesion: 0.11
Nodes (22): configured_scan_policy(), iter_safe_files(), Path, Bounded, read-only traversal for untrusted repositories., Raised when a repository exceeds configured traversal limits., Limits and exclusions applied during repository traversal., Build traversal limits from process settings while retaining safe exclusions., A regular, in-root, non-binary file safe to read within its limit. (+14 more)

### Community 23 - "config.py"
Cohesion: 0.33
Nodes (6): BaseSettings, get_settings(), Process configuration; no credentials are stored in source., Return cached process settings., Settings loaded from environment or a local .env file., Settings

## Knowledge Gaps
- **14 isolated node(s):** `forge-engineer`, `Requirements`, `Run`, `Development`, `Phase 1 acceptance criteria` (+9 more)
  These have ≤1 connection - possible missing edges or undocumented components.
- **8 thin communities (<3 nodes) omitted from report** — run `graphify query` to explore isolated nodes.

## Suggested Questions
_Questions this graph is uniquely positioned to answer:_

- **Why does `SqlRepositoryIndexer` connect `LocalRepositoryScanner` to `contracts.py`, `Repository`, `_Visitor`, `RepositoryProfiler`?**
  _High betweenness centrality (0.198) - this node is a cross-community bridge._
- **Why does `RepositoryProfile` connect `contracts.py` to `ToolRegistry`, `Repository`, `LocalRepositoryScanner`, `RepositoryProfiler`?**
  _High betweenness centrality (0.148) - this node is a cross-community bridge._
- **Why does `PythonLanguageAdapter` connect `_Visitor` to `LocalRepositoryScanner`?**
  _High betweenness centrality (0.098) - this node is a cross-community bridge._
- **Are the 15 inferred relationships involving `Repository` (e.g. with `create_task()` and `find_dependents()`) actually correct?**
  _`Repository` has 15 INFERRED edges - model-reasoned connections that need verification._
- **Are the 15 inferred relationships involving `TaskType` (e.g. with `CreateTaskRequest` and `ImportResponse`) actually correct?**
  _`TaskType` has 15 INFERRED edges - model-reasoned connections that need verification._
- **Are the 15 inferred relationships involving `TaskStatus` (e.g. with `CreateTaskRequest` and `ImportResponse`) actually correct?**
  _`TaskStatus` has 15 INFERRED edges - model-reasoned connections that need verification._
- **Are the 13 inferred relationships involving `SqlRepositoryIndexer` (e.g. with `index_repository()` and `index_repository()`) actually correct?**
  _`SqlRepositoryIndexer` has 13 INFERRED edges - model-reasoned connections that need verification._