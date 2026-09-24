# Decision log

Accepted decisions from build specification Part L:

1. Assign permanent invoice numbers at issue.
2. Offer receipt generation after payment; generate once and permit reissue.
3. Keep the live database local; use OneDrive for backups only.
4. Copy attachments into managed storage by default.
5. Treat the NAB advice as confirmed payment for INV-0001.
6. Import INV-0002 and INV-0003 legacy payments flagged for missing date/evidence.
7. Keep `0001-1` and `ERROR` only as migration issues, never financial records.
8. Import the current setting as not GST registered; documents say `INVOICE`.
9. Use GST-exclusive price entry by default.
10. Overdue takes precedence over Part Paid whenever a positive balance remains past the due date.
11. An invoice cleared by a mix of payments and credits is Paid; Credited is reserved for balances cleared purely by credits.
12. GST rates are stored as decimal fractions: `0.1000` represents 10% GST. Percentage discounts remain values from 0 to 100.
