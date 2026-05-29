from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pandas as pd
import pytest
from pydantic import ValidationError

ROOT_DIR = Path(__file__).resolve().parents[2]
SCREENING_DIR = ROOT_DIR / "Screening"
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))
if str(SCREENING_DIR) not in sys.path:
    sys.path.insert(0, str(SCREENING_DIR))

from Screening.abstract_screening import ThreeAgents
from Screening.abstract_screening.literature_search import (
    has_valid_abstract,
    iter_batch_sizes,
    literature_search_all,
    reconstruct_abstract,
    search_openalex,
    search_pubmed,
)
from Screening.AbstractScreening import _run_ai_screening_async


def _paper_df(n: int) -> pd.DataFrame:
    rows = []
    for i in range(1, n + 1):
        rows.append(
            {
                "ID": i,
                "Title": f"T{i}",
                "Abstract_clean": f"A{i}",
                "Abstract": f"A{i}",
                "Flag1": "",
                "Flag2": "",
                "Flag3": "",
                "Reason": "",
            }
        )
    return pd.DataFrame(rows)


class _FakeAgent:
    def __init__(self, judge_list: ThreeAgents.Judge_List | None = None, *, exc: Exception | None = None) -> None:
        self._judge_list = judge_list
        self._exc = exc
        self.calls: list[object] = []

    async def ainvoke(self, payload, **kwargs):
        self.calls.append(payload)
        if self._exc is not None:
            raise self._exc
        assert self._judge_list is not None
        return {"structured_response": self._judge_list}


def _judges(*items: tuple[int, str, str]) -> ThreeAgents.Judge_List:
    # items: (paper_id, flag, reason)
    return ThreeAgents.Judge_List(
        judge_list=[ThreeAgents.Judge_Base(ID=paper_id, Flag=flag, Reason=reason) for paper_id, flag, reason in items]
    )


def _judges_no_reason(*items: tuple[int, str]) -> ThreeAgents.Judge_List:
    # Agent2 doesn't write reasons.
    return ThreeAgents.Judge_List(judge_list=[ThreeAgents.Judge_Base(ID=paper_id, Flag=flag) for paper_id, flag in items])


class CallWithRetryTests(unittest.IsolatedAsyncioTestCase):
    async def test_call_with_retry_returns_result_on_first_success(self) -> None:
        async def ok(x):
            return x

        with (
            patch.object(ThreeAgents, "retries", 2),
            patch.object(ThreeAgents, "timeout", 0.05),
            patch.object(ThreeAgents, "delay", 0),
            patch.object(ThreeAgents.asyncio, "sleep", new=AsyncMock()),
        ):
            self.assertEqual(await ThreeAgents.call_with_retry(ok, 123), 123)

    async def test_call_with_retry_retries_on_timeout(self) -> None:
        calls = 0

        async def sometimes_slow():
            nonlocal calls
            calls += 1
            if calls == 1:
                await ThreeAgents.asyncio.sleep(0.05)
                return "slow"
            return "ok"

        with (
            patch.object(ThreeAgents, "retries", 2),
            patch.object(ThreeAgents, "timeout", 0.01),
            patch.object(ThreeAgents, "delay", 0),
        ):
            got = await ThreeAgents.call_with_retry(sometimes_slow)
        self.assertEqual(got, "ok")
        self.assertEqual(calls, 2)

    async def test_call_with_retry_returns_none_after_exhaustion(self) -> None:
        async def always_slow():
            await ThreeAgents.asyncio.sleep(0.05)
            return "never"

        with (
            patch.object(ThreeAgents, "retries", 2),
            patch.object(ThreeAgents, "timeout", 0.01),
            patch.object(ThreeAgents, "delay", 0),
        ):
            got = await ThreeAgents.call_with_retry(always_slow)
        self.assertIsNone(got)


