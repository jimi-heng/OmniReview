import random
import os
from pathlib import Path
from dotenv import load_dotenv
from urllib3.util.retry import Retry
from requests.adapters import HTTPAdapter
import requests
import defusedxml.ElementTree as ET

SCRIPT_DIR = Path(__file__).resolve().parent
load_dotenv(SCRIPT_DIR / ".env", override=True)
WOS_API_KEY = os.getenv("WOS_API_KEY")


def reconstruct_abstract(inv_index):
    """将 OpenAlex 的 abstract_inverted_index 还原为正常 abstract"""
    if not inv_index:
        return ""

    words = []
    for word, positions in inv_index.items():
        for pos in positions:
            words.append((pos, word))

    words.sort()
    return " ".join(word for _, word in words)


def search_openalex(query, max_number):
    try:
        url = "https://api.openalex.org/works"

        params = {
            "search": query,
            "filter": "has_abstract:true",
            "per-page": max_number
        }

        r = safe_get(url, params=params)
        if not r:
            return []

        if r.status_code != 200:
            print("OpenAlex request failed:", r.status_code)
            return []

        data = r.json()

        results = []

        for p in data.get("results", []):

            abstract = reconstruct_abstract(
                p.get("abstract_inverted_index")
            )
            if not abstract:
                continue

            # authors
            authors = []
            for a in p.get("authorships", []):
                author_info = a.get("author") or {}
                name = author_info.get("display_name")
                if name:
                    authors.append(name)

            author_str = "; ".join(authors)

            # journal（防止 None）
            primary_location = p.get("primary_location") or {}
            source = primary_location.get("source") or {}
            journal = source.get("display_name", "")

            # year
            year = p.get("publication_year") or ""

            # doi
            doi = p.get("doi") or ""
            doi = doi.replace("https://doi.org/", "")

            row = {
                "title": p.get("title") or "",
                "abstract": abstract or "",
                "author": author_str,
                "journal": journal,
                "year": year,
                "doi": doi
            }

            if not has_valid_abstract(row):
                continue

            results.append(row)
        return results

    except Exception as e:
        print(f"OpenAlex search error: {e}")
        return []


def extract_doi(record):
    """从 PubMed record 中提取 DOI"""
    for a in record.get("AID", []):
        if "[doi]" in a:
            return a.replace(" [doi]", "")
    return ""


def create_session():
    session = requests.Session()

    retries = Retry(
        total=3,
        backoff_factor=1,  # 1s, 2s, 4s
        status_forcelist=[500, 502, 503, 504]
    )

    adapter = HTTPAdapter(max_retries=retries)
    session.mount("http://", adapter)
    session.mount("https://", adapter)

    return session

session = create_session()

def safe_get(url, params=None, headers=None):
    try:
        r = session.get(url, params=params, headers=headers, timeout=10)
        r.raise_for_status()
        return r
    except Exception as e:
        print(f"[HTTP ERROR] {url} -> {e}")
        return None

def search_pubmed(query, max_number):
    try:
        # 1. 搜索 PMID
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

        data = r.json()
        pmids = data.get("esearchresult", {}).get("idlist", [])

        if not pmids:
            return []

        # 2. 获取详细信息（XML）
        url_fetch = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi"

        params = {
            "db": "pubmed",
            "id": ",".join(pmids),
            "retmode": "xml"
        }

        r = safe_get(url_fetch, params=params)
        if not r:
            return []

        root = ET.fromstring(r.text)

        results = []

        for article in root.findall(".//PubmedArticle"):

            try:
                title = article.findtext(".//ArticleTitle") or ""
                abstract = " ".join(
                    [a.text or "" for a in article.findall(".//AbstractText")]
                )

                journal = article.findtext(".//Title") or ""

                year = article.findtext(".//PubDate/Year") or ""

                # DOI
                doi = ""
                for id_node in article.findall(".//ArticleId"):
                    if id_node.attrib.get("IdType") == "doi":
                        doi = id_node.text or ""

                # authors
                authors = []
                for a in article.findall(".//Author"):
                    last = a.findtext("LastName") or ""
                    fore = a.findtext("ForeName") or ""
                    name = f"{fore} {last}".strip()
                    if name:
                        authors.append(name)

                row = {
                    "title": title,
                    "abstract": abstract,
                    "author": "; ".join(authors),
                    "journal": journal,
                    "year": year,
                    "doi": doi
                }

                if not has_valid_abstract(row):
                    continue

                results.append(row)

            except Exception as e:
                print("Parse error:", e)
                continue

        return results

    except Exception as e:
        print(f"PubMed search error: {e}")
        return []

