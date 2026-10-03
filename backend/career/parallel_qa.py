"""Independent QA network calls; DB reads and trace writes stay on the request thread."""

from concurrent.futures import ThreadPoolExecutor
from contextvars import copy_context

from career.models import PromptRun
from career.providers import configured_provider
from career.runtime_trace import emit_trace, input_hash, trace_context, trace_sink


def run(service, calls):
    from career.references import compile_pack

    provider = service.provider or configured_provider()
    prepared = []
    for stage, context, schema in calls:
        pack = compile_pack(service.db, service.user, stage, context.get("document_domain", ""))
        prepared.append(
            (
                stage,
                {**context, "supplemental_guidance": pack},
                schema,
                {
                    **trace_context.get(),
                    "workspace_id": service.current_workspace,
                    "input_artifact_ids": sorted(service.input_artifact_ids),
                    "input_hash_only": True,
                    "prompt_version": "v2-supplement" if pack["references"] else "v1",
                    "reference_pack": pack["pack"],
                    "reference_versions": [
                        {key: ref[key] for key in ("key", "version", "content_hash")}
                        for ref in pack["references"]
                    ],
                },
            )
        )

    def execute(item):
        stage, context, schema, metadata = item
        traces = []
        sink = trace_sink.set(lambda key, name, data: traces.append((key, name, data)))
        token = trace_context.set(metadata)
        try:
            value = provider.structured(stage, context, schema).model_dump()
            if not getattr(provider, "trace_emitting", False):
                emit_trace(
                    stage,
                    type(provider).__name__,
                    {
                        **getattr(provider, "last_trace", {}),
                        "status": "COMPLETED",
                        "input_hash": input_hash(context),
                    },
                )
            return value, traces, None
        except Exception as error:
            if not getattr(provider, "trace_emitting", False):
                emit_trace(
                    stage,
                    type(provider).__name__,
                    {
                        "status": "FAILED",
                        "input_hash": input_hash(context),
                        "error_code": "PROVIDER_UNAVAILABLE",
                    },
                )
            return None, traces, error
        finally:
            trace_context.reset(token)
            trace_sink.reset(sink)

    with ThreadPoolExecutor(max_workers=2, thread_name_prefix="career-qa") as pool:
        # Each worker gets its own Context, sharing the one immutable deadline
        # and thread-safe usage envelope. No worker owns a database connection.
        futures = [pool.submit(copy_context().run, execute, item) for item in prepared]
        results = [future.result() for future in futures]
    for _, traces, _ in results:
        for stage, name, metadata in traces:
            if trace_sink.get() is None:
                service.db.add(PromptRun(user_id=service.user, stage=stage, provider=name, data=metadata))
            else:
                emit_trace(stage, name, metadata)
            if metadata.get("model") and metadata.get("status") == "COMPLETED":
                service.current_model = metadata["model"]
    for _, _, error in results:
        if error:
            raise error
    return [value for value, _, _ in results]
