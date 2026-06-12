# Taskforce hook assets

These files are runtime copies of the canonical scripts in
`scripts/taskforce-hooks/` at the repository root. The backend Docker build
only includes the backend subtree, so the public installer endpoint packages
the copies here.

`tests/api/test_taskforce_installer.py` enforces byte-for-byte parity with the
canonical scripts.