class VotingWorkflowTests(unittest.IsolatedAsyncioTestCase):
    async def test_voting_both_agents_agree_include(self) -> None:
        df = _paper_df(2)
        agent1 = _FakeAgent(_judges((1, "1", "r1"), (2, "1", "r1")))
        agent2 = _FakeAgent(_judges_no_reason((1, "1"), (2, "1")))
        agent3 = _FakeAgent(exc=AssertionError("agent3 should not be called"))
        agents = [agent1, agent2, agent3]

        with (
            patch.object(ThreeAgents, "batch_size", 20),
            patch.object(ThreeAgents, "delay", 0),
            patch.object(ThreeAgents, "timeout", 0.05),
            patch.object(ThreeAgents, "ChatOpenAI", lambda *a, **k: object()),
            patch.object(ThreeAgents, "create_agent", side_effect=lambda *a, **k: agents.pop(0)),
            patch.object(ThreeAgents.asyncio, "sleep", new=AsyncMock()),
        ):
            out = await ThreeAgents.use_agent_all(df, {"Topic": ""}, "m1", "m2", "m3", "sr", "sn", "{paper_list}", "{paper_list}")

        self.assertEqual(out.loc[out["ID"] == 1, "Flag3"].iloc[0], "1")
        self.assertEqual(out.loc[out["ID"] == 2, "Flag3"].iloc[0], "1")
        self.assertTrue(str(out.loc[out["ID"] == 1, "Reason"].iloc[0]).strip())
        self.assertEqual(agent3.calls, [])

    async def test_voting_both_agents_agree_exclude(self) -> None:
        df = _paper_df(2)
        agent1 = _FakeAgent(_judges((1, "0", "r1"), (2, "0", "r1")))
        agent2 = _FakeAgent(_judges_no_reason((1, "0"), (2, "0")))
        agent3 = _FakeAgent(exc=AssertionError("agent3 should not be called"))
        agents = [agent1, agent2, agent3]

        with (
            patch.object(ThreeAgents, "batch_size", 20),
            patch.object(ThreeAgents, "delay", 0),
            patch.object(ThreeAgents, "timeout", 0.05),
            patch.object(ThreeAgents, "ChatOpenAI", lambda *a, **k: object()),
            patch.object(ThreeAgents, "create_agent", side_effect=lambda *a, **k: agents.pop(0)),
            patch.object(ThreeAgents.asyncio, "sleep", new=AsyncMock()),
        ):
            out = await ThreeAgents.use_agent_all(df, {"Topic": ""}, "m1", "m2", "m3", "sr", "sn", "{paper_list}", "{paper_list}")

        self.assertEqual(out.loc[out["ID"] == 1, "Flag3"].iloc[0], "0")
        self.assertEqual(out.loc[out["ID"] == 2, "Flag3"].iloc[0], "0")
        self.assertEqual(agent3.calls, [])

    async def test_voting_disagreement_agent3_decides_and_only_receives_disagreements(self) -> None:
        df = _paper_df(5)
        agent1 = _FakeAgent(_judges((1, "1", "r"), (2, "1", "r"), (3, "0", "r"), (4, "0", "r"), (5, "1", "r")))
        agent2 = _FakeAgent(_judges_no_reason((1, "1"), (2, "1"), (3, "0"), (4, "1"), (5, "0")))
        agent3 = _FakeAgent(_judges((4, "0", "r3"), (5, "1", "r3")))
        agents = [agent1, agent2, agent3]

        with (
            patch.object(ThreeAgents, "batch_size", 20),
            patch.object(ThreeAgents, "delay", 0),
            patch.object(ThreeAgents, "timeout", 0.05),
            patch.object(ThreeAgents, "ChatOpenAI", lambda *a, **k: object()),
            patch.object(ThreeAgents, "create_agent", side_effect=lambda *a, **k: agents.pop(0)),
            patch.object(ThreeAgents.asyncio, "sleep", new=AsyncMock()),
        ):
            out = await ThreeAgents.use_agent_all(df, {"Topic": ""}, "m1", "m2", "m3", "sr", "sn", "{paper_list}", "{paper_list}")

        # Agreeing rows keep Flag3 = Flag1.
        self.assertEqual(out.loc[out["ID"] == 1, "Flag3"].iloc[0], "1")
        self.assertEqual(out.loc[out["ID"] == 2, "Flag3"].iloc[0], "1")
        self.assertEqual(out.loc[out["ID"] == 3, "Flag3"].iloc[0], "0")
        # Disagreeing rows get model3 decisions.
        self.assertEqual(out.loc[out["ID"] == 4, "Flag3"].iloc[0], "0")
        self.assertEqual(out.loc[out["ID"] == 5, "Flag3"].iloc[0], "1")

        self.assertEqual(len(agent3.calls), 1)
        content = agent3.calls[0]["messages"][0]["content"]
        self.assertIn("'ID': 4", content)
        self.assertIn("'ID': 5", content)
        self.assertNotIn("'ID': 1", content)

    async def test_multiple_batches_write_back_correctly(self) -> None:
        df = _paper_df(25)
        agents: list[_FakeAgent] = []

        def mk_agents(start_id: int, end_id: int) -> list[_FakeAgent]:
            ids = list(range(start_id, end_id + 1))
            a1 = _FakeAgent(_judges(*[(i, "1", "r1") for i in ids]))
            a2 = _FakeAgent(_judges_no_reason(*[(i, "1") for i in ids]))
            a3 = _FakeAgent(exc=AssertionError("agent3 should not be called"))
            return [a1, a2, a3]

        agents.extend(mk_agents(1, 20))
        agents.extend(mk_agents(21, 25))

        with (
            patch.object(ThreeAgents, "batch_size", 20),
            patch.object(ThreeAgents, "delay", 0),
            patch.object(ThreeAgents, "timeout", 0.05),
            patch.object(ThreeAgents, "ChatOpenAI", lambda *a, **k: object()),
            patch.object(ThreeAgents, "create_agent", side_effect=lambda *a, **k: agents.pop(0)),
            patch.object(ThreeAgents.asyncio, "sleep", new=AsyncMock()),
        ):
            out = await ThreeAgents.use_agent_all(df, {"Topic": ""}, "m1", "m2", "m3", "sr", "sn", "{paper_list}", "{paper_list}")

        self.assertEqual(len(out), 25)
        self.assertTrue((out["Flag1"] == "1").all())
        self.assertTrue((out["Flag2"] == "1").all())
        self.assertTrue((out["Flag3"] == "1").all())

    async def test_voting_agent1_failure_leaves_flag1_empty_but_agent3_still_updates(self) -> None:
        df = _paper_df(2)
        agent1 = _FakeAgent(exc=RuntimeError("boom"))
        agent2 = _FakeAgent(_judges_no_reason((1, "1"), (2, "1")))
        agent3 = _FakeAgent(_judges((1, "0", "r3"), (2, "0", "r3")))
        agents = [agent1, agent2, agent3]

        with (
            patch.object(ThreeAgents, "batch_size", 20),
            patch.object(ThreeAgents, "retries", 2),
            patch.object(ThreeAgents, "delay", 0),
            patch.object(ThreeAgents, "timeout", 0.05),
            patch.object(ThreeAgents, "ChatOpenAI", lambda *a, **k: object()),
            patch.object(ThreeAgents, "create_agent", side_effect=lambda *a, **k: agents.pop(0)),
            patch.object(ThreeAgents.asyncio, "sleep", new=AsyncMock()),
        ):
            out = await ThreeAgents.use_agent_all(df, {"Topic": ""}, "m1", "m2", "m3", "sr", "sn", "{paper_list}", "{paper_list}")

        self.assertEqual(out.loc[out["ID"] == 1, "Flag1"].iloc[0], "")
        self.assertEqual(out.loc[out["ID"] == 1, "Flag2"].iloc[0], "1")
        self.assertEqual(out.loc[out["ID"] == 1, "Flag3"].iloc[0], "0")

    async def test_voting_agent3_failure_keeps_other_flags_and_does_not_crash(self) -> None:
        df = _paper_df(2)
        agent1 = _FakeAgent(_judges((1, "1", "r1"), (2, "1", "r1")))
        agent2 = _FakeAgent(_judges_no_reason((1, "0"), (2, "0")))
        agent3 = _FakeAgent(exc=RuntimeError("agent3 down"))
        agents = [agent1, agent2, agent3]

        with (
            patch.object(ThreeAgents, "batch_size", 20),
            patch.object(ThreeAgents, "retries", 2),
            patch.object(ThreeAgents, "delay", 0),
            patch.object(ThreeAgents, "timeout", 0.05),
            patch.object(ThreeAgents, "ChatOpenAI", lambda *a, **k: object()),
            patch.object(ThreeAgents, "create_agent", side_effect=lambda *a, **k: agents.pop(0)),
            patch.object(ThreeAgents.asyncio, "sleep", new=AsyncMock()),
        ):
            out = await ThreeAgents.use_agent_all(df, {"Topic": ""}, "m1", "m2", "m3", "sr", "sn", "{paper_list}", "{paper_list}")

        self.assertEqual(out.loc[out["ID"] == 1, "Flag1"].iloc[0], "1")
        self.assertEqual(out.loc[out["ID"] == 1, "Flag2"].iloc[0], "0")
        self.assertEqual(out.loc[out["ID"] == 1, "Flag3"].iloc[0], "")


