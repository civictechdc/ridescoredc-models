# legacy/

Flows parked here are **not synced**. `sync_git_flows` reads `kestra/flows/`
only, so anything in this folder is invisible to the server.

Move a flow here instead of deleting it when its YAML no longer validates —
typically after a plugin property rename. One broken file under `flows/` is one
failed import on every single sync, forever, until somebody notices.

Fix it and move it back, or leave it here as a record of what was tried.
