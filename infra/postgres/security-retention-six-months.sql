-- Owner-run retention policy; identical to revision 0018. No purge is executed.
-- Does not stamp alembic_version; coordinate application-image upgrades separately.
BEGIN;
CREATE OR REPLACE FUNCTION public.purge_security_events() RETURNS bigint
LANGUAGE plpgsql SECURITY DEFINER
SET search_path = pg_catalog SET TimeZone = 'UTC'
SET sinegor.security_retention_months = '6'
AS $function$

        DECLARE
            removed_count bigint;
            first_at timestamptz;
            last_at timestamptz;
            subjects_json jsonb;
            completed_at timestamptz;
            operation_uuid uuid;
        BEGIN
            WITH removed AS (
                DELETE FROM public.security_events WHERE
                    recorded_at + make_interval(months =>
                        current_setting('sinegor.security_retention_months')::integer)
                    <= statement_timestamp()
                RETURNING user_id, user_role, subject_user_id, recorded_at
            ), principals AS (
                SELECT user_id AS identifier, user_role AS role
                FROM removed WHERE user_id IS NOT NULL
                UNION
                SELECT subject_user_id, 'customer' FROM removed WHERE subject_user_id IS NOT NULL
                UNION
                SELECT NULL::uuid, NULL::text FROM removed
                  WHERE user_id IS NULL AND subject_user_id IS NULL
            ), identities AS (
                SELECT DISTINCT jsonb_build_object(
                    'identity', CASE WHEN p.identifier IS NULL THEN
                        'Определить субъекта невозможно: событие не содержит ' ||
                        'идентификатора субъекта'
                    ELSE COALESCE(NULLIF(btrim(c.display_name),''), c.email, a.email,
                        'Учётная запись ' || p.role || ': ' || p.identifier::text ||
                        '; ФИО отсутствует в доступных источниках') END,
                    'source', CASE WHEN c.display_name IS NOT NULL AND btrim(c.display_name)<>''
                        THEN 'customers.display_name'
                        ELSE 'security_events; available principal metadata' END,
                    'categories', CASE WHEN p.identifier IS NULL THEN
                        jsonb_build_array('События безопасности', 'Идентификаторы запросов')
                    ELSE jsonb_build_array('События безопасности', 'Идентификаторы запросов',
                                          'Идентификаторы учётных записей') END
                ) AS subject
                FROM principals p
                LEFT JOIN public.customers c ON p.role='customer' AND c.id=p.identifier
                LEFT JOIN public.admin_users a ON p.role='admin' AND a.id=p.identifier
            )
            SELECT count(*), min(recorded_at), max(recorded_at),
                (SELECT jsonb_agg(subject ORDER BY subject::text) FROM identities)
                INTO removed_count, first_at, last_at, subjects_json FROM removed;
            IF removed_count = 0 THEN RETURN 0; END IF;
            completed_at := clock_timestamp();
            operation_uuid := gen_random_uuid();
            INSERT INTO public.destruction_operations
                (id, created_at, updated_at, idempotency_key, kind, state, metadata_json,
                 destroyed_at, expires_at)
            VALUES (operation_uuid, completed_at, completed_at,
                'security_events:' || operation_uuid::text, 'security_events', 'documents_pending',
                jsonb_build_object(
                    'subjects', subjects_json,
                    'entity', jsonb_build_object('batch_count', removed_count,
                        'first_recorded_at', first_at, 'last_recorded_at', last_at),
                    'source', 'security_events',
                    'basis', 'Истечение срока хранения журнала безопасности (' ||
                             current_setting('sinegor.security_retention_months') ||
                             ' календарных месяцев)',
                    'method', 'Удаление записей PostgreSQL функцией ' ||
                              'purge_security_events (SECURITY DEFINER)',
                    'initiator', session_user::text, 'executor', session_user::text
                ), completed_at, completed_at + interval '3 years');
            RETURN removed_count;
        END;
    
$function$;
COMMIT;
