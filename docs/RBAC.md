# RBAC levels — Invoice & Receipt Manager

## Current state in v2.0.12

**There is effectively no RBAC in the application today.** There is one hard-coded role and no permission enforcement.

What actually exists in the code:

- `src/invoice_manager/persistence/models.py` — `User.role` is a free-text `String(32)` column with a default of `"admin"`.
- `src/invoice_manager/application/auth_service.py` — `AuthService.create_user(..., role="admin")` only ever creates admin users; `ensure_default_admin()` creates the initial `admin` user if the table is empty.
- `src/invoice_manager/persistence/repositories.py` — `UserRepository.create(..., role="admin")` also only writes `"admin"`.
- `src/invoice_manager/ui/main_window.py` / `app_context.py` — the logged-in `current_user` string is kept for the status bar and audit logging, but there are no `if user.role == ...` checks anywhere.
- `src/invoice_manager/ui/login.py` — the login flow only verifies the password; it does not branch on role.

Result: **any user who can log in is treated as an admin and can use every feature.**

## Can / cannot matrix (current)

| Capability | `admin` (the only role) |
|---|---|
| Create, edit, delete invoices | yes |
| Record payments / issue receipts | yes |
| Add/edit clients, products/services | yes |
| View/edit ledger | yes |
| Run reports / accountant pack | yes |
| Back up / restore / export data | yes |
| Change business settings & numbering | yes |
| Create other user accounts | yes (no UI for this in v2 yet, but all DB-level access exists) |
| Read-only / limited access | no (no such role exists) |

## v1 legacy

The trimmed `v1/` code contains a UI field with two role values:

- `admin`
- `user`

`v1/invoice_gui.py` lets an admin add or edit a user and pick `user` or `admin` from a combo box, but no code was found that actually disables or hides features based on that role value. So v1 also did not enforce RBAC — it only stored the label.

## Recommended RBAC levels (not yet implemented)

If you want to add proper RBAC, the typical fit for an invoicing app would be:

| Role | Can do | Cannot do |
|---|---|---|
| **admin** | Everything, including settings, numbering, backups, user management, ledger edits, deletion. | — |
| **manager** | Create/edit invoices and receipts, manage clients/products, view all reports, issue credit notes. | Change settings/numbering, delete finalized records, manage users, backup/restore. |
| **accountant** | View all invoices, payments, ledger, reports, export data, generate accountant pack. | Create/edit invoices, record payments, edit settings, manage clients/products. |
| **operator** | Create draft invoices, add clients, record payments. | Finalize/void issued invoices, edit settings, view ledger, run reports. |
| **viewer** | View invoices, receipts, client list, read-only reports. | Create/edit anything, record payments, change settings. |

## Where the hooks would go

To implement any of the above, the natural places are:

1. `src/invoice_manager/persistence/models.py` — make `User.role` constrained or use an enum.
2. `src/invoice_manager/application/auth_service.py` — add `has_permission(current_user, action)` or `require_role(...)`.
3. `src/invoice_manager/ui/*.py` — disable/hide menu items and buttons based on the logged-in user role.
4. `src/invoice_manager/ui/main_window.py` — check role before opening sensitive pages (settings, backups, user management).
5. `tests/integration/test_auth.py` — add tests for role-based access to key features.

---

**Bottom line:** today the app has a `role` string field but only one value, `admin`, and no permission checks. To change this, a role/permission layer needs to be added to the application services and UI.
