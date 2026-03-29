import random
import os
from pathlib import Path
from dotenv import load_dotenv
from urllib3.util.retry import Retry
from requests.adapters import HTTPAdapter
import requests
import defusedxml.ElementTree as ET

__all__ = ["literature_search_all"]


SCRIPT_DIR = Path(__file__).resolve().parent
load_dotenv(SCRIPT_DIR / ".env", override=True)
WOS_API_KEY = os.getenv("WOS_API_KEY")


def reconstruct_abstract(inv_index):
    """
    Reconstruct plain-text abstract from OpenAlex inverted index.

    Args:
        inv_index (dict): Mapping of word → list of positions.

    Returns:
        str: Reconstructed abstract text.
    """
    if not inv_index:
        return ""

    words = []
    for word, positions in inv_index.items():
        for pos in positions:
            words.append((pos, word))

    words.sort()
    return " ".join(word for _, word in words)


def search_openalex(query, max_number):
    """
    Search OpenAlex for papers with abstracts.

    Args:
        query (str): Search query.
        max_number (int): Maximum number of results.

    Returns:
        list[dict]: List of paper metadata.
    """
    try:
        url = "https://api.openalex.org/works"

        params = {
            "search": query,
            "filter": "has_abstract:true",
            "per-page": max_number
        }

        r = safe_get(url, params=params)
        if not r or r.status_code != 200:
            return []

        data = r.json()
        results = []

        for p in data.get("results", []):

            abstract = reconstruct_abstract(p.get("abstract_inverted_index"))
            if not abstract:
                continue

            authors = [
                a.get("author", {}).get("display_name")
                for a in p.get("authorships", [])
                if a.get("author", {}).get("display_name")
            ]

            primary_location = p.get("primary_location") or {}
            source = primary_location.get("source") or {}

            row = {
                "title": p.get("title") or "",
                "abstract": abstract,
                "author": "; ".join(authors),
                "journal": source.get("display_name", ""),
                "year": p.get("publication_year") or "",
                "doi": (p.get("doi") or "").replace("https://doi.org/", "")
            }

            if has_valid_abstract(row):
                results.append(row)

        return results

    except Exception:
        return []


def extract_doi(record):
    """
    Extract DOI from PubMed record.

    Args:
        record (dict): PubMed record.

    Returns:
        str: DOI string if found, otherwise empty string.
    """
    for a in record.get("AID", []):
        if "[doi]" in a:
            return a.replace(" [doi]", "")
    return ""


def create_session():
    """
    Create a requests session with retry strategy.

    Returns:
        requests.Session: Configured session object.
    """
    session = requests.Session()

    retries = Retry(
        total=3,
        backoff_factor=1,
        status_forcelist=[500, 502, 503, 504]
    )

    adapter = HTTPAdapter(max_retries=retries)
    session.mount("http://", adapter)
    session.mount("https://", adapter)

    return session


session = create_session()


def safe_get(url, params=None, headers=None):
    """
    Perform HTTP GET with error handling.

    Args:
        url (str): Request URL.
        params (dict, optional): Query parameters.
        headers (dict, optional): HTTP headers.

    Returns:
        requests.Response | None: Response object or None if failed.
    """
    try:
        r = session.get(url, params=params, headers=headers, timeout=10)
        r.raise_for_status()
        return r
    except Exception:
        return None


