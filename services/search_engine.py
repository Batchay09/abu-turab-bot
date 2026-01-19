"""
Hybrid search engine using rubert-tiny-turbo, FAISS, and BM25.
Combines semantic search with keyword search for better relevance.
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
    """Hybrid search engine combining semantic (FAISS) and keyword (BM25) search"""

    MODEL_NAME = "sergeyzh/rubert-tiny-turbo"
    EMBEDDING_DIM = 312  # rubert-tiny-turbo output dimension
    BM25_INDEX_PATH = "data/bm25_corpus.json"

    def __init__(self):
        self.model: Optional[SentenceTransformer] = None
        self.index: Optional[faiss.IndexFlatIP] = None
        self.bm25: Optional[BM25Okapi] = None
        self.tokenized_corpus: list[list[str]] = []
        self.documents: list[dict] = []
        self._initialized = False

    @staticmethod
    def _tokenize(text: str) -> list[str]:
        """Simple tokenization for Russian text"""
        text = text.lower()
        text = re.sub(r'[^\w\s]', ' ', text)
        tokens = text.split()
        return [t for t in tokens if len(t) > 1]

    async def initialize(self):
        """Initialize the search engine - load model and index"""
        if self._initialized:
            return

        print(f"Loading model {self.MODEL_NAME}...")
        self.model = SentenceTransformer(self.MODEL_NAME)

        # Load existing index if available
        if os.path.exists(config.FAISS_INDEX_PATH) and os.path.exists(config.DOCUMENTS_PATH):
            print("Loading existing index...")
            self._load_index()
            self._build_bm25_index()
        else:
            print("Creating new empty index...")
            self.index = faiss.IndexFlatIP(self.EMBEDDING_DIM)
            self.documents = []
            self.bm25 = None

        self._initialized = True
        print(f"Search engine initialized. Documents in index: {len(self.documents)}")

    def _load_index(self):
        """Load FAISS index and documents from disk"""
        self.index = faiss.read_index(config.FAISS_INDEX_PATH)
        with open(config.DOCUMENTS_PATH, "r", encoding="utf-8") as f:
            self.documents = json.load(f)

    def _build_bm25_index(self):
        """Build BM25 index from documents"""
        if not self.documents:
            self.bm25 = None
            self.tokenized_corpus = []
            return

        print("Building BM25 index...")
        self.tokenized_corpus = []
        for doc in self.documents:
            combined = f"{doc['question_text']} {doc['answer_text']}"
            tokens = self._tokenize(combined)
            self.tokenized_corpus.append(tokens)

        self.bm25 = BM25Okapi(self.tokenized_corpus)
        print(f"BM25 index built with {len(self.tokenized_corpus)} documents")

    def _save_index(self):
        """Save FAISS index and documents to disk"""
        os.makedirs(config.DATA_DIR, exist_ok=True)
        faiss.write_index(self.index, config.FAISS_INDEX_PATH)
        with open(config.DOCUMENTS_PATH, "w", encoding="utf-8") as f:
            json.dump(self.documents, f, ensure_ascii=False, indent=2)

    def _encode(self, texts: list[str]) -> np.ndarray:
        """Encode texts to embeddings"""
        embeddings = self.model.encode(
            texts,
            normalize_embeddings=True,  # For cosine similarity via inner product
            convert_to_numpy=True
        )
        return embeddings.astype("float32")

    def add_document(self, doc: dict) -> int:
        """
        Add a document to the index.

        Args:
            doc: Document with keys: post_id, post_number, question_text, answer_text, message_id

        Returns:
            Index position of the added document
        """
        if not self._initialized:
            raise RuntimeError("Search engine not initialized. Call initialize() first.")

        # Create combined text for embedding (question + answer for better context)
        combined_text = f"{doc['question_text']} {doc['answer_text']}"

        # Generate embedding
        embedding = self._encode([combined_text])

        # Add to FAISS index
        self.index.add(embedding)

        # Store document metadata
        self.documents.append({
            "post_id": doc.get("post_id"),
            "post_number": doc.get("post_number"),
            "question_text": doc["question_text"],
            "answer_text": doc["answer_text"],
            "message_id": doc.get("message_id"),
        })

        # Save to disk
        self._save_index()

        return len(self.documents) - 1

    def add_documents_batch(self, docs: list[dict]):
        """
        Add multiple documents to the index in batch.

        Args:
            docs: List of documents
        """
        if not self._initialized:
            raise RuntimeError("Search engine not initialized. Call initialize() first.")

        if not docs:
            return

        # Create combined texts
        texts = [f"{d['question_text']} {d['answer_text']}" for d in docs]

        # Generate embeddings in batch
        embeddings = self._encode(texts)

        # Add to FAISS index
        self.index.add(embeddings)

        # Store document metadata
        for doc in docs:
            self.documents.append({
                "post_id": doc.get("post_id"),
                "post_number": doc.get("post_number"),
                "question_text": doc["question_text"],
                "answer_text": doc["answer_text"],
                "message_id": doc.get("message_id"),
            })

        # Save to disk
        self._save_index()

    def _semantic_search(self, query: str, top_k: int) -> dict[int, float]:
        """Perform semantic search using FAISS"""
        query_embedding = self._encode([query])
        scores, indices = self.index.search(
            query_embedding.reshape(1, -1),
            min(top_k * 3, self.index.ntotal)
        )

        results = {}
        for score, idx in zip(scores[0], indices[0]):
            if idx == -1:
                continue
            results[int(idx)] = float(score)
        return results

    def _bm25_search(self, query: str, top_k: int) -> dict[int, float]:
        """Perform BM25 keyword search"""
        if self.bm25 is None:
            return {}

        tokens = self._tokenize(query)
        if not tokens:
            return {}

        scores = self.bm25.get_scores(tokens)

        # Get top indices
        top_indices = np.argsort(scores)[::-1][:top_k * 3]

        results = {}
        max_score = max(scores) if max(scores) > 0 else 1
        for idx in top_indices:
            if scores[idx] > 0:
                # Normalize BM25 scores to 0-1 range
                results[int(idx)] = float(scores[idx] / max_score)
        return results

    def _reciprocal_rank_fusion(
        self,
        semantic_results: dict[int, float],
        bm25_results: dict[int, float],
        k: int = 60,
        semantic_weight: float = 0.5
    ) -> dict[int, float]:
        """
        Combine results using Reciprocal Rank Fusion (RRF).
        RRF score = sum(1 / (k + rank)) for each retriever
        """
        # Convert scores to rankings
        semantic_ranked = sorted(semantic_results.items(), key=lambda x: x[1], reverse=True)
        bm25_ranked = sorted(bm25_results.items(), key=lambda x: x[1], reverse=True)

        rrf_scores = {}

        # Add semantic RRF scores
        for rank, (idx, _) in enumerate(semantic_ranked):
            rrf_scores[idx] = rrf_scores.get(idx, 0) + semantic_weight / (k + rank + 1)

        # Add BM25 RRF scores
        bm25_weight = 1 - semantic_weight
        for rank, (idx, _) in enumerate(bm25_ranked):
            rrf_scores[idx] = rrf_scores.get(idx, 0) + bm25_weight / (k + rank + 1)

        return rrf_scores

    def search(
        self,
        query: str,
        top_k: int = 5,
        threshold: float = 0.5,
        use_synonyms: bool = True
    ) -> list[tuple[dict, float]]:
        """
        Hybrid search combining semantic and keyword (BM25) search.

        Args:
            query: Search query (question text)
            top_k: Maximum number of results
            threshold: Minimum similarity score (0-1) for semantic results
            use_synonyms: Whether to expand query with synonyms

        Returns:
            List of (document, score) tuples sorted by relevance
        """
        if not self._initialized:
            raise RuntimeError("Search engine not initialized. Call initialize() first.")

        if self.index.ntotal == 0:
            return []

        # Expand query with synonyms for better recall
        if use_synonyms:
            queries = expand_query(query)
        else:
            queries = [query]

        # Collect semantic results from all query variants
        all_semantic = {}
        for q in queries:
            results = self._semantic_search(q, top_k)
            for idx, score in results.items():
                if idx not in all_semantic or all_semantic[idx] < score:
                    all_semantic[idx] = score

        # Get BM25 results (using original query for exact keyword matching)
        bm25_results = self._bm25_search(query, top_k)

        # Combine using RRF
        # Lower semantic weight = higher BM25 importance (keyword matches)
        if bm25_results:
            combined_scores = self._reciprocal_rank_fusion(
                all_semantic, bm25_results, semantic_weight=0.3
            )
        else:
            # Fallback to semantic only
            combined_scores = all_semantic

        # Filter results - include if passes semantic OR has high BM25 score
        # BM25 threshold of 0.5 means document has good keyword match
        BM25_THRESHOLD = 0.5

        filtered_results = []
        for idx, rrf_score in combined_scores.items():
            semantic_score = all_semantic.get(idx, 0)
            bm25_score = bm25_results.get(idx, 0)

            # Include if semantic score passes threshold OR BM25 score is high
            if semantic_score >= threshold or bm25_score >= BM25_THRESHOLD:
                # Use max of both scores for display
                display_score = max(semantic_score, bm25_score)
                filtered_results.append((idx, rrf_score, display_score))

        # Sort by RRF score
        filtered_results.sort(key=lambda x: x[1], reverse=True)

        # Return top_k with display score
        return [(self.documents[idx], display_score) for idx, _, display_score in filtered_results[:top_k]]

    def get_document_count(self) -> int:
        """Get number of documents in the index"""
        return len(self.documents)

    def clear_index(self):
        """Clear the entire index"""
        self.index = faiss.IndexFlatIP(self.EMBEDDING_DIM)
        self.documents = []
        self.bm25 = None
        self.tokenized_corpus = []
        self._save_index()

    def rebuild_index(self, docs: list[dict]):
        """Rebuild the entire index from scratch"""
        self.clear_index()
        self.add_documents_batch(docs)
        self._build_bm25_index()


# Singleton instance
search_engine = SearchEngine()
