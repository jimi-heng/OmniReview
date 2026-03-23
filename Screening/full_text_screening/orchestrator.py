import asyncio
import json
from typing import Any, Mapping

import httpx

from .models import FullTextRequest, FullTextScreeningConfig, FullTextScreeningRuntime
from .parsing import StructuredOutputError, extract_output_text, parse_structured_output
from .pdf import load_pdf_bytes, load_text_content, parse_pages_spec
from .pico_normalizer import coerce_pico_payload, normalize_pico_input
from .prompts import build_user_prompt, get_system_prompt, normalize_project_type
from .runtime import (
    build_payload,
    call_with_retry,
    coerce_paper,
    error_result,
    post_with_auth_fallback,
    resolve_runtime_config,
)


async def process_single_paper(
    client: httpx.AsyncClient,
    runtime: FullTextScreeningRuntime,
    request: FullTextRequest,
) -> dict[str, Any]:
    paper = request.paper
    source_path = paper.source_path
    if not source_path.exists():
        return error_result(paper.paper_id, error_type="missing_file", message=f"Input file not found: {source_path}")

    try:
        pdf_bytes = None
        document_text = None
        if paper.is_text:
            document_text = load_text_content(source_path)
        else:
            pdf_bytes = load_pdf_bytes(source_path, runtime.selected_pages)
    except Exception as exc:
        return error_result(paper.paper_id, error_type="input_read_error", message=str(exc))

    try:
        parsed_output: dict[str, Any] | None = None
        raw_text = ""
        for parse_retry in (False, True):
            prompt = get_system_prompt(request.project_type) + "\n\n" + build_user_prompt(request, parse_retry=parse_retry)
            payload = build_payload(
                runtime.model,
                prompt=prompt,
                filename=source_path.name,
                file_bytes=pdf_bytes,
                document_text=document_text,
            )
            response = await call_with_retry(
                post_with_auth_fallback,
                client,
                runtime.endpoint,
                runtime.api_key,
                payload,
                runtime.timeout,
                retries=runtime.retries,
                delay_s=runtime.retry_delay,
            )
            if response.status_code != 200:
                return error_result(
                    paper.paper_id,
                    error_type="http_error",
                    message=f"Upstream returned status {response.status_code}",
                )

            raw_text = extract_output_text(response.json())
            try:
                parsed_output = parse_structured_output(raw_text)
                break
            except StructuredOutputError as exc:
                raw_text = exc.raw_output or raw_text
                if parse_retry:
                    return error_result(
                        paper.paper_id,
                        error_type="parse_error",
                        message=str(exc),
                        raw_output=raw_text,
                    )

        if parsed_output is None:
            return error_result(
                paper.paper_id,
                error_type="parse_error",
                message="Failed to parse structured output",
                raw_output=raw_text,
            )

        decision = str(parsed_output["decision"])
        evidences = dict(parsed_output["evidence"])
        #print(evidences)
        conclusion = str(parsed_output["reason"])

        hl_path_str = None
        if runtime.enable_highlight and paper.is_pdf:
            try:
                try:
                    from Screening.TextHighlight import highlight_pdf
                except ImportError:
                    from TextHighlight import highlight_pdf

                hl_dir = source_path.parent / "highlighted"
                hl_dir.mkdir(exist_ok=True)
                out_pdf = hl_dir / f"HL_{source_path.name}"
                highlight_pdf(source_path, out_pdf, evidences)
                hl_path_str = str(out_pdf)
            except Exception as exc:
                print(f"Highlight error for ID {paper.paper_id}: {exc}")

        evidence_json = json.dumps({"evidences": evidences, "conclusion": conclusion}, ensure_ascii=False)
        return {"id": paper.paper_id, "decision": decision, "evidence": evidence_json, "hl_path": hl_path_str}
    except Exception as exc:
        return error_result(paper.paper_id, error_type="runtime_error", message=str(exc))


async def run_fulltext(
    papers,
    pico_dict,
    project_type,
    config: FullTextScreeningConfig | Mapping[str, Any] | None = None,
):
    runtime = resolve_runtime_config(config, parse_pages_spec=parse_pages_spec)
    normalized_project_type = normalize_project_type(project_type)
    raw_pico = coerce_pico_payload(pico_dict)
    normalized_pico = normalize_pico_input(raw_pico)
    requests = [
        FullTextRequest(
            paper=coerce_paper(paper),
            pico_dict=raw_pico,
            project_type=normalized_project_type,
            normalized_pico=normalized_pico,
        )
        for paper in papers
    ]

    sem = asyncio.Semaphore(runtime.max_concurrency)
    async with httpx.AsyncClient(timeout=runtime.timeout) as client:
        async def bounded_process(request: FullTextRequest):
            async with sem:
                return await process_single_paper(client, runtime, request)

        tasks = [bounded_process(request) for request in requests]
        return await asyncio.gather(*tasks)


def run_fulltext_ai_sync(
    papers,
    pico_dict,
    project_type="PICOS",
    config: FullTextScreeningConfig | Mapping[str, Any] | None = None,
):
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        return loop.run_until_complete(run_fulltext(papers, pico_dict, project_type, config=config))
    finally:
        loop.close()