def search_wos(query, max_number):
    try:

        url = "https://wos-api.clarivate.com/api/wos"

        params = {
            "databaseId": "WOS",
            "usrQuery": f"TS={query}",
            "count": max_number,
            "firstRecord": 1
        }

        headers = {
            "X-ApiKey": "WOS_API_KEY"
        }

        r = safe_get(url, params=params, headers=headers)
        if not r:
            return []

        if r.status_code != 200:
            print("WOS request failed:", r.status_code)
            return []

        data = r.json()

        results = []

        records = data.get("Data", {}).get("Records", {}).get("records", {}).get("REC", [])

        for p in records:

            title = ""
            abstract = ""
            journal = ""
            year = ""
            doi = ""
            authors = []

            # title
            titles = p.get("static_data", {}).get("summary", {}).get("titles", {}).get("title", [])
            if titles:
                title = titles[0].get("content", "")

            # abstract
            abstract_block = p.get("static_data", {}).get("fullrecord_metadata", {}).get("abstracts", {})
            if "abstract" in abstract_block:
                abstract = abstract_block["abstract"].get("abstract_text", "")

            # authors
            names = p.get("static_data", {}).get("summary", {}).get("names", {}).get("name", [])
            for n in names:
                if "full_name" in n:
                    authors.append(n["full_name"])

            # journal
            source = p.get("static_data", {}).get("summary", {}).get("publishers", {})
            journal = str(source)

            # year
            pub_info = p.get("static_data", {}).get("summary", {}).get("pub_info", {})
            year = pub_info.get("pubyear", "")

            # DOI
            ids = p.get("dynamic_data", {}).get("cluster_related", {}).get("identifiers", {}).get("identifier", [])
            for i in ids:
                if i.get("type") == "doi":
                    doi = i.get("value")

            row = {
                "title": title,
                "abstract": abstract,
                "author": "; ".join(authors),
                "journal": journal,
                "year": year,
                "doi": doi
            }

            if not has_valid_abstract(row):
                continue

            results.append(row)

        return results

    except Exception as e:
        print(f"WOS search error: {e}")
        return []

def has_valid_abstract(paper):
    abstract = paper.get("abstract")

    if abstract is None:
        return False

    abstract = abstract.strip()

    if abstract == "":
        return False

    if abstract.lower() in ["no abstract available", "n/a"]:
        return False

    return True

def literature_search_all(query, N, databases=None):
    # 如果没传，默认全选防报错
    if databases is None:
        databases = ['pubmed', 'openalex', 'wos']

    pubmed_papers = []
    openalex_papers = []
    wos_papers = []

    # 根据前端传来的 databases 数组动态决定调用哪个库
    if 'pubmed' in databases:
        pubmed_papers = search_pubmed(query, 2*N)
        print(f"PubMed returned {len(pubmed_papers)} papers")

    if 'openalex' in databases:
        openalex_papers = search_openalex(query, 2*N)
        print(f"OpenAlex returned {len(openalex_papers)} papers")

    if 'wos' in databases:
        wos_papers = search_wos(query, 2*N)
        print(f"WOS returned {len(wos_papers)} papers")

    all_papers = pubmed_papers + openalex_papers + wos_papers

    unique = {}
    results = []
    duplicate_count = 0

    for p in all_papers:

        doi = (p.get("doi") or "").lower().strip()

        # DOI 统一格式
        doi = doi.replace("https://doi.org/", "")

        if doi:
            key = doi
        else:
            key = p.get("title", "").lower()

        if key not in unique:
            unique[key] = True
            results.append(p)
        else:
            duplicate_count += 1

    # 打乱
    random.shuffle(results)

    # 取前 N
    results = results[:N]
    print(f"Final paper count: {len(results)}")
    print(f"Duplicate papers: {duplicate_count}")
    return results