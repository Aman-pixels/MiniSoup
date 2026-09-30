"""AST-aware repository retriever using Tree-Sitter, Voyage AI, and ChromaDB.

Key Features:
- AST parsing using tree-sitter-python for semantic function/class/method chunking.
- No raw line splitting: respects syntax boundaries and contextual docstrings.
- Embeds with voyage-code-2 (via voyageai client) with graceful fallback if API key is unset.
- Embedded local ChromaDB vector store (no external infrastructure required).
- Interactive CLI for manual sanity-check queries (e.g., 'JWT auth logic').
"""

import argparse
from dataclasses import dataclass
import os
from pathlib import Path
import sys
from typing import Any, Dict, List, Optional

import chromadb
from chromadb.api.types import EmbeddingFunction, Documents, Embeddings
import tree_sitter_python as tspython
from tree_sitter import Language, Parser, Node

import config

# Initialize tree-sitter Python parser
PY_LANGUAGE = Language(tspython.language())
_AST_PARSER = Parser(PY_LANGUAGE)


@dataclass
class CodeChunk:
    """Represents an AST-extracted semantic code chunk."""
    chunk_id: str
    file_path: str
    chunk_type: str  # 'function', 'class', 'method', 'module_header'
    name: str
    start_line: int
    end_line: int
    content: str

    @property
    def contextual_text(self) -> str:
        """Formatted text with file path and scope header for optimal embedding."""
        return (
            f"# File: {self.file_path} | Type: {self.chunk_type} | "
            f"Symbol: {self.name} | Lines {self.start_line}-{self.end_line}\n"
            f"{self.content}"
        )


@dataclass
class SearchResult:
    """Result of a semantic code search."""
    chunk_id: str
    file_path: str
    chunk_type: str
    name: str
    start_line: int
    end_line: int
    content: str
    score: float


class VoyageCodeEmbeddingFunction(EmbeddingFunction):
    """Embedding function utilizing Voyage AI's voyage-code-2 model."""

    def __init__(self, api_key: str, model_name: str = config.VOYAGE_EMBED_MODEL):
        import voyageai
        self.client = voyageai.Client(api_key=api_key)
        self.model_name = model_name

    def __call__(self, input: Documents) -> Embeddings:
        """Embed a list of documents for indexing."""
        res = self.client.embed(
            texts=list(input),
            model=self.model_name,
            input_type="document"
        )
        return res.embeddings

    def embed_query(self, input: Any, **kwargs) -> Embeddings:
        """Embed query documents."""
        texts = [input] if isinstance(input, str) else list(input)
        res = self.client.embed(
            texts=texts,
            model=self.model_name,
            input_type="query"
        )
        return res.embeddings


class FallbackEmbeddingFunction(EmbeddingFunction):
    """Fallback local embedding function using Chroma's default sentence-transformers model."""

    def __init__(self):
        from chromadb.utils import embedding_functions
        self._fn = embedding_functions.DefaultEmbeddingFunction()

    def __call__(self, input: Documents) -> Embeddings:
        return self._fn(input)

    def embed_query(self, input: Any, **kwargs) -> Embeddings:
        if hasattr(self._fn, "embed_query"):
            return self._fn.embed_query(input=input)
        texts = [input] if isinstance(input, str) else list(input)
        return self._fn(texts)


def get_embedding_function() -> tuple[EmbeddingFunction, str]:
    """Return appropriate embedding function based on environment."""
    api_key = os.environ.get("VOYAGE_API_KEY", config.VOYAGE_API_KEY).strip()
    if api_key:
        try:
            return VoyageCodeEmbeddingFunction(api_key=api_key), f"voyageai ({config.VOYAGE_EMBED_MODEL})"
        except Exception as e:
            print(f"[WARN] Failed to initialize Voyage AI client ({e}). Falling back to local embeddings.")
    
    return FallbackEmbeddingFunction(), "local (all-MiniLM-L6-v2 / Chroma default)"


