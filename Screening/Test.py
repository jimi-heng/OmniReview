import requests

def reconstruct_abstract(inv_index):
    if not inv_index:
        return ""

    words = []
    for word, positions in inv_index.items():
        for pos in positions:
            words.append((pos, word))

    words.sort()
    return " ".join(word for _, word in words)


def search_openalex(query, limit=20):

    url = "https://api.openalex.org/works"

    params = {
        "search": query,
        "per-page": limit
    }

    r = requests.get(url, params=params)
    data = r.json()

    papers = []

    for p in data["results"]:

        abstract = reconstruct_abstract(
            p.get("abstract_inverted_index")
        )

        papers.append({
            "Title": p.get("title"),
            "Abstract": abstract,
            "DOI": p.get("doi"),
            "Publication_Date": p.get("publication_year")
        })

    return papers

if __name__ == '__main__':
    papers = search_openalex("honey wound")
    print(papers)