class AbstractScreeningAPITests(unittest.IsolatedAsyncioTestCase):
    async def test_run_ai_screening_async_end_to_end(self) -> None:
        papers = [{"id": 1, "title": "T", "abstract": "A"}]

        updated = pd.DataFrame(
            [
                {
                    "ID": 1,
                    "Title": "T",
                    "Abstract_clean": "A",
                    "Abstract": "A",
                    "Flag1": "1",
                    "Flag2": "1",
                    "Flag3": "1",
                    "Reason": "Because.",
                }
            ]
        )

        with patch.object(ThreeAgents, "use_agent_all", new=AsyncMock(return_value=updated)):
            out = await _run_ai_screening_async({"p": "Adults"}, papers, project_type="SPICO")

        self.assertEqual(out, [{"id": 1, "ai_decision": "Included", "reasoning": "Because."}])

    async def test_run_ai_screening_async_exception_returns_pending(self) -> None:
        papers = [{"id": 1, "title": "T", "abstract": "A"}]

        with patch.object(ThreeAgents, "use_agent_all", new=AsyncMock(side_effect=RuntimeError("nope"))):
            out = await _run_ai_screening_async({"p": "Adults"}, papers, project_type="SPICO")

        self.assertEqual(out[0]["ai_decision"], "Pending")
        self.assertIn("AI Screening Error:", out[0]["reasoning"])

    async def test_run_ai_screening_async_empty_papers(self) -> None:
        out = await _run_ai_screening_async({"p": "Adults"}, [], project_type="SPICO")
        self.assertEqual(out, [])

    async def test_run_ai_screening_async_missing_reason_gets_default(self) -> None:
        papers = [{"id": 1, "title": "T", "abstract": "A"}]
        updated = pd.DataFrame(
            [
                {
                    "ID": 1,
                    "Title": "T",
                    "Abstract_clean": "A",
                    "Abstract": "A",
                    "Flag1": "1",
                    "Flag2": "1",
                    "Flag3": "1",
                    "Reason": "",
                }
            ]
        )
        with patch.object(ThreeAgents, "use_agent_all", new=AsyncMock(return_value=updated)):
            out = await _run_ai_screening_async({"p": "Adults"}, papers, project_type="SPICO")
        self.assertTrue(out[0]["reasoning"])


