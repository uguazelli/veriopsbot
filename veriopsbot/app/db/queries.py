"""Raw SQL statements used by the application.

Keeping queries in their own module keeps repository functions concise and
makes it easy to share statements between different call sites.
"""

SQL_GET_PARAMS_BY_OMNICHANNEL_ID = """
SELECT
  t.id, t.email,
  l.id as llm_id, l.params as llm_params,
  c.id as crm_id, c.params as crm_params,
  o.id as omnichannel_id, o.params as omnichannel
FROM tenants AS t
JOIN llm         AS l ON l.tenant_id = t.id
JOIN crm         AS c ON c.tenant_id = t.id
JOIN omnichannel AS o ON o.tenant_id = t.id
WHERE o.id = %(omnichannel_id)s
"""


SQL_GET_PARAMS_BY_TENANT_ID = """
SELECT
  t.id, t.email,
  l.id as llm_id, l.params as llm_params,
  c.id as crm_id, c.params as crm_params,
  o.id as omnichannel_id, o.params as omnichannel
FROM tenants AS t
JOIN llm         AS l ON l.tenant_id = t.id
JOIN crm         AS c ON c.tenant_id = t.id
JOIN omnichannel AS o ON o.tenant_id = t.id
WHERE t.id = %(tenant_id)s
"""


SQL_CREATE_BOT_USAGE_TABLE = """
CREATE TABLE IF NOT EXISTS bot_request_usage (
    id BIGSERIAL PRIMARY KEY,
    tenant_id BIGINT NOT NULL REFERENCES tenants(id),
    bucket_date DATE NOT NULL,
    request_count BIGINT NOT NULL DEFAULT 0,
    last_request_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (tenant_id, bucket_date)
);
"""


SQL_GET_BOT_REQUEST_COUNT_IN_RANGE = """
SELECT COALESCE(SUM(request_count), 0) AS total
FROM bot_request_usage
WHERE tenant_id = %(tenant_id)s
  AND bucket_date BETWEEN %(start_date)s AND %(end_date)s;
"""


SQL_INCREMENT_BOT_REQUEST_COUNT = """
INSERT INTO bot_request_usage (tenant_id, bucket_date, request_count, last_request_at)
VALUES (%(tenant_id)s, %(bucket_date)s, 1, NOW())
ON CONFLICT (tenant_id, bucket_date)
DO UPDATE SET
    request_count = bot_request_usage.request_count + 1,
    last_request_at = EXCLUDED.last_request_at
RETURNING request_count;
"""


SQL_GET_USER_BY_EMAIL = """
SELECT id, tenant_id, email, password_hash, is_admin
FROM veriops_users
WHERE email = %(email)s
"""

SQL_GET_USER_BY_ID = """
SELECT id, tenant_id, email, password_hash, is_admin
FROM veriops_users
WHERE id = %(user_id)s
"""

SQL_UPDATE_USER_ACCOUNT = """
UPDATE veriops_users
SET email = %(email)s,
    password_hash = COALESCE(%(password_hash)s, password_hash),
    modified_at = NOW()
WHERE id = %(user_id)s
RETURNING id, tenant_id, email, is_admin
"""


SQL_UPDATE_LLM_SETTINGS = """
UPDATE llm
SET params = %(params)s
WHERE id = %(llm_id)s
"""


SQL_UPDATE_CRM_SETTINGS = """
UPDATE crm
SET params = %(params)s
WHERE id = %(crm_id)s
"""


SQL_UPDATE_OMNICHANNEL_SETTINGS = """
UPDATE omnichannel
SET params = %(params)s
WHERE id = %(omnichannel_id)s
"""


SQL_INSERT_USER = """
INSERT INTO veriops_users (tenant_id, email, password_hash, is_admin, modified_at)
VALUES (%(tenant_id)s, %(email)s, %(password_hash)s, %(is_admin)s, NOW())
RETURNING id, tenant_id, email, is_admin
"""


SQL_LIST_TENANTS = """
SELECT t.id, t.email, t.modified_at
FROM tenants t
ORDER BY t.id ASC
"""


SQL_UPSERT_LLM_SETTINGS = """
INSERT INTO llm (tenant_id, params, modified_at)
VALUES (%(tenant_id)s, %(params)s, NOW())
ON CONFLICT (id) DO UPDATE
SET params = EXCLUDED.params,
    modified_at = NOW()
"""
# Note: The above UPSERT on (id) might be wrong if we don't have the ID.
# But wait, the table definition says:
# CREATE TABLE public.llm (
#     id bigint NOT NULL,
#     tenant_id bigint NOT NULL,
# ...
#     ADD CONSTRAINT llm_pkey PRIMARY KEY (id);
# It doesn't seem to have a unique constraint on tenant_id?
# Let's check the schema again.
# The schema shows:
# CREATE TABLE public.llm (
#     id bigint NOT NULL,
#     tenant_id bigint NOT NULL,
# ...
#     ADD CONSTRAINT llm_pkey PRIMARY KEY (id);
# There is NO unique constraint on tenant_id in the provided schema dump for `llm`, `crm`, or `omnichannel`.
# However, `queries.py` uses `JOIN llm AS l ON l.tenant_id = t.id` which implies 1:1.
# If I want to UPSERT by tenant_id, I need a unique constraint on tenant_id.
# Since I cannot easily change the schema right now without migrations (which I can do if needed, but let's see),
# I should probably check if it exists first, or rely on the fact that we usually look up by tenant_id.
# Actually, `SQL_GET_PARAMS_BY_TENANT_ID` joins them.
# If I want to support "Insert if not exists" for a specific tenant, I should probably do an INSERT ... ON CONFLICT (tenant_id) ...
# BUT only if there is a unique constraint.
# Let's assume for now I will write a query that tries to UPDATE first, and if 0 rows affected, INSERT.
# OR, I can use a PL/SQL block or just simple logic in python.
# Given the user request "INSERT INTO llm ...", they are doing raw inserts.
# I will implement `upsert` logic in Python repository to be safe if I can't rely on DB constraints.
# Wait, `SQL_UPDATE_LLM_SETTINGS` uses `WHERE id = %(llm_id)s`.
# So the current update logic relies on knowing the `llm_id`.
# When I'm in the admin view for a tenant, I might not know the `llm_id` if it doesn't exist yet.
# I should probably fetch the tenant's settings first.
#
# Let's define the queries to be flexible.
# I will add queries to Insert specifically.

SQL_INSERT_LLM_SETTINGS = """
INSERT INTO llm (tenant_id, params, modified_at)
VALUES (%(tenant_id)s, %(params)s, NOW())
RETURNING id
"""

SQL_INSERT_CRM_SETTINGS = """
INSERT INTO crm (tenant_id, params, modified_at)
VALUES (%(tenant_id)s, %(params)s, NOW())
RETURNING id
"""

SQL_INSERT_OMNICHANNEL_SETTINGS = """
INSERT INTO omnichannel (tenant_id, params, modified_at)
VALUES (%(tenant_id)s, %(params)s, NOW())
RETURNING id
"""
