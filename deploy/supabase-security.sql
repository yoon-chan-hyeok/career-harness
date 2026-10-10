-- Dedicated Career Harness project. Browser clients use Supabase Auth only, never these tables.
-- The backend server uses the private DB owner connection and enforces user_id in repositories.
-- One transaction: no policy grants to anon/authenticated; existing application rows are untouched.
BEGIN;
DO $career_security$
DECLARE
  table_name text;
  role_name text;
  career_tables text[] := ARRAY[
    'users','domain_records','sources','career_facts','evidences','artifacts',
    'application_workspaces','artifact_feedback_events','document_revision_events','prompt_runs',
    'execution_runs','ai_usage_settings','ai_usage_buckets','ai_usage_reservations','service_members','request_rate_buckets',
    'editor_drafts','local_evidence_embeddings','projects','decision_episodes','metrics','ownership_records','claim_boundaries',
    'writing_rules','expression_records','capability_records','opportunities','application_questions',
    'opportunity_job_outputs','opportunity_evidence_maps','artifact_dependencies','draft_versions',
    'company_research_results','review_issues','submission_snapshots','interview_handoff_records',
    'selection_outcomes','postmortem_hypotheses','correction_records','evidence_embeddings','alembic_version'
  ];
BEGIN
  FOREACH table_name IN ARRAY career_tables LOOP
    IF to_regclass(format('public.%I', table_name)) IS NOT NULL THEN
      EXECUTE format('ALTER TABLE public.%I ENABLE ROW LEVEL SECURITY', table_name);
      EXECUTE format('REVOKE ALL ON TABLE public.%I FROM PUBLIC', table_name);
      FOREACH role_name IN ARRAY ARRAY['anon', 'authenticated'] LOOP
        IF EXISTS(SELECT 1 FROM pg_roles WHERE rolname=role_name) THEN
          EXECUTE format('REVOKE ALL ON TABLE public.%I FROM %I', table_name, role_name);
        END IF;
      END LOOP;
    END IF;
  END LOOP;
END;
$career_security$;
COMMIT;
