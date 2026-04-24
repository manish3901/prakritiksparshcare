## Reference Tables Migration Task List

Goal: remove hardcoded dropdown/business option values from templates/routes and move them into database-managed tables.

### Done
- Added `reference_options` table (generic option catalog).
- Seeded `reference_options` for key categories (access role, statuses, support query types, product filter).
- Updated `pin_types` seeds to include `Joining` and `Trial Pin`.
- Wired option lists into the `/home` render context.
- Updated admin/user dropdowns in `home.html` to read from DB-driven lists.
- Fixed `/admin/legal-document/create` crash (`LegalDocument` import).
- Updated `psc_cloud_schema.sql` to include `reference_options` table, indexes, and seed rows.

### Next (Recommended)
- Move `withdraw_status` values in routes/analytics to read from `reference_options` instead of hardcoding counts/labels.
- Move `LEVEL_PRODUCTS` (`pad/diaper`) to be derived from `product_types` so adding products is fully data-driven.
- Replace `user_login.product_type = 'Both'` with a proper mapping table (user-product access) so it's not stored as a magic string.
- Convert `user_login.status`, `approval_status`, `WithdrawRequest.status`, `SupportTicket.status`, `EPin.status` to constrained values:
  - Option A: enforce at app-layer only (fastest).
  - Option B: enforce via DB `CHECK` constraints (strongest).
- Add small admin UI for managing `reference_options` categories (enable/disable, reorder, rename).

