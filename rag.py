import os
import sys
import json
import re
from dotenv import load_dotenv

if sys.stdout.encoding != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")

from pinecone import Pinecone, ServerlessSpec
from langchain_openai import OpenAIEmbeddings, ChatOpenAI
from langchain_community.document_loaders import PyPDFLoader
from langchain_text_splitters import RecursiveCharacterTextSplitter
from langchain_pinecone import PineconeVectorStore
from langchain_classic.retrievers.multi_query import MultiQueryRetriever
from langchain_cohere import CohereRerank
from langchain_core.prompts import ChatPromptTemplate

load_dotenv()


class AdvancedRAG:
    def __init__(self, index_name="school-curriculum"):
        self.pinecone_api_key = os.getenv("PINECONE_API_KEY")
        self.openai_api_key = os.getenv("OPENAI_API_KEY")
        self.cohere_api_key = os.getenv("COHERE_API_KEY")

        self.pc = Pinecone(api_key=self.pinecone_api_key)
        self.index_name = index_name
        self.embeddings = OpenAIEmbeddings(model="text-embedding-3-small")
        self.llm = ChatOpenAI(model_name="gpt-4o", temperature=0)

        existing_indexes = [idx.name for idx in self.pc.list_indexes()]
        if self.index_name not in existing_indexes:
            self.pc.create_index(
                name=self.index_name,
                dimension=1536,
                metric="cosine",
                spec=ServerlessSpec(cloud="aws", region="us-east-1"),
            )

        self.vectorstore = PineconeVectorStore(
            index_name=self.index_name,
            embedding=self.embeddings,
            pinecone_api_key=self.pinecone_api_key,
        )

    def ingest_documents(self, file_paths):
        all_splits = []
        for file_path in file_paths:
            grade = "3" if "3학년" in file_path else "1,2"
            loader = PyPDFLoader(file_path)
            docs = loader.load()
            splitter = RecursiveCharacterTextSplitter(
                chunk_size=800,
                chunk_overlap=100,
                separators=["\n\n", "\n", ".", " ", ""],
            )
            splits = splitter.split_documents(docs)
            for split in splits:
                split.metadata["grade"] = grade
            all_splits.extend(splits)

        self.vectorstore = PineconeVectorStore.from_documents(
            all_splits,
            self.embeddings,
            index_name=self.index_name,
            pinecone_api_key=self.pinecone_api_key,
        )

    # ── Step 1: 검색 + 질문 분석 → 직접 답변 or 보기 제시 결정 ──────────

    def analyze_query(self, query: str, selected_grade: str) -> dict:
        """
        MultiQuery로 검색 후 LLM이 질문의 구체성을 판단한다.

        반환값:
          {"action": "answer", "docs": [...]}
          {"action": "choose", "topics": [...], "docs": [...]}

        action == "answer": 질문이 충분히 구체적 → 보기 없이 바로 답변
        action == "choose": 질문이 포괄적 → 서로 다른 범주의 보기 3개 제시
        """
        base_retriever = self.vectorstore.as_retriever(
            search_kwargs={"filter": {"grade": selected_grade}, "k": 15}
        )
        mq_retriever = MultiQueryRetriever.from_llm(
            retriever=base_retriever, llm=self.llm
        )
        docs = mq_retriever.invoke(query)

        docs_summary = "\n\n".join(
            f"[문서 {i+1}] (pg.{doc.metadata.get('page', 0)+1})\n{doc.page_content[:300]}"
            for i, doc in enumerate(docs[:12])
        )

        prompt = f"""사용자 질문: "{query}"

검색된 관련 문서:
{docs_summary}

[판단 기준]
다음 중 하나를 선택하세요.

(A) 직접 답변 — action: "answer"
  - 질문에 특정 학교유형, 과목명, 구체적 수치 등 명확한 키워드가 있는 경우
  - 질문의 답이 PDF 내 1~2곳에 집중되어 있는 경우
  - 단순 사실 확인형 질문 (예: "일반고 총 이수학점은?", "창체 시간 배당은?")
  - 주제가 하나여서 보기로 쪼개면 오히려 중복되는 경우

(B) 보기 제시 — action: "choose"
  - 질문이 포괄적이어서 여러 다른 범주에 걸쳐 있는 경우
    예) 학교 유형별로 답이 다를 때 (일반고/특목고/자율고/특성화고)
    예) 과목 영역별로 내용이 달라질 때
    예) 질문 자체가 너무 짧고 모호한 경우
  - 각 보기는 반드시 서로 다른 범주/카테고리여야 함
  - 비슷한 표현이나 같은 개념을 다른 말로 쓴 보기는 절대 금지

반드시 아래 JSON 형식으로만 응답하세요 (다른 텍스트 없이):

직접 답변일 때:
{{"action":"answer"}}

보기 제시일 때 (보기는 서로 완전히 다른 범주):
{{"action":"choose","topics":[{{"id":1,"title":"10자이내 범주명"}},{{"id":2,"title":"10자이내 범주명"}},{{"id":3,"title":"10자이내 범주명"}}]}}"""

        response = self.llm.invoke(prompt)
        data = self._parse_json(response.content)
        data["docs"] = docs
        return data

    # ── Step 2: Rerank → (pg. X) 출처 포함 답변 ─────────────────────────

    def get_answer(
        self,
        query: str,
        selected_grade: str,
        topic_title: str,          # 직접 답변 시 query 그대로, 보기 선택 시 선택된 주제명
        all_docs: list,
        conversation_history: list,
    ) -> str:
        """CohereRerank 재랭크 후 (pg. X) 형식으로 출처를 명시하며 답변한다."""
        rerank_query = f"{topic_title} {query}" if topic_title != query else query

        compressor = CohereRerank(
            cohere_api_key=self.cohere_api_key,
            model="rerank-multilingual-v3.0",
            top_n=3,
        )
        ranked_docs = compressor.compress_documents(all_docs, rerank_query)
        if not ranked_docs:
            ranked_docs = all_docs[:3]

        context = "\n\n".join(
            f"[pg.{doc.metadata.get('page', 0)+1}]\n{doc.page_content}"
            for doc in ranked_docs
        )

        # 최근 대화 내역 (최대 6턴)
        history_text = ""
        if conversation_history:
            history_text = "\n[이전 대화]\n"
            for turn in conversation_history[-6:]:
                role = "사용자" if turn["role"] == "user" else "답변"
                history_text += f"{role}: {turn['content']}\n"
            history_text += "\n"

        template = """당신은 고등학교 교육과정 편성 및 운영 지침 전문 상담원입니다.
선택된 학년: {grade}학년
{history}
아래 참고 문서를 바탕으로 질문에 구체적이고 명확하게 답변하세요.
각 내용마다 출처를 "(pg. X)에 따르면" 또는 문장 끝에 "(pg. X)" 형식으로 반드시 명시하세요.
이전 대화 맥락이 있다면 자연스럽게 이어서 답변하세요.
문서에 없는 내용은 추측하지 마세요.

참고 문서:
{context}

질문: {question}

답변:"""

        chain = ChatPromptTemplate.from_template(template) | self.llm
        result = chain.invoke(
            {
                "grade": selected_grade,
                "history": history_text,
                "context": context,
                "question": query,
            }
        )
        return result.content

    # ── 유틸 ────────────────────────────────────────────────────────────

    def _parse_json(self, text: str) -> dict:
        text = re.sub(r"```(?:json)?\n?", "", text).strip("`").strip()
        match = re.search(r"\{.*\}", text, re.DOTALL)
        return json.loads(match.group() if match else text)


