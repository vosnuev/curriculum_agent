"""
FastAPI 백엔드 서버
실행: uv run uvicorn api:app --reload --port 8000
"""
import hashlib
from typing import Optional
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from rag import AdvancedRAG

app = FastAPI(title="2026 고등학교 교육과정 RAG API", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],   # Replit 프론트엔드 허용
    allow_methods=["*"],
    allow_headers=["*"],
)

# RAG 인스턴스 (서버 시작 시 1회 초기화)
rag = AdvancedRAG()

# 검색 결과 임시 캐시 (analyze → answer 사이에 docs 재사용)
_doc_cache: dict[str, list] = {}


# ── 요청 모델 ────────────────────────────────────────────────────────────

class QueryRequest(BaseModel):
    query: str
    grade: str                  # "1,2" 또는 "3"
    history: list[dict] = []    # [{"role":"user","content":"..."}, ...]

class AnswerRequest(BaseModel):
    query: str
    grade: str
    topic_title: str            # 선택된 주제명 (직접 답변 시 query와 동일)
    cache_key: str              # /api/query 응답으로 받은 캐시 키
    history: list[dict] = []


# ── 엔드포인트 ───────────────────────────────────────────────────────────

@app.get("/health")
def health():
    return {"status": "ok"}


@app.post("/api/query")
def analyze_query(req: QueryRequest):
    """
    질문을 분석해 직접 답변할지(action=answer) 보기를 줄지(action=choose) 결정.
    docs는 캐시에 저장하고 cache_key를 반환.
    """
    if not req.query.strip():
        raise HTTPException(status_code=400, detail="query가 비어있습니다.")
    if req.grade not in ("1,2", "3"):
        raise HTTPException(status_code=400, detail="grade는 '1,2' 또는 '3'이어야 합니다.")

    try:
        result = rag.analyze_query(req.query.strip(), req.grade)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

    cache_key = hashlib.md5(f"{req.grade}:{req.query}".encode()).hexdigest()
    _doc_cache[cache_key] = result["docs"]

    return {
        "action": result["action"],                 # "answer" | "choose"
        "topics": result.get("topics", []),         # choose일 때만 내용 있음
        "cache_key": cache_key,
    }


@app.post("/api/answer")
def get_answer(req: AnswerRequest):
    """
    선택된 주제(또는 쿼리)로 Rerank 후 구조화된 마크다운 답변 반환.
    """
    if not req.query.strip():
        raise HTTPException(status_code=400, detail="query가 비어있습니다.")

    docs = _doc_cache.get(req.cache_key)
    if not docs:
        # 캐시 만료 시 재검색
        try:
            fallback = rag.analyze_query(req.query.strip(), req.grade)
            docs = fallback["docs"]
        except Exception as e:
            raise HTTPException(status_code=500, detail=str(e))

    try:
        answer = rag.get_answer(
            req.query.strip(),
            req.grade,
            req.topic_title,
            docs,
            req.history,
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

    return {"answer": answer}
