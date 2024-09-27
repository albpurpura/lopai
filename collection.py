import shutil
import os
import logging
from typing import List, Dict
from fastapi import HTTPException, UploadFile
from llama_index.core import Document, VectorStoreIndex, SimpleDirectoryReader, Settings
from llama_index.embeddings.huggingface import HuggingFaceEmbedding
from llama_index.llms.ollama import Ollama
from llama_index.core import StorageContext
from dotenv import load_dotenv
from llama_index.llms.openai import OpenAI
from llama_index.vector_stores.qdrant import QdrantVectorStore


load_dotenv()

EMBEDDING_MODEL = os.getenv("EMBEDDING_MODEL", "BAAI/bge-base-en-v1.5")
EMBEDDING_SIZE = os.getenv("EMBEDDING_SIZE", 768)
LLM_MODEL_NAME = os.getenv("LLM_MODEL_NAME", "llama3.2")
OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://ollama:11434")
COLLECTIONS_DIR = os.getenv("COLLECTIONS_DIR", "collections")
USE_OPENAI = os.getenv("USE_OPENAI", "False").lower() == "true"

# Set up logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class Collection:
    def __init__(self, client, name: str):
        self.client = client
        Settings.embed_model = HuggingFaceEmbedding(model_name=EMBEDDING_MODEL)

        if USE_OPENAI:
            Settings.llm = OpenAI(model="gpt-4o", temperature=0.1)
        else:
            Settings.llm = Ollama(
                model=LLM_MODEL_NAME, request_timeout=360.0, base_url=OLLAMA_BASE_URL
            )

        self.name = name
        self.data_dir = f"{COLLECTIONS_DIR}/{name}"

        if not os.path.exists(self.data_dir):
            os.makedirs(self.data_dir, exist_ok=True)

        # initializes index
        self.load_or_create_index()

    def load_or_create_index(self):
        self.vector_store = QdrantVectorStore(
            client=self.client, collection_name=self.name
        )
        self.storage_context = StorageContext.from_defaults(
            vector_store=self.vector_store
        )
        self.index = VectorStoreIndex.from_vector_store(
            vector_store=self.vector_store,
            storage_context=self.storage_context,
        )

        if not self.index.vector_store._collection_initialized:
            # if collection was not initialized create it
            self.index.vector_store._create_collection(
                collection_name=self.name,
                vector_size=EMBEDDING_SIZE,
            )

        self.query_engine = self.index.as_query_engine()

    def query(self, question: str) -> Dict:
        response = self.query_engine.query(question)
        file_names = [str(node.node.metadata) for node in response.source_nodes]
        return {
            "question": question,
            "answer": str(response),
            "source_files": file_names,
            "source_nodes": [
                {
                    "text": node.node.text,
                    "score": node.score,
                    "metadata": node.node.metadata,
                }
                for node in response.source_nodes
            ],
        }

    def get_existing_docs(
        self,
    ):
        return {
            item.ref_doc_id: item.extra_info
            for item in self.index.vector_store.get_nodes()
        }

    def upload_files(self, files: List[UploadFile]) -> Dict:
        tmp_dir = f"tmp_uploads/{self.name}"
        os.makedirs(tmp_dir, exist_ok=True)
        existing_docs = self.get_existing_docs()
        existing_fnames = [item["file_name"] for item in existing_docs.values()]
        files_to_update = []
        new_files = []

        for file in files:
            file_path = os.path.join(tmp_dir, file.filename)
            with open(file_path, "wb") as buffer:
                shutil.copyfileobj(file.file, buffer)

            if file.filename in existing_fnames:
                files_to_update.append(file.filename)
            else:
                new_files.append(file.filename)

        if files_to_update:
            return {
                "message": f"The following files already exist: {', '.join(files_to_update)}. Do you want to update them?",
                "files_to_update": files_to_update,
            }

        if new_files:
            documents = SimpleDirectoryReader(tmp_dir, recursive=True).load_data()
            doc_objects = [
                Document(text=doc.text, metadata=doc.metadata) for doc in documents
            ]

            for doc in doc_objects:
                self.index.insert(doc)
            # self.load_or_create_index()

        shutil.rmtree(tmp_dir)

        return {"message": f"Successfully added {len(new_files)} files to the index"}

    def update_files(self, files: List[str]) -> Dict:
        for file_name in files:
            doc_id = next(
                (
                    doc_id
                    for doc_id, doc in self.get_existing_docs()
                    if doc["file_name"] == file_name
                ),
                None,
            )
            if doc_id:
                self.index.delete_ref_doc(doc_id)

        tmp_dir = f"tmp_uploads/{self.name}"
        documents = SimpleDirectoryReader(tmp_dir, recursive=True).load_data()
        doc_objects = [
            Document(text=doc.text, metadata=doc.metadata) for doc in documents
        ]

        for doc in doc_objects:
            self.index.insert(doc)

        shutil.rmtree(tmp_dir)

        return {"message": f"Successfully updated {len(files)} files in the index"}

    def list_documents(self) -> List[Dict]:
        return [
            {"id": node_id, "metadata": doc}
            for node_id, doc in self.get_existing_docs().items()
        ]

    def delete_documents(self, doc_ids: List[str]) -> Dict:
        existing_docs = self.get_existing_docs()
        deleted_count = 0
        for doc_id in doc_ids:
            if doc_id in existing_docs:
                self.index.delete_ref_doc(doc_id)
                deleted_count += 1

        if deleted_count > 0:
            return {"message": f"{deleted_count} document(s) deleted successfully"}
        else:
            raise HTTPException(status_code=404, detail="No documents found to delete")