def search_pubmed(query, max_number):
    """
    Search PubMed and return structured paper data.

    Args:
        query (str): Search query.
        max_number (int): Maximum number of results.

    Returns:
        list[dict]: List of paper metadata.
    """
    try:
        url_search = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi"

        params = {
            "db": "pubmed",
            "term": query,
            "retmax": max_number,
            "retmode": "json"
        }

        r = safe_get(url_search, params=params)
        if not r:
            return []

        pmids = r.json().get("esearchresult", {}).get("idlist", [])
        if not pmids:
            return []

        url_fetch = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi"

        r = safe_get(url_fetch, params={
            "db": "pubmed",
            "id": ",".join(pmids),
            "retmode": "xml"
        })
        if not r:
            return []

        root = ET.fromstring(r.text)
        results = []

        for article in root.findall(".//PubmedArticle"):
            try:
                authors = []
                for a in article.findall(".//Author"):
                    name = f"{a.findtext('ForeName') or ''} {a.findtext('LastName') or ''}".strip()
                    if name:
                        authors.append(name)

                row = {
                    "title": article.findtext(".//ArticleTitle") or "",
                    "abstract": " ".join([a.text or "" for a in article.findall(".//AbstractText")]),
                    "author": "; ".join(authors),
                    "journal": article.findtext(".//Title") or "",
                    "year": article.findtext(".//PubDate/Year") or "",
                    "doi": next(
                        (i.text for i in article.findall(".//ArticleId")
                         if i.attrib.get("IdType") == "doi"),
                        ""
                    )
                }

                if has_valid_abstract(row):
                    results.append(row)

            except Exception:
                continue

        return results

    except Exception:
        return []


def search_wos(query, max_number):
    """
    Search Web of Science (WOS) API.

    Args:
        query (str): Search query.
        max_number (int): Maximum number of results.

    Returns:
        list[dict]: List of paper metadata.
    """
    try:
        url = "https://wos-api.clarivate.com/api/wos"

        r = safe_get(url, params={
            "databaseId": "WOS",
            "usrQuery": f"TS={query}",
            "count": max_number,
            "firstRecord": 1
        }, headers={"X-ApiKey": WOS_API_KEY})

        if not r or r.status_code != 200:
            return []

        records = r.json().get("Data", {}).get("Records", {}).get("records", {}).get("REC", [])
        results = []

        for p in records:
            authors = [
                n["full_name"]
                for n in p.get("static_data", {}).get("summary", {}).get("names", {}).get("name", [])
                if "full_name" in n
            ]

            ids = p.get("dynamic_data", {}).get("cluster_related", {}).get("identifiers", {}).get("identifier", [])
            doi = next((i.get("value") for i in ids if i.get("type") == "doi"), "")

            row = {
                "title": (p.get("static_data", {}).get("summary", {}).get("titles", {}).get("title", [{}])[0].get("content", "")),
                "abstract": p.get("static_data", {}).get("fullrecord_metadata", {}).get("abstracts", {}).get("abstract", {}).get("abstract_text", ""),
                "author": "; ".join(authors),
                "journal": str(p.get("static_data", {}).get("summary", {}).get("publishers", {})),
                "year": p.get("static_data", {}).get("summary", {}).get("pub_info", {}).get("pubyear", ""),
                "doi": doi
            }

            if has_valid_abstract(row):
                results.append(row)

        return results

    except Exception:
        return []


def has_valid_abstract(paper):
    """
    Check whether a paper has a valid abstract.

    Args:
        paper (dict): Paper metadata.

    Returns:
        bool: True if abstract is valid.
    """
    abstract = (paper.get("abstract") or "").strip().lower()
    return abstract not in ["", "no abstract available", "n/a"]


def literature_search_all(query, N, databases=None):
    """
    Aggregate search results from multiple literature databases.

    Args:
        query (str): Search query.
        N (int): Number of final results to return.
        databases (list[str], optional): Selected databases.

    Returns:
        list[dict]: Deduplicated and shuffled paper list.
    """
    if databases is None:
        databases = ['pubmed', 'openalex', 'wos']

    results = []

    if 'pubmed' in databases:
        results += search_pubmed(query, 2 * N)

    if 'openalex' in databases:
        results += search_openalex(query, 2 * N)

    if 'wos' in databases:
        results += search_wos(query, 2 * N)

    unique = {}
    deduped = []

    for p in results:
        doi = (p.get("doi") or "").lower().replace("https://doi.org/", "")
        key = doi if doi else p.get("title", "").lower()

        if key not in unique:
            unique[key] = True
            deduped.append(p)

    random.shuffle(deduped)
    return deduped[:N]