class CodeChunker:
    """AST-aware Python code chunker using Tree-sitter."""

    @staticmethod
    def chunk_python_code(file_path: str, code_bytes: bytes) -> List[CodeChunk]:
        """Parse Python source code and extract function, class, and method chunks."""
        tree = _AST_PARSER.parse(code_bytes)
        root = tree.root_node
        lines = code_bytes.decode("utf-8", errors="replace").splitlines()

        chunks: List[CodeChunk] = []

        def get_node_text(node: Node) -> str:
            return node.text.decode("utf-8", errors="replace")

        def get_identifier(node: Node) -> str:
            for child in node.children:
                if child.type == "identifier":
                    return get_node_text(child)
            return "anonymous"

        # 1. Extract module header (imports, module docstrings, globals)
        header_nodes = []
        for child in root.children:
            if child.type in ("import_statement", "import_from_statement", "expression_statement"):
                header_nodes.append(child)
            elif child.type in ("function_definition", "class_definition"):
                break

        if header_nodes:
            start_line = header_nodes[0].start_point.row + 1
            end_line = header_nodes[-1].end_point.row + 1
            header_text = "\n".join(lines[start_line - 1:end_line]).strip()
            if header_text:
                chunks.append(CodeChunk(
                    chunk_id=f"{file_path}:module_header:{start_line}-{end_line}",
                    file_path=file_path,
                    chunk_type="module_header",
                    name="<module_imports>",
                    start_line=start_line,
                    end_line=end_line,
                    content=header_text
                ))

        # 2. Traverse AST for classes and functions
        for child in root.children:
            if child.type == "function_definition":
                fn_name = get_identifier(child)
                start_l = child.start_point.row + 1
                end_l = child.end_point.row + 1
                content = "\n".join(lines[start_l - 1:end_l])
                chunks.append(CodeChunk(
                    chunk_id=f"{file_path}:fn:{fn_name}:{start_l}-{end_l}",
                    file_path=file_path,
                    chunk_type="function",
                    name=fn_name,
                    start_line=start_l,
                    end_line=end_l,
                    content=content
                ))

            elif child.type == "class_definition":
                cls_name = get_identifier(child)
                cls_start = child.start_point.row + 1
                cls_end = child.end_point.row + 1
                cls_content = "\n".join(lines[cls_start - 1:cls_end])

                # Add whole class chunk
                chunks.append(CodeChunk(
                    chunk_id=f"{file_path}:class:{cls_name}:{cls_start}-{cls_end}",
                    file_path=file_path,
                    chunk_type="class",
                    name=cls_name,
                    start_line=cls_start,
                    end_line=cls_end,
                    content=cls_content
                ))

                # Also extract individual methods inside class for fine-grained retrieval
                body_node = None
                for c in child.children:
                    if c.type == "block":
                        body_node = c
                        break

                if body_node:
                    for member in body_node.children:
                        if member.type == "function_definition":
                            method_name = get_identifier(member)
                            m_start = member.start_point.row + 1
                            m_end = member.end_point.row + 1
                            m_content = "\n".join(lines[m_start - 1:m_end])
                            chunks.append(CodeChunk(
                                chunk_id=f"{file_path}:method:{cls_name}.{method_name}:{m_start}-{m_end}",
                                file_path=file_path,
                                chunk_type="method",
                                name=f"{cls_name}.{method_name}",
                                start_line=m_start,
                                end_line=m_end,
                                content=m_content
                            ))

        return chunks


