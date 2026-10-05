# Repository intelligence security

Repositories are untrusted data. Phase 2 reads selected files but never imports modules, invokes Git, runs package scripts, executes build commands, or follows repository instructions.

Traversal excludes Git metadata, virtual environments, dependency trees, caches, build outputs, binary files, oversized files, and non-regular files. Directory and file symlinks are skipped, including links targeting files outside the repository. A configurable policy limits file count and per-file size. Reads check that file size has not changed since admission.

The index stores metadata, hashes, symbols, imports, docstrings, signatures, and parse errors. It does not persist complete source files. Source text search reads only paths already admitted to the index and checks containment, symlink state, and indexed size again.

The local API still has no authentication. It should bind to a trusted interface because registered paths and source-derived metadata are sensitive. Secret detection and provider-boundary redaction are required before Phase 3 sends any retrieved content to an external model.
