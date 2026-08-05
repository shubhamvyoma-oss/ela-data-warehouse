# Manual Import Engine

The import CLI accepts `.csv`, `.tsv`, and `.xlsx` files, validates headers and row widths, hashes the original file, and stores each accepted row unchanged in `bronze.manual_import_rows`.

```bash
python -m manual_imports.import_file \
  --source approved_student_reference \
  --file /app/data/imports/students.xlsx \
  --required-column user_id
```

Re-importing the same file for the same source is rejected by database uniqueness. Source files remain outside Git and should be moved to a restricted archive after verification.
