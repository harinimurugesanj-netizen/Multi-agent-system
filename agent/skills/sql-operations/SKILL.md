---
name: sql-operations
description: Write and run one PostgreSQL statement (SELECT, INSERT, UPDATE or DELETE) for the user's database request, using the exact table and column names from the supplied schema. Use for any request to show, find, list, count, add, change or delete database records.
---
## SQL Data Type Rules

- Read the database schema and check each column's data type before generating SQL.
- Use ILIKE only for text columns such as VARCHAR and TEXT.
- For DATE columns, use = for exact date comparisons and <, >, <=, or >= for date ranges.
- Never use ILIKE on DATE, INTEGER, NUMERIC, or BOOLEAN columns.
- For exact dates, use the YYYY-MM-DD format, such as '2002-05-15'.
- Never use 'YYYY-MM-DD' as an actual date value; it is a format pattern.
- For year-based searches, use EXTRACT(YEAR FROM "column_name") = year.
- Use operators appropriate to the column's data type.
- Never invent column names or data types; follow the provided database schema.

# sql-operations

You turn a user's request into ONE correct PostgreSQL statement and run it with the `execute_sql` tool.
The DATABASE SCHEMA is supplied with every request. It is the only source of truth for table and column names.

## Workflow (follow in this order)

1. Read the USER REQUEST and decide the operation (see "Choose the operation").
2. Find the table(s) and column(s) in the schema that match the request.
3. Write exactly ONE SQL statement using the rules below.
4. Call `execute_sql` once with that statement in the `sql` argument.
5. If the tool returns an error, fix the SQL using the "Fixing errors" section and call `execute_sql` again.

Never answer from memory or invent results. Never skip `execute_sql`.

## Choose the operation

Only generate SELECT, INSERT, UPDATE or DELETE. Never generate DROP, TRUNCATE, ALTER, CREATE, GRANT or REVOKE.

## Identifier rules (most common source of errors)

- Wrap EVERY table name and column name in double quotes, exactly as written in the schema: `"users"`, `"User_name"`, `"Organisation"`.
- PostgreSQL lowercases unquoted names, so `User_name` without quotes breaks. Always quote.
- Copy spelling and capitalization from the schema. Never guess, shorten or rename: use `"User_name"`, never `username`, `name` or `"username"`.
- Use only tables and columns that appear in the schema. If the user mentions something that is not in the schema, use the closest matching column from the schema instead of inventing one.
- In a JOIN, qualify every column with its table: `"users"."User_name"`.

## Value rules

- Text values use SINGLE quotes: `'hari'`. Never use double quotes for values.
- Numbers have no quotes: `8`. But if the schema says the column is VARCHAR (for example `"Org_id"`), quote the value: `'1'`.
- Dates use `'YYYY-MM-DD'`.
- Use only values the user gave. Never invent ids, names or other values. For INSERT, include only the columns the user provided.

## Filtering rules

- Text columns: use `ILIKE` (case-insensitive). Exact name: `ILIKE 'hari'`. If the user says "contains", "like" or "starts with", use `'%hari%'` or `'hari%'`.
- IDs, numbers and dates: use `=`.
- Several conditions: combine with `AND` / `OR` and keep each column quoted.

## Statement rules

- SELECT: add `LIMIT 500` unless it is an aggregate query (COUNT, SUM, AVG, MIN, MAX).
- Aggregates ("how many", "total", "average", "per organisation"): use `COUNT`, `SUM`, `AVG`, `MIN`, `MAX` with `GROUP BY` for each non-aggregated selected column.
- JOIN: when the user asks for related data (for example a user with their organisation), join using the FK lines in the schema and select named columns from both tables instead of only foreign key ids. Never use `SELECT *` with a JOIN.
- INSERT, UPDATE, DELETE: end with `RETURNING *`.
- UPDATE and DELETE: ALWAYS include a `WHERE` clause that identifies the intended rows. Never write an UPDATE or DELETE without WHERE.
- Write exactly one statement. No semicolon-separated batches, no comments, no markdown.
- DELETE is not run immediately; the system asks the user to confirm. Still write the correct DELETE statement and call `execute_sql`.

## Examples (tables from the current schema; always trust the schema in the request over these)

Request: get the user details of hari
```sql
SELECT * FROM "users" WHERE "User_name" ILIKE 'hari' LIMIT 500
```

Request: show the name and email of the organisation google
```sql
SELECT "Org_name", "Org_email" FROM "Organisation" WHERE "Org_name" ILIKE 'google' LIMIT 500
```

Request: get harini's name and designation with her organisation details
```sql
SELECT "users"."User_name", "users"."Designation", "Organisation"."Org_name", "Organisation"."Org_address", "Organisation"."Org_email" FROM "users" JOIN "Organisation" ON "users"."Org_id" = "Organisation"."Org_id" WHERE "users"."User_name" ILIKE 'harini' LIMIT 500
```

Request: how many users are in each organisation
```sql
SELECT "Organisation"."Org_name", COUNT("users"."User_id") AS "user_count" FROM "users" JOIN "Organisation" ON "users"."Org_id" = "Organisation"."Org_id" GROUP BY "Organisation"."Org_name"
```

Request: list all users whose name starts with ha
```sql
SELECT * FROM "users" WHERE "User_name" ILIKE 'ha%' LIMIT 500
```

Request: add user harini with id 8 in organisation 1
```sql
INSERT INTO "users" ("User_id", "User_name", "Org_id") VALUES (8, 'harini', '1') RETURNING *
```

Request: change the designation of user 8 to Senior Dev
```sql
UPDATE "users" SET "Designation" = 'Senior Dev' WHERE "User_id" = 8 RETURNING *
```

Request: delete the user with id 5
```sql
DELETE FROM "users" WHERE "User_id" = 5 RETURNING *
```

## Fixing errors

When `execute_sql` returns an error, read the real database message and correct the SQL. Do not repeat the same statement.

| Error message contains | Likely cause | Fix |
|---|---|---|
| `column ... does not exist` | Wrong name or missing double quotes | Recheck the exact column name in the schema and quote it |
| `relation ... does not exist` | Wrong table name or missing quotes | Use the exact table name from the schema in double quotes |
| `syntax error` | Double quotes around a value, missing comma, extra text | Values use single quotes; output only the SQL statement |
| `invalid input syntax for type` | Value type does not match the column | Quote VARCHAR values, leave numbers unquoted, dates as `'YYYY-MM-DD'` |
| `column reference ... is ambiguous` | Same column name in joined tables | Prefix the column with its table name |
| `violates foreign key constraint` | The referenced row does not exist | Use a valid value for the foreign key column |
| `must appear in the GROUP BY clause` | Selected column missing from GROUP BY | Add it to GROUP BY or aggregate it |

If you still cannot fix the query, stop and report the real error. Do not make up a result.

## Never

- Never invent tables, columns, ids or results.
- Never use unquoted identifiers.
- Never write UPDATE or DELETE without WHERE.
- Never write more than one statement.
- Never return SQL as text without calling `execute_sql`.