class LiteratureSearchHelperTests(unittest.TestCase):
    def test_iter_batch_sizes_caps_requests_at_100(self) -> None:
        self.assertEqual(list(iter_batch_sizes(0)), [])
        self.assertEqual(list(iter_batch_sizes(50)), [50])
        self.assertEqual(list(iter_batch_sizes(250)), [100, 100, 50])

    def test_reconstruct_abstract_ordered(self) -> None:
        self.assertEqual(reconstruct_abstract({"hello": [0], "world": [1]}), "hello world")

    def test_reconstruct_abstract_empty(self) -> None:
        self.assertEqual(reconstruct_abstract(None), "")
        self.assertEqual(reconstruct_abstract({}), "")

    def test_has_valid_abstract_rejects_placeholders(self) -> None:
        self.assertFalse(has_valid_abstract({"abstract": ""}))
        self.assertFalse(has_valid_abstract({"abstract": None}))
        self.assertFalse(has_valid_abstract({"abstract": "no abstract available"}))
        self.assertFalse(has_valid_abstract({"abstract": "n/a"}))
        self.assertTrue(has_valid_abstract({"abstract": "Real abstract."}))

    def test_literature_search_all_dedup_and_limit(self) -> None:
        pubmed = [{"doi": "10.1234/X", "title": "A", "abstract": "a"} for _ in range(5)]
        openalex = [{"doi": "https://doi.org/10.1234/x", "title": "A-dup", "abstract": "b"}] + [
            {"doi": f"10.9999/{i}", "title": f"T{i}", "abstract": "c"} for i in range(4)
        ]

        with (
            patch("Screening.abstract_screening.literature_search.search_pubmed", return_value=pubmed),
            patch("Screening.abstract_screening.literature_search.search_openalex", return_value=openalex),
            patch("Screening.abstract_screening.literature_search.search_wos", return_value=[]),
            patch("Screening.abstract_screening.literature_search.random.shuffle", lambda x: None),
        ):
            out = literature_search_all("q", 5, databases=["pubmed", "openalex"])

        self.assertEqual(len(out), 5)
        dois = [p.get("doi") for p in out]
        normalized = [str(d or "").lower().replace("https://doi.org/", "").strip() for d in dois]
        self.assertEqual(len(set(normalized)), len(normalized))

    def test_literature_search_all_still_requests_two_n_candidates(self) -> None:
        with (
            patch("Screening.abstract_screening.literature_search.search_pubmed", return_value=[]) as pubmed,
            patch("Screening.abstract_screening.literature_search.search_openalex", return_value=[]) as openalex,
            patch("Screening.abstract_screening.literature_search.search_wos", return_value=[]) as wos,
        ):
            literature_search_all("q", 200, databases=["pubmed", "openalex", "wos"])

        pubmed.assert_called_once_with("q", 400)
        openalex.assert_called_once_with("q", 400)
        wos.assert_called_once_with("q", 400)

    def test_openalex_search_splits_large_requests_into_pages(self) -> None:
        calls = []

        class Response:
            status_code = 200

            def __init__(self, count):
                self._count = count

            def json(self):
                return {
                    "results": [
                        {
                            "title": f"T{i}",
                            "abstract_inverted_index": {"abstract": [0]},
                            "authorships": [],
                            "primary_location": {},
                            "publication_year": 2024,
                            "doi": f"10.1/{i}",
                        }
                        for i in range(self._count)
                    ]
                }

        def fake_safe_get(url, params=None, headers=None):
            calls.append(params)
            return Response(params["per-page"])

        with patch("Screening.abstract_screening.literature_search.safe_get", side_effect=fake_safe_get):
            out = search_openalex("q", 250)

        self.assertEqual(len(out), 250)
        self.assertEqual([c["per-page"] for c in calls], [100, 100, 50])
        self.assertEqual([c["page"] for c in calls], [1, 2, 3])

    def test_pubmed_search_splits_large_requests_into_retstart_pages(self) -> None:
        calls = []

        class SearchResponse:
            status_code = 200

            def __init__(self, pmids):
                self._pmids = pmids

            def json(self):
                return {"esearchresult": {"idlist": self._pmids}}

        class FetchResponse:
            status_code = 200
            text = "<PubmedArticleSet />"

        def fake_safe_get(url, params=None, headers=None):
            calls.append((url, params))
            if "esearch.fcgi" in url:
                retstart = params["retstart"]
                retmax = params["retmax"]
                return SearchResponse([str(i) for i in range(retstart, retstart + retmax)])
            return FetchResponse()

        with patch("Screening.abstract_screening.literature_search.safe_get", side_effect=fake_safe_get):
            out = search_pubmed("q", 250)

        self.assertEqual(out, [])
        search_params = [params for url, params in calls if "esearch.fcgi" in url]
        self.assertEqual([p["retmax"] for p in search_params], [100, 100, 50])
        self.assertEqual([p["retstart"] for p in search_params], [0, 100, 200])

    def test_one_source_raises_others_still_returned(self) -> None:
        with (
            patch("Screening.abstract_screening.literature_search.search_pubmed", side_effect=RuntimeError("down")),
            patch(
                "Screening.abstract_screening.literature_search.search_openalex",
                return_value=[{"doi": "10.1/a", "title": "T", "abstract": "A"}],
            ),
            patch("Screening.abstract_screening.literature_search.search_wos", return_value=[]),
            patch("Screening.abstract_screening.literature_search.random.shuffle", lambda x: None),
        ):
            out = literature_search_all("q", 5, databases=["pubmed", "openalex"])
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0]["doi"], "10.1/a")


class PydanticAndCollectResponseTests(unittest.TestCase):
    def test_judge_base_rejects_invalid_flag(self) -> None:
        with self.assertRaises(ValidationError):
            ThreeAgents.Judge_Base(ID=1, Flag="2")

    def test_collect_response_ignores_unknown_ids(self) -> None:
        df = _paper_df(1)
        ThreeAgents.CollectAIResponse(df, [{"ID": 999, "Flag": "1", "Reason": "x"}], 1)
        self.assertEqual(df.loc[df["ID"] == 1, "Flag1"].iloc[0], "")


if __name__ == "__main__":
    unittest.main()