# ── CLI 인터랙티브 루프 ────────────────────────────────────────────────

def select_grade() -> str:
    while True:
        print("\n학년을 선택하세요:")
        print("  1) 1,2학년")
        print("  2) 3학년")
        c = input("선택 (1/2): ").strip()
        if c == "1":
            return "1,2"
        if c == "2":
            return "3"
        print("1 또는 2를 입력하세요.")


def handle_query(rag: AdvancedRAG, query: str, grade: str, conversation_history: list):
    """
    질문 하나를 처리한다.
    - 구체적 질문 → 바로 답변
    - 포괄적 질문 → 보기(최대 3 + 기타) 제시 후 답변
    반환: 최종 답변 문자열 또는 None (사용자가 취소한 경우)
    """
    current_query = query

    while True:
        print("\n분석 중...")
        try:
            result = rag.analyze_query(current_query, grade)
        except Exception as e:
            print(f"오류: {e}")
            return None

        docs = result["docs"]

        # ── 구체적 질문: 바로 답변 ──────────────────────────────────────
        if result["action"] == "answer":
            print("\n답변 생성 중...")
            try:
                answer = rag.get_answer(current_query, grade, current_query, docs, conversation_history)
                print("\n" + "=" * 55)
                print(answer)
                print("=" * 55)
                return answer
            except Exception as e:
                print(f"오류: {e}")
                return None

        # ── 포괄적 질문: 보기 제시 ──────────────────────────────────────
        topics = result.get("topics", [])
        if not topics:
            # topics가 비어있으면 직접 답변으로 폴백
            print("\n답변 생성 중...")
            try:
                answer = rag.get_answer(current_query, grade, current_query, docs, conversation_history)
                print("\n" + "=" * 55)
                print(answer)
                print("=" * 55)
                return answer
            except Exception as e:
                print(f"오류: {e}")
                re