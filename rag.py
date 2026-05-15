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

    # ── Step 1: 넓게 검색 → 핵심 주제 3개 도출 ─────────────────────────

    def suggest_topics(self, query: str, selected_grade: str):
        """MultiQuery로 폭넓게 검색하고 LLM이 관련성 높은 핵심 주제 3개를 제안한다."""
        base_retriever = self.vectorstore.as_retriever(
            search_kwargs={"filter": {"grade": selected_grade}, "k": 15}
        )
        mq_retriever = MultiQueryRetriever.from_llm(
            retriever=base_retriever, llm=self.llm
        )
        docs = mq_retriever.invoke(query)

        docs_summary = "\n\n".join(
            f"[문서 {i+1}] (pg.{doc.metadata.get('page', 0)+1})\n{doc.page_content[:250]}"
            for i, doc in enumerate(docs[:12])
        )

        prompt = f"""사용자 질문: "{query}"

검색된 관련 문서들:
{docs_summary}

위 문서들을 분석하여 사용자 질문과 가장 관련성 높은 핵심 주제 3개를 도출하세요.
각 주제 title은 10자 이내로 짧고 명확하게 작성하세요.

반드시 아래 JSON 형식으로만 응답하세요 (다른 텍스트 없이):
{{"topics":[{{"id":1,"title":"짧은 주제명"}},{{"id":2,"title":"짧은 주제명"}},{{"id":3,"title":"짧은 주제명"}}]}}"""

        response = self.llm.invoke(prompt)
        data = self._parse_json(response.content)
        return data["topics"], docs

    # ── Step 2: 선택된 주제로 재랭크 → (pg. X) 출처 포함 답변 ───────────

    def get_detailed_answer(
        self,
        query: str,
        selected_grade: str,
        selected_topic: dict,
        all_docs: list,
        conversation_history: list,
    ):
        """선택된 주제로 CohereRerank 재랭크 후 (pg. X) 형식으로 출처를 명시하며 답변한다."""
        topic_query = f"{selected_topic['title']} {query}"

        compressor = CohereRerank(
            cohere_api_key=self.cohere_api_key,
            model="rerank-multilingual-v3.0",
            top_n=3,
        )
        ranked_docs = compressor.compress_documents(all_docs, topic_query)
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
선택된 주제: {topic}
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
        return chain.invoke(
            {
                "grade": selected_grade,
                "topic": selected_topic["title"],
                "history": history_text,
                "context": context,
                "question": query,
            }
        )

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


def run_topic_selection(rag: AdvancedRAG, query: str, grade: str):
    """주제 선택 루프. (selected_topic, final_query, docs) 또는 None 반환."""
    current_query = query
    while True:
        print("\n관련 주제 분석 중...")
        try:
            topics, docs = rag.suggest_topics(current_query, grade)
        except Exception as e:
            print(f"오류: {e}")
            return None

        print("\n어떤 내용이 궁금하신가요?")
        for t in topics:
            print(f"  {t['id']}) {t['title']}")
        print("  4) 기타 — 질문을 다시 입력하기")

        choice = input("\n선택 (1/2/3/4): ").strip()

        if choice == "4":
            current_query = input("더 구체적인 질문을 입력하세요: ").strip()
            if not current_query:
                return None
            continue  # 새 질문으로 주제 재분석

        if choice in ("1", "2", "3"):
            idx = int(choice) - 1
            if idx < len(topics):
                return topics[idx], current_query, docs

        print("1, 2, 3, 또는 4를 입력하세요.")


def run_interactive(rag: AdvancedRAG):
    print("=" * 55)
    print("  2026 고등학교 교육과정 Q&A 시스템")
    print("  (종료: 'quit' 입력)")
    print("=" * 55)

    # 학년은 세션 시작 시 한 번만 선택
    grade = select_grade()
    conversation_history: list[dict] = []

    print("\n질문을 입력하세요. 언제든 'quit'을 입력하면 종료됩니다.")

    while True:
        print()
        query = input("질문: ").strip()

        if query.lower() in ("quit", "exit", "종료", "q"):
            break
        if not query:
            continue

        result = run_topic_selection(rag, query, grade)
        if result is None:
            continue

        selected_topic, final_query, docs = result

        print(f"\n'{selected_topic['title']}' 답변 생성 중...")
        try:
            response = rag.get_detailed_answer(
                final_query, grade, selected_topic, docs, conversation_history
            )
            print("\n" + "=" * 55)
            print(response.content)
            print("=" * 55)

            # 대화 기록 업데이트 (follow-up 맥락 유지)
            conversation_history.append({"role": "user", "content": final_query})
            conversation_history.append({"role": "assistant", "content": response.content})

        except Exception as e:
            print(f"오류: {e}")

        # 추가 안내 없이 바로 다음 질문 대기

    print("\n시스템을 종료합니다.")


if __name__ == "__main__":
    rag = AdvancedRAG()

    # ── 최초 1회만 인덱싱 시 아래 주석 해제 후 실행 ──
    # base_dir = os.path.dirname(os.path.abspath(__file__))
    # files = [
    #     os.path.join(base_dir, "data", "2026학년도 고등학교 1,2학년 교육과정 편성·운영 방향.pdf"),
    #     os.path.join(base_dir, "data", "2026학년도 고등학교 3학년 교육과정 편성·운영 방향.pdf"),
    # ]
    # rag.ingest_documents(files)

    run_interactive(rag)
