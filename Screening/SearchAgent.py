from Bio import Entrez
from Bio import Medline
import pandas as pd
import os
from dotenv import load_dotenv
from openai import OpenAI
from langchain.chat_models import init_chat_model
from langchain_core.prompts import PromptTemplate
from langchain_core.output_parsers import JsonOutputParser
load_dotenv(override=True)

class PubMedBiopythonDownloader:
    def __init__(self, email: str):
        Entrez.email = email
    
    def search_to_csv(self, query: str, save_dir: str, max_results: int = 100):
        #Search
        handle = Entrez.esearch(db="pubmed", term=query, retmax=max_results)
        record = Entrez.read(handle)
        handle.close()
        
        pmids = record["IdList"]
        print(f"找到 {len(pmids)} 篇文献")
        
        if not pmids:
            return
        
        handle = Entrez.efetch(db="pubmed", id=pmids, rettype="medline", retmode="text")
        records = list(Medline.parse(handle))
        handle.close()
        
        #Transform
        data = []
        for record in records:
            row = {
                'PMID': record.get('PMID', ''),
                'Title': record.get('TI', ''),
                'Abstract': record.get('AB', ''),
                'Authors': '; '.join(record.get('AU', [])),
                'Journal': record.get('JT', ''),
                'Publication_Date': record.get('DP', ''),
                'DOI': record.get('LID', record.get('AID', '')),
                'Keywords': '; '.join(record.get('OT', record.get('MH', []))),
                'Flag': '',
                'Reason': ''
            }
            data.append(row)
        
        df = pd.DataFrame(data)
        filename = os.path.join(save_dir, f"CSVList.csv")
        df=use_agent(df, query)
        df.to_csv(filename, index=False, encoding='utf-8-sig')
        print(f"保存到: {filename}")
        
        return df

#Judge by agent
def use_agent(csv_list, query):
    model = init_chat_model(model="deepseek-chat", model_provider="deepseek")

    parser = JsonOutputParser()

    prompt = PromptTemplate.from_template(
        "你需要评估以下文献是否适合用于撰写关于'{query}'的学术论文。\n\n"
        "文献信息：\n{csv_list}\n\n"
        "请对每篇文献进行评估,并以JSON格式输出结果:\n"
        "```json\n"
        "{{\n"
        "  \"evaluations\": [\n"
        "    {{\n"
        "      \"pmid\": \"文献PMID\",\n"
        "      \"flag\": \"True或False\",\n"
        "      \"reason\": \"50字左右的判断理由\"\n"
        "    }},\n"
        "    ...\n"
        "  ]\n"
        "}}\n"
        "```\n"
        "要求：\n"
        "1. flag只能是'True'或'False'\n"
        "2. reason50字左右\n"
        "3. 包含所有文献的评估结果\n"
        "4. 确保输出是有效的JSON格式"
    )

    chain = prompt | model | parser
    response = chain.invoke({"query":query,
                             "csv_list": csv_list})
    
    return CollectAIResponse(csv_list, response)

#transform the AIResponse
def CollectAIResponse(csv_list, response):
    evals = response["evaluations"]
    for e in evals:
        pmid = str(e.get("pmid", "")).strip()
        flag = str(e.get("flag", "")).strip()
        reason = str(e.get("reason", "")).strip()
        mask = csv_list["PMID"] == pmid
        if mask.any():
            csv_list.loc[mask, "Flag"] = flag
            csv_list.loc[mask, "Reason"] = reason

    return csv_list

if __name__ == "__main__":
    query = input("enter key words: ").strip()
    max_number = input("enter number: ").strip()
    save_dir = input("enter address: ").strip()

    DeepSeek_API_KEY=os.getenv("DEEPSEEK_API_KEY")
    client = OpenAI(api_key=DeepSeek_API_KEY, base_url="https://api.deepseek.com")

    downloader = PubMedBiopythonDownloader("erzhuzi2023@outlook.com")
    csv_list=downloader.search_to_csv(
        query=query,
        save_dir=save_dir,
        max_results=max_number,
    )

