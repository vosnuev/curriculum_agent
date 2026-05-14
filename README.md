# 📚 Curriculum RAG Agent

> 2026학년도 고등학교 교육과정 편성·운영 방향 PDF를 기반으로 한 학년별 맞춤형 RAG Q&A 에이전트

---

## 📌 프로젝트 개요

학생, 교사, 학부모가 고등학교 교육과정에 대해 궁금한 점을 자연어로 질문하면, 학년별 공식 문서에서 정확한 정보를 찾아 답변하는 RAG(Retrieval-Augmented Generation) 에이전트입니다.

**지원 문서**

- `2026학년도 고등학교 1·2학년 교육과정 편성·운영 방향.pdf`
- `2026학년도 고등학교 3학년 교육과정 편성·운영 방향.pdf`

---

## 🏗️ 아키텍처

```
사용자 입력
    │
    ▼
[학년 선택] ──────────────────────────────────────────────
    │  (1·2학년 / 3학년)                                   │
    ▼                                                       ▼
[메타데이터 필터링]                              학년별 시스템 프롬프트 주입
    │  Pinecone namespace 분리
    ▼
[Multi-Query 확장]
    │  사용자 질문 → 다각도 유사 질문 N개 생성
    ▼
[Hybrid Retrieval]
    │  Pinecone 벡터 검색 + 키워드 검색 결합
    ▼
[Contextual Compression]
    │  질문 맥락과 무관한 청크 제거
    ▼
[Cohere Rerank]
    │  Top-K 문서 → 정답 관련도 기준 재순위화
    ▼
[LLM 답변 생성]
    │  GPT-4.1 / gpt-4.1-mini
    ▼
최종 답변 출력
```

---

## ✨ 주요 기능

### 1. 학년별 문서 분리 인덱싱 (Metadata Filtering)
PDF 로드 시 `grade` 메타데이터를 부여해 Pinecone에 인덱싱합니다. 1·2학년 질문 시 3학년 문서가 혼입되는 오답을 원천 차단합니다.

```python
# 예시
{"grade": "1-2"}  # 1·2학년 문서
{"grade": "3"}    # 3학년 문서
```

### 2. Multi-Query 질문 확장
사용자가 "창체"처럼 짧게 입력해도 LLM이 자동으로 "창의적 체험활동", "창체 배당 시간", "창체 운영 방식" 등 유사 질문을 생성해 검색 범위를 넓힙니다.

### 3. Hybrid Retrieval (벡터 + 키워드)
Pinecone의 벡터 유사도 검색과 BM25 기반 키워드 검색을 결합하여 의미적 유사성과 정확한 키워드 매칭을 동시에 활용합니다.

### 4. Contextual Compression
검색된 문서 청크에서 질문과 관련 없는 내용을 LLM이 직접 필터링·압축하여 노이즈를 제거합니다.

### 5. Cohere Rerank
검색된 상위 10개 문서 조각 중 질문과 가장 관련성 높은 상위 3개만 추려 LLM에 전달합니다. 토큰 절약과 답변 품질 향상을 동시에 달성합니다.

---

## 🛠️ 기술 스택

| 구분 | 기술 |
|------|------|
| LLM | OpenAI GPT-4.1 / gpt-4.1-mini |
| Embedding | OpenAI text-embedding-3-small |
| Vector DB | Pinecone |
| Reranker | Cohere Rerank |
| Framework | LangChain |
| 환경 관리 | [uv](https://docs.astral.sh/uv/) |

---

## ⚙️ 환경 설정

### 사전 요구사항

- Python 3.11+
- [uv](https://docs.astral.sh/uv/) 설치

```bash
# uv 설치 (macOS/Linux)
curl -LsSf https://astral.sh/uv/install.sh | sh

# uv 설치 (Windows PowerShell)
powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
```

### 프로젝트 설치

```bash
# 저장소 클론
git clone https://github.com/vosnuev/curriculum_agent.git
cd curriculum_agent

# 가상환경 생성 및 의존성 설치 (uv가 자동으로 .venv 생성)
uv sync
```

### 환경 변수 설정

`.env` 파일을 프로젝트 루트에 생성하고 아래 값을 입력합니다.

```env
# OpenAI
OPENAI_API_KEY=sk-...

# Pinecone
PINECONE_API_KEY=...
PINECONE_INDEX_NAME=curriculum-agent

# Cohere
COHERE_API_KEY=...

# 모델 설정 (선택, 기본값 사용 가능)
OPENAI_TEXT_MODEL=gpt-4.1-mini
OPENAI_EMBEDDING_MODEL=text-embedding-3-small
RETRIEVER_K=3
```

---

## 🚀 실행 방법

### 1. 문서 인덱싱 (최초 1회)

PDF를 청크로 분할하여 Pinecone에 업로드합니다.

```bash
uv run python rag.py --ingest
```

### 2. 에이전트 실행

```bash
uv run python app.py
```

실행 후 터미널에서 학년을 선택하고 질문을 입력합니다.

```
학년을 선택하세요:
  1. 1·2학년
  2. 3학년
> 1

질문을 입력하세요 (종료: q):
> 창체 시간 배당은 어떻게 되나요?

[답변]
창의적 체험활동(창체)의 시간 배당은 ...
```

---

## 📁 프로젝트 구조

```
curriculum_agent/
├── data/
│   ├── 2026학년도 고등학교 1·2학년 교육과정 편성·운영 방향.pdf
│   └── 2026학년도 고등학교 3학년 교육과정 편성·운영 방향.pdf
├── app.py              # 메인 실행 파일 (학년 선택 + 대화 루프)
├── rag.py              # RAG 파이프라인 (인덱싱 + 검색 + 생성)
├── pyproject.toml      # uv 프로젝트 설정 및 의존성
├── .python-version     # Python 버전 고정
├── .env                # 환경 변수 (git 제외)
└── .gitignore
```

---

## 🔑 핵심 구현 포인트

| 포인트 | 설명 |
|--------|------|
| **메타데이터 필터링** | 인덱싱 시 학년 정보를 메타데이터로 저장 → 검색 시 해당 학년 문서만 조회 |
| **Multi-Query** | 짧고 모호한 질문도 LLM이 다양한 형태로 확장 → 召回率 향상 |
| **Cohere Rerank** | Top-10 → Top-3 압축으로 LLM 입력 토큰 절약 및 정답률 향상 |
| **Contextual Compression** | 문서 청크를 질문 맥락에 맞게 압축 → 불필요한 정보 제거 |

---

## 📝 라이선스

MIT License
