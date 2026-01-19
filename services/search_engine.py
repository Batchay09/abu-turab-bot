"""
Advanced hybrid search engine using rubert-tiny-turbo, FAISS, and BM25.
Features:
1. Separate indexes for questions and answers (Multi-vector retrieval)
2. Weighted embedding combination
3. Enhanced BM25 with separate question/answer search
"""

import json
import os
import re
from typing import Optional
import numpy as np
import faiss
from sentence_transformers import SentenceTransformer
from rank_bm25 import BM25Okapi

from config import config
from services.synonyms import expand_query


class SearchEngine:
    """
    Advanced hybrid search engine with multi-vector retrieval.

    Features:
    - Separate FAISS indexes for questions and answers
    - Weighted combination of question/answer embeddings
    - BM25 keyword search on both questions and answers
    - Reciprocal Rank Fusion for combining results
    """

    MODEL_NAME = "sergeyzh/rubert-tiny-turbo"
    EMBEDDING_DIM = 312  # rubert-tiny-turbo output dimension

    # Index file paths
    QUESTION_INDEX_PATH = "data/faiss_questions.index"
    ANSWER_INDEX_PATH = "data/faiss_answers.index"
    COMBINED_INDEX_PATH = "data/faiss_combined.index"

    def __init__(self):
        self.model: Optional[SentenceTransformer] = None

        # Multi-vector indexes
        self.question_index: Optional[faiss.IndexFlatIP] = None
        self.answer_index: Optional[faiss.IndexFlatIP] = None
        self.combined_index: Optional[faiss.IndexFlatIP] = None  # Weighted combination

        # Legacy single index for backward compatibility
        self.index: Optional[faiss.IndexFlatIP] = None

        # BM25 indexes
        self.bm25_questions: Optional[BM25Okapi] = None
        self.bm25_answers: Optional[BM25Okapi] = None
        self.bm25: Optional[BM25Okapi] = None  # Combined, for backward compatibility

        self.tokenized_corpus: list[list[str]] = []
        self.documents: list[dict] = []
        self._initialized = False

        # Configurable weights
        self.question_weight = 0.6  # Weight for questions in combined embedding
        self.answer_weight = 0.4    # Weight for answers in combined embedding

    @staticmethod
    def _tokenize(text: str) -> list[str]:
        """Simple tokenization for Russian text"""
        text = text.lower()
        text = re.sub(r'[^\w\s]', ' ', text)
        tokens = text.split()
        return [t for t in tokens if len(t) > 1]

    async def initialize(self):
        """Initialize the search engine - load model and indexes"""
        if self._initialized:
            return

        print(f"Loading model {self.MODEL_NAME}...")
        self.model = SentenceTransformer(self.MODEL_NAME)

        # Check for new multi-index format first
        if self._has_multi_index():
            print("Loading multi-vector indexes...")
            self._load_multi_index()
        # Fallback to legacy single index
        elif os.path.exists(config.FAISS_INDEX_PATH) and os.path.exists(config.DOCUMENTS_PATH):
            print("Loading legacy index and upgrading...")
            self._load_legacy_index()
            # Upgrade to multi-index format
            self._build_multi_index()
        else:
            print("Creating new empty indexes...")
            self._create_empty_indexes()

        # Build BM25 indexes
        self._build_bm25_indexes()

        self._initialized = True
        print(f"Search engine initialized. Documents in index: {len(self.documents)}")

    def _has_multi_index(self) -> bool:
        """Check if multi-index files exist"""
        return (
            os.path.exists(os.path.join(config.DATA_DIR, "faiss_questions.index")) and
            os.path.exists(os.path.join(config.DATA_DIR, "faiss_answers.index")) and
            os.path.exists(os.path.join(config.DATA_DIR, "faiss_combined.index")) and
            os.path.exists(config.DOCUMENTS_PATH)
        )

    def _create_empty_indexes(self):
        """Create empty indexes"""
        self.question_index = faiss.IndexFlatIP(self.EMBEDDING_DIM)
        self.answer_index = faiss.IndexFlatIP(self.EMBEDDING_DIM)
        self.combined_index = faiss.IndexFlatIP(self.EMBEDDING_DIM)
        self.index = self.combined_index  # Backward compatibility
        self.documents = []

    def _load_legacy_index(self):
        """Load legacy single FAISS index and documents"""
        self.index = faiss.read_index(config.FAISS_INDEX_PATH)
        self.combined_index = self.index
        with open(config.DOCUMENTS_PATH, "r", encoding="utf-8") as f:
            self.documents = json.load(f)

    def _load_multi_index(self):
        """Load all multi-vector indexes"""
        data_dir = config.DATA_DIR
        self.question_index = faiss.read_index(os.path.join(data_dir, "faiss_questions.index"))
        self.answer_index = faiss.read_index(os.path.join(data_dir, "faiss_answers.index"))
        self.combined_index = faiss.read_index(os.path.join(data_dir, "faiss_combined.index"))
        self.index = self.combined_index  # Backward compatibility

        with open(config.DOCUMENTS_PATH, "r", encoding="utf-8") as f:
            self.documents = json.load(f)

    def _build_multi_index(self):
        """Build multi-vector indexes from documents"""
        if not self.documents:
            self._create_empty_indexes()
            return

        print("Building multi-vector indexes...")

        # Create fresh indexes
        self.question_index = faiss.IndexFlatIP(self.EMBEDDING_DIM)
        self.answer_index = faiss.IndexFlatIP(self.EMBEDDING_DIM)
        self.combined_index = faiss.IndexFlatIP(self.EMBEDDING_DIM)

        # Prepare texts
        questions = [doc['question_text'] for doc in self.documents]
        answers = [doc['answer_text'] for doc in self.documents]

        # Generate embeddings
        print("Encoding questions...")
        question_embeddings = self._encode(questions)

        print("Encoding answers...")
        answer_embeddings = self._encode(answers)

        print("Creating weighted combined embeddings...")
        combined_embeddings = self._create_weighted_embeddings(
            question_embeddings,
            answer_embeddings
        )

        # Add to indexes
        self.question_index.add(question_embeddings)
        self.answer_index.add(answer_embeddings)
        self.combined_index.add(combined_embeddings)
        self.index = self.combined_index

        # Save all indexes
        self._save_all_indexes()
        print(f"Multi-vector indexes built with {len(self.documents)} documents")

    def _create_weighted_embeddings(
        self,
        question_emb: np.ndarray,
        answer_emb: np.ndarray
    ) -> np.ndarray:
        """
        Create weighted combination of question and answer embeddings.
        This prevents long answers from "drowning" short questions.
        """
        # Weighted average
        combined = (
            self.question_weight * question_emb +
            self.answer_weight * answer_emb
        )

        # Re-normalize for cosine similarity
        norms = np.linalg.norm(combined, axis=1, keepdims=True)
        norms = np.where(norms == 0, 1, norms)  # Avoid division by zero
        combined = combined / norms

        return combined.astype("float32")

    def _build_bm25_indexes(self):
        """Build separate BM25 indexes for questions and answers"""
        if not self.documents:
            self.bm25_questions = None
            self.bm25_answers = None
            self.bm25 = None
            self.tokenized_corpus = []
            return

        print("Building BM25 indexes...")

        # Tokenize questions
        tokenized_questions = []
        for doc in self.documents:
            tokens = self._tokenize(doc['question_text'])
            tokenized_questions.append(tokens)

        # Tokenize answers
        tokenized_answers = []
        for doc in self.documents:
            tokens = self._tokenize(doc['answer_text'])
            tokenized_answers.append(tokens)

        # Combined tokenization (for backward compatibility)
        self.tokenized_corpus = []
        for doc in self.documents:
            combined = f"{doc['question_text']} {doc['answer_text']}"
            tokens = self._tokenize(combined)
            self.tokenized_corpus.append(tokens)

        # Build BM25 indexes
        self.bm25_questions = BM25Okapi(tokenized_questions)
        self.bm25_answers = BM25Okapi(tokenized_answers)
        self.bm25 = BM25Okapi(self.tokenized_corpus)

        print(f"BM25 indexes built with {len(self.documents)} documents")

    def _save_all_indexes(self):
        """Save all FAISS indexes and documents to disk"""
        os.makedirs(config.DATA_DIR, exist_ok=True)

        # Save multi-vector indexes
        faiss.write_index(
            self.question_index,
            os.path.join(config.DATA_DIR, "faiss_questions.index")
        )
        faiss.write_index(
            self.answer_index,
            os.path.join(config.DATA_DIR, "faiss_answers.index")
        )
        faiss.write_index(
            self.combined_index,
            os.path.join(config.DATA_DIR, "faiss_combined.index")
        )

        # Also save as legacy format for backward compatibility
        faiss.write_index(self.combined_index, config.FAISS_INDEX_PATH)

        # Save documents
        with open(config.DOCUMENTS_PATH, "w", encoding="utf-8") as f:
            json.dump(self.documents, f, ensure_ascii=False, indent=2)

    def _save_index(self):
        """Save index (backward compatible method)"""
        self._save_all_indexes()

    def _encode(self, texts: list[str]) -> np.ndarray:
        """Encode texts to embeddings"""
        embeddings = self.model.encode(
            texts,
            normalize_embeddings=True,
            convert_to_numpy=True
        )
        return embeddings.astype("float32")

    def add_document(self, doc: dict) -> int:
        """
        Add a document to all indexes.

        Args:
            doc: Document with keys: post_id, post_number, question_text, answer_text, message_id

        Returns:
            Index position of the added document
        """
        if not self._initialized:
            raise RuntimeError("Search engine not initialized. Call initialize() first.")

        question_text = doc['question_text']
        answer_text = doc['answer_text']

        # Generate separate embeddings
        question_emb = self._encode([question_text])
        answer_emb = self._encode([answer_text])
        combined_emb = self._create_weighted_embeddings(question_emb, answer_emb)

        # Add to all FAISS indexes
        self.question_index.add(question_emb)
        self.answer_index.add(answer_emb)
        self.combined_index.add(combined_emb)

        # Store document metadata
        self.documents.append({
            "post_id": doc.get("post_id"),
            "post_number": doc.get("post_number"),
            "question_text": question_text,
            "answer_text": answer_text,
            "message_id": doc.get("message_id"),
        })

        # Rebuild BM25 indexes (necessary for BM25)
        self._build_bm25_indexes()

        # Save to disk
        self._save_all_indexes()

        return len(self.documents) - 1

    def add_documents_batch(self, docs: list[dict]):
        """Add multiple documents to all indexes in batch."""
        if not self._initialized:
            raise RuntimeError("Search engine not initialized. Call initialize() first.")

        if not docs:
            return

        # Prepare texts
        questions = [d['question_text'] for d in docs]
        answers = [d['answer_text'] for d in docs]

        # Generate embeddings in batch
        question_embeddings = self._encode(questions)
        answer_embeddings = self._encode(answers)
        combined_embeddings = self._create_weighted_embeddings(
            question_embeddings,
            answer_embeddings
        )

        # Add to all FAISS indexes
        self.question_index.add(question_embeddings)
        self.answer_index.add(answer_embeddings)
        self.combined_index.add(combined_embeddings)

        # Store document metadata
        for doc in docs:
            self.documents.append({
                "post_id": doc.get("post_id"),
                "post_number": doc.get("post_number"),
                "question_text": doc["question_text"],
                "answer_text": doc["answer_text"],
                "message_id": doc.get("message_id"),
            })

        # Rebuild BM25 indexes
        self._build_bm25_indexes()

        # Save to disk
        self._save_all_indexes()

    def _semantic_search_index(
        self,
        query: str,
        index: faiss.IndexFlatIP,
        top_k: int
    ) -> dict[int, float]:
        """Perform semantic search on a specific FAISS index"""
        query_embedding = self._encode([query])
        scores, indices = index.search(
            query_embedding.reshape(1, -1),
            min(top_k * 3, index.ntotal)
        )

        results = {}
        for score, idx in zip(scores[0], indices[0]):
            if idx == -1:
                continue
            results[int(idx)] = float(score)
        return results

    def _semantic_search(self, query: str, top_k: int) -> dict[int, float]:
        """Perform semantic search using combined index (backward compatible)"""
        return self._semantic_search_index(query, self.combined_index, top_k)

    def _multi_vector_search(self, query: str, top_k: int) -> dict[int, float]:
        """
        Perform multi-vector search across all indexes.
        Combines results from question, answer, and combined indexes.
        """
        # Search in all indexes
        question_results = self._semantic_search_index(query, self.question_index, top_k)
        answer_results = self._semantic_search_index(query, self.answer_index, top_k)
        combined_results = self._semantic_search_index(query, self.combined_index, top_k)

        # Combine using max score for each document
        all_results = {}

        for idx, score in question_results.items():
            all_results[idx] = max(all_results.get(idx, 0), score * 1.0)  # Questions weight

        for idx, score in answer_results.items():
            all_results[idx] = max(all_results.get(idx, 0), score * 0.9)  # Answers slightly lower

        for idx, score in combined_results.items():
            all_results[idx] = max(all_results.get(idx, 0), score * 0.95)  # Combined

        return all_results

    def _bm25_search_index(
        self,
        query: str,
        bm25_index: Optional[BM25Okapi],
        top_k: int
    ) -> dict[int, float]:
        """Perform BM25 search on a specific index"""
        if bm25_index is None:
            return {}

        tokens = self._tokenize(query)
        if not tokens:
            return {}

        scores = bm25_index.get_scores(tokens)
        top_indices = np.argsort(scores)[::-1][:top_k * 3]

        results = {}
        max_score = max(scores) if max(scores) > 0 else 1
        for idx in top_indices:
            if scores[idx] > 0:
                results[int(idx)] = float(scores[idx] / max_score)
        return results

    def _bm25_search(self, query: str, top_k: int) -> dict[int, float]:
        """Perform BM25 keyword search (backward compatible)"""
        return self._bm25_search_index(query, self.bm25, top_k)

    def _multi_bm25_search(self, query: str, top_k: int) -> dict[int, float]:
        """
        Perform multi-index BM25 search.
        Searches in questions and answers separately, then combines.
        """
        question_results = self._bm25_search_index(query, self.bm25_questions, top_k)
        answer_results = self._bm25_search_index(query, self.bm25_answers, top_k)

        # Combine using max score
        all_results = {}

        for idx, score in question_results.items():
            all_results[idx] = max(all_results.get(idx, 0), score)

        for idx, score in answer_results.items():
            all_results[idx] = max(all_results.get(idx, 0), score)

        return all_results

    def _reciprocal_rank_fusion(
        self,
        *result_dicts: dict[int, float],
        k: int = 60,
        weights: Optional[list[float]] = None
    ) -> dict[int, float]:
        """
        Combine multiple result sets using Reciprocal Rank Fusion (RRF).
        Supports variable number of result dictionaries with optional weights.
        """
        if weights is None:
            weights = [1.0] * len(result_dicts)

        rrf_scores = {}

        for results, weight in zip(result_dicts, weights):
            ranked = sorted(results.items(), key=lambda x: x[1], reverse=True)
            for rank, (idx, _) in enumerate(ranked):
                rrf_scores[idx] = rrf_scores.get(idx, 0) + weight / (k + rank + 1)

        return rrf_scores

    def search(
        self,
        query: str,
        top_k: int = 5,
        threshold: float = 0.5,
        use_synonyms: bool = True,
        use_multi_vector: bool = True  # New option to enable multi-vector search
    ) -> list[tuple[dict, float]]:
        """
        Advanced hybrid search combining semantic and keyword search.

        Args:
            query: Search query (question text)
            top_k: Maximum number of results
            threshold: Minimum similarity score (0-1)
            use_synonyms: Whether to expand query with synonyms
            use_multi_vector: Whether to use multi-vector search (recommended)

        Returns:
            List of (document, score) tuples sorted by relevance
        """
        if not self._initialized:
            raise RuntimeError("Search engine not initialized. Call initialize() first.")

        if self.combined_index.ntotal == 0:
            return []

        # Expand query with synonyms
        if use_synonyms:
            queries = expand_query(query)
        else:
            queries = [query]

        # Collect semantic results
        all_semantic = {}
        for q in queries:
            if use_multi_vector:
                results = self._multi_vector_search(q, top_k)
            else:
                results = self._semantic_search(q, top_k)

            for idx, score in results.items():
                if idx not in all_semantic or all_semantic[idx] < score:
                    all_semantic[idx] = score

        # Get BM25 results
        if use_multi_vector:
            bm25_results = self._multi_bm25_search(query, top_k)
        else:
            bm25_results = self._bm25_search(query, top_k)

        # Also search with expanded queries for BM25
        if use_synonyms:
            for q in queries[1:]:  # Skip original query
                additional_bm25 = self._multi_bm25_search(q, top_k) if use_multi_vector else self._bm25_search(q, top_k)
                for idx, score in additional_bm25.items():
                    if idx not in bm25_results or bm25_results[idx] < score:
                        bm25_results[idx] = score

        # Combine using RRF with weights favoring BM25 slightly
        # semantic_weight=0.3 means BM25 gets more influence
        if bm25_results:
            combined_scores = self._reciprocal_rank_fusion(
                all_semantic, bm25_results,
                weights=[0.3, 0.7]  # Semantic, BM25
            )
        else:
            combined_scores = all_semantic

        # Filter results
        BM25_THRESHOLD = 0.5

        filtered_results = []
        for idx, rrf_score in combined_scores.items():
            semantic_score = all_semantic.get(idx, 0)
            bm25_score = bm25_results.get(idx, 0)

            # Include if semantic score passes threshold OR BM25 score is high
            if semantic_score >= threshold or bm25_score >= BM25_THRESHOLD:
                display_score = max(semantic_score, bm25_score)
                filtered_results.append((idx, rrf_score, display_score))

        # Sort by RRF score
        filtered_results.sort(key=lambda x: x[1], reverse=True)

        # Return top_k with display score
        return [(self.documents[idx], display_score) for idx, _, display_score in filtered_results[:top_k]]

    def search_questions_only(
        self,
        query: str,
        top_k: int = 5,
        threshold: float = 0.5
    ) -> list[tuple[dict, float]]:
        """Search only in questions (useful for finding similar questions)"""
        if not self._initialized:
            raise RuntimeError("Search engine not initialized.")

        semantic_results = self._semantic_search_index(query, self.question_index, top_k)
        bm25_results = self._bm25_search_index(query, self.bm25_questions, top_k)

        combined = self._reciprocal_rank_fusion(semantic_results, bm25_results)

        filtered = [
            (idx, score) for idx, score in combined.items()
            if semantic_results.get(idx, 0) >= threshold or bm25_results.get(idx, 0) >= 0.5
        ]
        filtered.sort(key=lambda x: x[1], reverse=True)

        return [(self.documents[idx], max(semantic_results.get(idx, 0), bm25_results.get(idx, 0)))
                for idx, _ in filtered[:top_k]]

    def search_answers_only(
        self,
        query: str,
        top_k: int = 5,
        threshold: float = 0.5
    ) -> list[tuple[dict, float]]:
        """Search only in answers (useful for finding specific terms/details)"""
        if not self._initialized:
            raise RuntimeError("Search engine not initialized.")

        semantic_results = self._semantic_search_index(query, self.answer_index, top_k)
        bm25_results = self._bm25_search_index(query, self.bm25_answers, top_k)

        combined = self._reciprocal_rank_fusion(semantic_results, bm25_results)

        filtered = [
            (idx, score) for idx, score in combined.items()
            if semantic_results.get(idx, 0) >= threshold or bm25_results.get(idx, 0) >= 0.5
        ]
        filtered.sort(key=lambda x: x[1], reverse=True)

        return [(self.documents[idx], max(semantic_results.get(idx, 0), bm25_results.get(idx, 0)))
                for idx, _ in filtered[:top_k]]

    def get_document_count(self) -> int:
        """Get number of documents in the index"""
        return len(self.documents)

    def clear_index(self):
        """Clear all indexes"""
        self._create_empty_indexes()
        self.bm25_questions = None
        self.bm25_answers = None
        self.bm25 = None
        self.tokenized_corpus = []
        self._save_all_indexes()

    def rebuild_index(self, docs: list[dict]):
        """Rebuild all indexes from scratch"""
        self.documents = []
        self._create_empty_indexes()

        if docs:
            self.add_documents_batch(docs)

    def set_weights(self, question_weight: float = 0.6, answer_weight: float = 0.4):
        """
        Set weights for question/answer in combined embedding.

        Args:
            question_weight: Weight for questions (0-1)
            answer_weight: Weight for answers (0-1)

        Note: Weights don't need to sum to 1, they will be normalized.
        """
        total = question_weight + answer_weight
        self.question_weight = question_weight / total
        self.answer_weight = answer_weight / total


# Singleton instance
search_engine = SearchEngine()
