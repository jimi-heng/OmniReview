# Before Started

- Create a ".env" file under the same folder of AbstractScreening.py. In the file, copy paste these code

```python
DMX_API_KEY_1=sk-qUyWwUB5y3wiprWPKjQYw73MkBU8K0pLSi4pGQ8bVv06IfLt
```

```python
DMX_API_KEY_2=sk-ujAXlwqFIYyGCpqqB9zjjlAtoEyfI5iQ9cJL5mIHVP2MdpH4
```

- Please download uv. Run this code in terminal

```python
pip install uv
```

- Use the code below and it will download packages automatically

```python
uv run projectName.py
```

- Here is the langchain's reference: https://docs.langchain.com/oss/python/releases/langchain-v1


# Install requirement

## Test for grpfh

1) 安装开发依赖
uv sync --group dev

2) 跑 grpfh 的单元/集成测试（不含 E2E）
uv run pytest grpfh/tests --ignore=grpfh/tests/e2e -v

3) 安装 Playwright 浏览器（首次需要）
uv run playwright install chromium

4) 跑前端 E2E
uv run pytest grpfh/tests/e2e -v

5) 覆盖率（不含 E2E）
uv run pytest grpfh/tests --ignore=grpfh/tests/e2e --cov=grpfh --cov-report=term-missing --cov-report=html