class RepoRetriever:
    """Manages indexing and semantic retrieval of repository codebase."""

    def __init__(
        self,
        persist_dir: Path | str = config.CHROMA_PERSIST_DIR,
        collection_name: str = config.CHROMA_COLLECTION_NAME
    ):
        self.persist_dir = Path(persist_dir)
        self.embedding_fn, self.embedding_provider = get_embedding_function()

        provider_suffix = "voyage" if "voyageai" in self.embedding_provider else "local"
        if collection_name == config.CHROMA_COLLECTION_NAME:
            self.collection_name = f"{collection_name}_{provider_suffix}"
        else:
            self.collection_name = collection_name

        # Initialize embedded persistent Chroma client
        self.client = chromadb.PersistentClient(path=str(self.persist_dir))
        try:
            self.collection = self.client.get_or_create_collection(
                name=self.collection_name,
                embedding_function=self.embedding_fn,
                metadata={"hnsw:space": "cosine"}
            )
        except Exception:
            try:
                self.client.delete_collection(name=self.collection_name)
            except Exception:
                pass
            self.collection = self.client.create_collection(
                name=self.collection_name,
                embedding_function=self.embedding_fn,
                metadata={"hnsw:space": "cosine"}
            )

    def index_repository(self, repo_path: Path | str, reset: bool = True) -> int:
        """Scan Python files in repo, extract AST chunks, and index into Chroma.
        
        Args:
            repo_path: Path to target repository.
            reset: If True, clear existing collection before indexing.
            
        Returns:
            Number of indexed chunks.
        """
        path = Path(repo_path).resolve()
        if not path.exists():
            raise FileNotFoundError(f"Target repository not found: {path}")

        if reset:
            try:
                self.client.delete_collection(self.collection_name)
            except Exception:
                pass
            self.collection = self.client.get_or_create_collection(
                name=self.collection_name,
                embedding_function=self.embedding_fn,
                metadata={"hnsw:space": "cosine"}
            )

        ignore_dirs = {".git", "__pycache__", ".pytest_cache", ".venv", "venv", "node_modules", ".chroma_db"}
        chunks: List[CodeChunk] = []

        for py_file in path.rglob("*.py"):
            # Check if any parent is in ignore_dirs
            if any(part in ignore_dirs for part in py_file.parts):
                continue

            rel_path = py_file.relative_to(path).as_posix()
            try:
                code_bytes = py_file.read_bytes()
                file_chunks = CodeChunker.chunk_python_code(rel_path, code_bytes)
                chunks.extend(file_chunks)
            except Exception as e:
                print(f"[WARN] Failed to parse {rel_path}: {e}")

        if not chunks:
            return 0

        # Batch upsert into Chroma
        ids = [c.chunk_id for c in chunks]
        documents = [c.contextual_text for c in chunks]
        metadatas = [
            {
                "file_path": c.file_path,
                "chunk_type": c.chunk_type,
                "name": c.name,
                "start_line": c.start_line,
                "end_line": c.end_line,
                "content": c.content
            }
            for c in chunks
        ]

        # Chroma handles batches
        batch_size = 100
        for i in range(0, len(chunks), batch_size):
            self.collection.add(
                ids=ids[i:i+batch_size],
                documents=documents[i:i+batch_size],
                metadatas=metadatas[i:i+batch_size]
            )

        return len(chunks)

    def query(self, query_text: str, n_results: int = 4) -> List[SearchResult]:
        """Perform semantic search against indexed code chunks.
        
        Args:
            query_text: Natural-language bug description or symbol query.
            n_results: Top-k results to return.
            
        Returns:
            List of SearchResult objects sorted by relevance.
        """
        results = self.collection.query(
            query_texts=[query_text],
            n_results=min(n_results, self.collection.count() or 1)
        )

        search_results: List[SearchResult] = []
        if not results or not results["ids"] or not results["ids"][0]:
            return search_results

        ids = results["ids"][0]
        distances = results.get("distances", [[]])[0]
        metadatas = results.get("metadatas", [[]])[0]

        for i, chunk_id in enumerate(ids):
            meta = metadatas[i]
            # Convert cosine distance to similarity score
            dist = distances[i] if i < len(distances) else 1.0
            score = 1.0 - dist if dist is not None else 0.0

            search_results.append(SearchResult(
                chunk_id=chunk_id,
                file_path=meta.get("file_path", ""),
                chunk_type=meta.get("chunk_type", ""),
                name=meta.get("name", ""),
                start_line=meta.get("start_line", 0),
                end_line=meta.get("end_line", 0),
                content=meta.get("content", ""),
                score=score
            ))

        return search_results


def run_manual_query(query: str, repo_path: Path = config.TARGET_REPO_PATH, n_results: int = 4):
    """CLI helper to index target repo and print top semantic retrieval results."""
    print("\n" + "="*65)
    print(f"[SEARCH] Semantic AST Retrieval Query: '{query}'")
    print("="*65)

    retriever = RepoRetriever()
    print(f"[INFO] Embedding Engine: {retriever.embedding_provider}")
    print(f"[INFO] Indexing target repository at: {repo_path} ...")
    
    count = retriever.index_repository(repo_path, reset=True)
    print(f"[OK] Successfully indexed {count} AST code chunks into ChromaDB.")

    print(f"\n[INFO] Running search for top {n_results} results...")
    results = retriever.query(query, n_results=n_results)

    if not results:
        print("[WARN] No matching code chunks found.")
        return

    for idx, r in enumerate(results, 1):
        print("\n" + "-"*65)
        print(f"Result #{idx} | Score: {r.score:.4f} | Type: {r.chunk_type} | Symbol: {r.name}")
        print(f"Location: {r.file_path} (Lines {r.start_line}-{r.end_line})")
        print("-" * 65)
        # Print snippet indented
        for line in r.content.splitlines()[:12]:
            print(f"  {line}")
        if len(r.content.splitlines()) > 12:
            print("  ... [truncated]")

    print("\n" + "="*65 + "\n")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Query repository AST code chunks")
    parser.add_argument("query", nargs="?", default="JWT auth logic", help="Search query")
    parser.add_argument("--repo", default=str(config.TARGET_REPO_PATH), help="Repo path")
    parser.add_argument("-n", "--top-k", type=int, default=3, help="Number of results")

    args = parser.parse_args()
    run_manual_query(args.query, repo_path=Path(args.repo), n_results=args.top_k)
