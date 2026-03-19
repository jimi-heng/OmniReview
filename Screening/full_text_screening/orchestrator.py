import asyncio
import json
from typing import Any, Mapping

import httpx

try:
    from Screening.TextHighlight import highlight_pdf
except ImportError:
    from TextHighlight import highlight_pdf

from .models import FullTextRequest, FullTextScreeningConfig, FullTextScreeningRuntime
from .parsing import extract_conclusion, extract_evidence, extract_flag, extract_output_text
from .pdf import load_pdf_bytes, parse_pages_spec
from .prompts import build_user_prompt, get_system_prompt, normalize_project_type
from .runtime import (
    build_payload,
    call_with_retry,
    coerce_paper,
    error_result,
    normalize_pico_dict,
    post_with_auth_fallback,
    resolve_runtime_config,
)


async def process_single_paper(
    client: httpx.AsyncClient,
    runtime: FullTextScreeningRuntime,
    request: FullTextRequest,
) -> dict[str, Any]:
    paper = request.paper
    pdf_path = paper.pdf_path
    if not pdf_path.exists():
        return error_result(paper.paper_id)

    try:
        prompt = get_system_prompt(request.project_type) + "\n\n" + build_user_prompt(request)
        pdf_bytes = load_pdf_bytes(pdf_path, runtime.selected_pages)
        payload = build_payload(runtime.model, pdf_bytes, pdf_path.name, prompt)
    except Exception:
        return error_result(paper.paper_id)

    try:
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
            return error_result(paper.paper_id)

        text = extract_output_text(response.json())
        flag = extract_flag(text)
        evidences = extract_evidence(text)
        conclusion = extract_conclusion(text)
        decision = "Included" if flag == "1" else "Excluded"

        print(evidences)

        hl_path_str = None
        try:
            hl_dir = pdf_path.parent / "highlighted"
            hl_dir.mkdir(exist_ok=True)
            out_pdf = hl_dir / f"HL_{pdf_path.name}"
            highlight_pdf(pdf_path, out_pdf, evidences)
            hl_path_str = str(out_pdf)
        except Exception as exc:
            print(f"Highlight error for ID {paper.paper_id}: {exc}")

        evidence_json = json.dumps({"evidences": evidences, "conclusion": conclusion}, ensure_ascii=False)
        return {"id": paper.paper_id, "decision": decision, "evidence": evidence_json, "hl_path": hl_path_str}
    except Exception:
        return error_result(paper.paper_id)


async def run_fulltext(
    papers,
    pico_dict,
    project_type,
    config: FullTextScreeningConfig | Mapping[str, Any] | None = None,
):
    runtime = resolve_runtime_config(config, parse_pages_spec=parse_pages_spec)
    normalized_project_type = normalize_project_type(project_type)
    normalized_pico = normalize_pico_dict(pico_dict)
    requests = [
        FullTextRequest(
            paper=coerce_paper(paper),
            pico_dict=normalized_pico,
            project_type=normalized_project_type,
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
