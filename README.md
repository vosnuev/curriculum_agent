# Curriculum RAG Agent (교육과정 RAG Q&A 에이전트)

> Two-stage RAG agent that answers questions about Seoul high school curriculum documents with PDF page citations.
> (서울특별시교육청 고등학교 교육과정 문서를 기반으로 PDF 페이지 출처를 명시하며 답변하는 2단계 RAG 에이전트)

---

## Tech Stack (기술 스택)

![Python](https://img.shields.io/badge/Python-3.11+-3776AB?logo=python&logoColor=white)
![FastAPI](https://img.shields.io/badge/FastAPI-0.115+-009688?logo=fastapi&logoColor=white)
![LangChain](https://img.shields.io/badge/LangChain-0.3+-1C3C3C?logo=langchain&logoColor=white)
![OpenAI](https://img.shields.io/badge/OpenAI_GPT--4o-412991?logo=openai&logoColor=white)
![Pinecone](https://img.shields.io/badge/Pinecone-Vector_DB-00A67E)
![Cohere](https://img.shields.io/badge/Cohere-Rerank-D97706)
![uv](https://img.shields.io/badge/uv-package_manager-DE5FE9)

| Layer | Technology |
|-------|-----------|
| LLM | OpenAI GPT-4o |
| Embedding | OpenAI text-embedding-3-small |
| Vector DB | Pinecone (Serverless, cosine, dim=1536) |
| Reranker | Cohere rerank-multilingual-v3.0 |
| Framework | LangChain (langchain, langchain-openai, langchain-pinecone, langchain-cohere) |
| Backend API | FastAPI + Uvicorn |
| Frontend | HTML/CSS/JS (Replit deployment) |
| Package Manager | [uv](https://docs.astral.sh/uv/) |

---

## Features (주요 기능)

### 1. Smart Routing — Direct Answer vs. Topic Selection (스마트 라우팅)
After retrieval, the LLM classifies the question before generating an answer.

- **Direct answer (`action: answer`)**: Query contains a specific school type, subject name, or numeric value, or the answer is concentrated in 1–2 PDF locations.
- **Topic selection (`action: choose`)**: Query spans multiple categories (e.g., school types, subject areas) — the agent presents 3 distinct topic choices + "Other."

```
# Direct answer example
Query: "일반고등학교 총 이수학점은?"
→ "일반 고등학교의 총 이수학점은 192학점입니다. (pg. 22)"

# Topic selection example
Query: "이수학점"
→ 어떤 내용이 궁금하신가요?
  1) 일반고
  2) 특목고
  3) 자율·특성화고
  4) 기타 — 질문을 다시 입력하기
```

### 2. Structured Answer with PDF Page Citations (구조화된 답변 + 출처 명시)
Every answer follows a fixed markdown structure. Page references appear inline as `| pg.X`.

```markdown
## 핵심 답변
네, 공통과목을 대체할 수 있는 과목이 있습니다.

## 대체 가능 과목 | pg.4
| 원래 공통과목 | 대체 과목 |
|---|---|
| 공통수학1 | 기본수학1 |
| 공통수학2 | 기본수학2 |

## ⚠️ 주의사항
1. **선택적 대체**: 대체과목은 필수가 아닙니다.
2. **동시 이수 불가**: 기본수학1과 공통수학1은 동시 이수할 수 없습니다.
```

### 3. Grade-based Metadata Filtering (학년별 메타데이터 필터링)
Documents are indexed with a `grade` metadata field. Pinecone filters at query time so Grade 1–2 queries never pull Grade 3 content.

```python
{"grade": "1,2"}  # 1·2학년 문서
{"grade": "3"}    # 3학년 문서
```

### 4. Multi-Query Expansion (Multi-Query 질문 확장)
Short or ambiguous queries (e.g., "창체") are automatically expanded by the LLM into multiple paraphrased queries to improve recall.

### 5. Cohere Rerank (재랭크)
All retrieved documents are re-ranked against the selected topic query. Only the top 3 are passed to the LLM — reducing token usage and improving answer quality.

### 6. Conversation History (대화 기록 유지)
Grade is selected once per session. The last 6 turns are maintained and passed to the LLM, enabling natural follow-up questions until the user types `quit`.

---

## Project Structure (프로젝트 구조)

```
curriculum_agent/
├── data/
│   ├── 2026학년도 고등학교 1,2학년 교육과정 편성·운영 방향.pdf
│   └── 2026학년도 고등학교 3학년 교육과정 편성·운영 방향.pdf
├── frontend/
│   └── index.html          # Web frontend (Replit deployment)
├── rag.py                  # Core RAG pipeline (AdvancedRAG class + CLI loop)
├── api.py                  # FastAPI backend server
├── pyproject.toml          # uv project config & dependencies
├── uv.lock                 # Locked dependency manifest
└── .env                    # Environment variables (not committed)
```

---

## Usage Flow (사용 흐름)

```
User input
    │
    ▼
[Grade selection]  Once per session — Grade 1·2 or Grade 3
    │
    ▼
[Multi-Query expansion]  LLM generates N paraphrased queries
    │
    ▼
[Pinecone vector search]  k=15, filtered by grade metadata
    │
    ▼
[LLM query analysis] ─────────────────────────────────────
    │                                                      │
    ▼ Broad/ambiguous query                  Specific query│
[Present 3 topic choices + Other]                         │
    │ User selects topic                                   │
    ▼                                                      │
[Cohere Rerank]  Re-rank all docs by selected topic → Top 3 ←─┘
    │
    ▼
[LLM answer generation]  Structured markdown + (pg. X) citations
    │
    ▼
Structured answer output
  ├─ 핵심 답변 (Core answer)
  ├─ Detail sections with tables + page citations
  └─ ⚠️ 주의사항 (Warnings, if applicable)
    │
    ▼
Conversation history maintained → await next question (until quit)
```

---

## Architecture (아키텍처)

```
┌─────────────────────────────────────────────────────────────┐
│  Frontend (Replit — frontend/index.html)                    │
│  HTML/CSS/JS  ←──── REST API (JSON) ────→  FastAPI (api.py) │
└──────────────────────────────┬──────────────────────────────┘
                               │
                    ┌──────────▼──────────┐
                    │   AdvancedRAG (rag.py)             │
                    │                                    │
                    │  POST /api/query                   │
                    │   └─ analyze_query()               │
                    │       ├─ MultiQueryRetriever       │
                    │       │   └─ Pinecone (k=15)       │
                    │       └─ LLM routing decision      │
                    │                                    │
                    │  POST /api/answer                  │
                    │   └─ get_answer()                  │
                    │       ├─ CohereRerank (top 3)      │
                    │       └─ LLM answer generation     │
                    └────────────────────────────────────┘
                               │
               ┌───────────────┼───────────────┐
               ▼               ▼               ▼
          Pinecone         OpenAI           Cohere
       (Vector Store)   (GPT-4o +        (Reranker)
                      text-embedding-3-small)
```

**API Endpoints:**

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/health` | Health check |
| `POST` | `/api/query` | Analyze query → return `action` + `topics` + `cache_key` |
| `POST` | `/api/answer` | Rerank + generate structured answer |

---

## Environment Setup (환경 설정)

### Prerequisites (사전 요구사항)

- Python 3.11+
- [uv](https://docs.astral.sh/uv/) package manager

```bash
# Install uv (macOS/Linux)
curl -LsSf https://astral.sh/uv/install.sh | sh

# Install uv (Windows PowerShell)
powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
```

### Install Project (프로젝트 설치)

```bash
git clone https://github.com/vosnuev/curriculum_agent.git
cd curriculum_agent
uv sync
```

### Environment Variables (환경 변수)

Create a `.env` file in the project root:

```env
OPENAI_API_KEY=sk-...
PINECONE_API_KEY=...
PINECONE_INDEX_NAME=school-curriculum
COHERE_API_KEY=...
```

| Variable | Description |
|----------|-------------|
| `OPENAI_API_KEY` | OpenAI API key (GPT-4o + text-embedding-3-small) |
| `PINECONE_API_KEY` | Pinecone API key |
| `PINECONE_INDEX_NAME` | Pinecone index name (default: `school-curriculum`) |
| `COHERE_API_KEY` | Cohere API key (for rerank-multilingual-v3.0) |

---

## How to Run (실행 방법)

### 1. Index Documents — First Run Only (문서 인덱싱 — 최초 1회)

Uncomment `ingest_documents` in the `__main__` block of `rag.py`, then run:

```bash
uv run python rag.py
```

Re-comment after indexing is complete.

### 2. CLI Q&A

```bash
uv run python rag.py
```

```
=======================================================
  2026 고등학교 교육과정 Q&A 시스템
  (종료: 'quit' 입력)
=======================================================

학년을 선택하세요:
  1) 1,2학년
  2) 3학년
선택 (1/2): 1

질문: 일반고 총 이수학점은?

분석 중...

[직접 답변]
=======================================================
## 핵심 답변
일반 고등학교의 총 이수학점은 192학점입니다.

## 이수학점 구성 | pg.22
| 구분 | 학점 |
|---|---|
| 교과 | 174학점 |
| 창의적 체험활동 | 18학점 |
| 합계 | 192학점 |
=======================================================
```

### 3. FastAPI Backend (웹 UI용 백엔드 실행)

```bash
uv run uvicorn api:app --reload --port 8000
```

Set `API_BASE` in `frontend/index.html` to the backend URL.

For external access, use [ngrok](https://ngrok.com):

```bash
ngrok http 8000
# Copy the https://xxxx.ngrok-free.app URL into index.html API_BASE
```

---

## License & References (라이선스 & 참고 문서)

**License:** MIT

**Source Documents (출처 문서):**
- 서울특별시교육청, *2026학년도 고등학교 1·2학년 교육과정 편성·운영 방향* (2025)
- 서울특별시교육청, *2026학년도 고등학교 3학년 교육과정 편성·운영 방향* (2025)

> The PDF documents in `data/` are official publications of the Seoul Metropolitan Office of Education (서울특별시교육청). All curriculum information is sourced directly from these documents.
