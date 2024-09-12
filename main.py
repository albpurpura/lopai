import shutil
import os
import logging
from typing import List, Dict
from fastapi import FastAPI, HTTPException, Request, File, UploadFile, Query
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from llama_index.core import Document, VectorStoreIndex, SimpleDirectoryReader, Settings
from llama_index.embeddings.huggingface import HuggingFaceEmbedding
from llama_index.llms.ollama import Ollama
from llama_index.vector_stores.docarray import DocArrayHnswVectorStore
from llama_index.core import StorageContext, load_index_from_storage
from fastapi.middleware.cors import CORSMiddleware
import requests
import shutil

# Set up logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI()

# CORS middleware setup
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Serve static files
app.mount("/static", StaticFiles(directory="static"), name="static")


class Question(BaseModel):
    text: str


class Directory(BaseModel):
    path: str


class DeleteDocuments(BaseModel):
    doc_ids: List[str]


# Configuration
EMBEDDING_MODEL = "BAAI/bge-base-en-v1.5"
LLM_MODEL_NAME = "llama3.1"
# OLLAMA_BASE_URL = "http://0.0.0.0:11434"
OLLAMA_BASE_URL = "http://ollama:11434"
COLLECTIONS_DIR = "collections"
INDEX_DIR = "index_persist_dir"


# LlamaIndex settings
Settings.embed_model = HuggingFaceEmbedding(model_name=EMBEDDING_MODEL)
Settings.llm = Ollama(
    model=LLM_MODEL_NAME, request_timeout=360.0, base_url=OLLAMA_BASE_URL
)
if not os.path.exists(COLLECTIONS_DIR):
    os.makedirs(COLLECTIONS_DIR)


class Collection:
    def __init__(self, name: str):
        self.name = name
        self.data_dir = f"{COLLECTIONS_DIR}/{name}"
        self.index_persist_dir = f"index_persist_dir/{name}"
        if not os.path.exists(self.data_dir):
            os.makedirs(self.data_dir, exist_ok=True)
            shutil.copyfile(
                "./sample_doc.md", os.path.join(self.data_dir, "sample_doc.md")
            )
        self.vector_store = DocArrayHnswVectorStore(work_dir=self.index_persist_dir)
        self.index = self.load_or_create_index()
        self.query_engine = self.index.as_query_engine()

    def load_or_create_index(self):
        if not os.path.exists(os.path.join(self.index_persist_dir, "docstore.json")):
            logger.info(
                f"Index not found for collection {self.name}, creating new index"
            )
            storage_context = StorageContext.from_defaults(
                vector_store=self.vector_store
            )
            documents = SimpleDirectoryReader(self.data_dir).load_data()
            index = VectorStoreIndex.from_documents(documents)
            index.storage_context.persist(persist_dir=self.index_persist_dir)
            logger.info(f"Index saved to directory for collection {self.name}")
        else:
            logger.info(
                f"Index found for collection {self.name}, loading existing index"
            )
            storage_context = StorageContext.from_defaults(
                persist_dir=self.index_persist_dir
            )
            index = load_index_from_storage(storage_context)
            logger.info(f"Index loaded successfully for collection {self.name}")
        return index

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

    def upload_files(self, files: List[UploadFile]) -> Dict:
        tmp_dir = f"tmp_uploads/{self.name}"
        os.makedirs(tmp_dir, exist_ok=True)

        existing_docs = {
            doc.metadata["file_name"]: doc_id
            for doc_id, doc in self.index.ref_doc_info.items()
        }
        files_to_update = []
        new_files = []

        for file in files:
            file_path = os.path.join(tmp_dir, file.filename)
            with open(file_path, "wb") as buffer:
                shutil.copyfileobj(file.file, buffer)

            if file.filename in existing_docs:
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
            self.index.storage_context.persist(persist_dir=self.index_persist_dir)
            self.index = self.load_or_create_index()
            self.query_engine = self.index.as_query_engine()

        shutil.rmtree(tmp_dir)

        return {"message": f"Successfully added {len(new_files)} files to the index"}

    def update_files(self, files: List[str]) -> Dict:
        for file_name in files:
            doc_id = next(
                (
                    doc_id
                    for doc_id, doc in self.index.ref_doc_info.items()
                    if doc.metadata["file_name"] == file_name
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
        self.index.storage_context.persist(persist_dir=self.index_persist_dir)
        shutil.rmtree(tmp_dir)
        self.index = self.load_or_create_index()
        self.query_engine = self.index.as_query_engine()

        return {"message": f"Successfully updated {len(files)} files in the index"}

    def list_documents(self) -> List[Dict]:
        return [
            {"id": node_id, "metadata": doc.metadata}
            for node_id, doc in self.index.ref_doc_info.items()
        ]

    def delete_documents(self, doc_ids: List[str]) -> Dict:
        deleted_count = 0
        for doc_id in doc_ids:
            if doc_id in self.index.ref_doc_info:
                self.index.delete_ref_doc(doc_id)
                deleted_count += 1

        if deleted_count > 0:
            self.index.storage_context.persist(persist_dir=self.index_persist_dir)
            self.index = self.load_or_create_index()
            self.query_engine = self.index.as_query_engine()
            return {"message": f"{deleted_count} document(s) deleted successfully"}
        else:
            raise HTTPException(status_code=404, detail="No documents found to delete")


class CollectionManager:
    def __init__(self):
        self.collections: Dict[str, Collection] = {}

    def create_collection(self, name: str) -> Dict:
        if name in self.collections:
            raise HTTPException(
                status_code=400, detail=f"Collection '{name}' already exists"
            )
        self.collections[name] = Collection(name)
        return {"message": f"Collection '{name}' created successfully"}

    def delete_collection(self, name: str) -> Dict:
        if name not in self.collections:
            raise HTTPException(
                status_code=404, detail=f"Collection '{name}' not found"
            )
        del self.collections[name]
        shutil.rmtree(f"{COLLECTIONS_DIR}/{name}", ignore_errors=True)

        shutil.rmtree(f"index_persist_dir/{name}", ignore_errors=True)
        return {"message": f"Collection '{name}' deleted successfully"}

    def rename_collection(self, old_name: str, new_name: str) -> Dict:
        if old_name not in self.collections:
            raise HTTPException(
                status_code=404, detail=f"Collection '{old_name}' not found"
            )
        if new_name in self.collections:
            raise HTTPException(
                status_code=400, detail=f"Collection '{new_name}' already exists"
            )
        self.collections[new_name] = self.collections.pop(old_name)
        self.collections[new_name].name = new_name

        if os.path.exists(f"{COLLECTIONS_DIR}/{new_name}"):
            shutil.rmtree(f"{COLLECTIONS_DIR}/{new_name}")
        if os.path.exists(f"index_persist_dir/{new_name}"):
            shutil.rmtree(f"index_persist_dir/{new_name}")

        os.rename(f"{COLLECTIONS_DIR}/{old_name}", f"{COLLECTIONS_DIR}/{new_name}")
        os.rename(f"index_persist_dir/{old_name}", f"index_persist_dir/{new_name}")
        return {
            "message": f"Collection renamed from '{old_name}' to '{new_name}' successfully"
        }

    def get_collection(self, name: str) -> Collection:
        if name not in self.collections:
            raise HTTPException(
                status_code=404, detail=f"Collection '{name}' not found"
            )
        return self.collections[name]


@app.post("/collections/{collection_name}/query")
async def query(collection_name: str, question: Question):
    try:
        collection = collection_manager.get_collection(collection_name)
        return collection.query(question.text)
    except Exception as e:
        logger.error(f"Error processing query: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Internal server error: {str(e)}")


@app.post("/collections/{collection_name}/upload_files")
async def upload_files(collection_name: str, files: List[UploadFile] = File(...)):
    try:
        collection = collection_manager.get_collection(collection_name)
        return collection.upload_files(files)
    except Exception as e:
        logger.error(f"Error uploading files: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Failed to upload files: {str(e)}")


@app.post("/collections/{collection_name}/update_files")
async def update_files(collection_name: str, files: List[str]):
    try:
        collection = collection_manager.get_collection(collection_name)
        return collection.update_files(files)
    except Exception as e:
        logger.error(f"Error updating files: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Failed to update files: {str(e)}")


@app.get("/collections/{collection_name}/list_documents")
async def list_documents(collection_name: str):
    try:
        collection = collection_manager.get_collection(collection_name)
        return {"documents": collection.list_documents()}
    except Exception as e:
        logger.error(f"Error listing documents: {str(e)}")
        raise HTTPException(
            status_code=500, detail=f"Failed to list documents: {str(e)}"
        )


@app.delete("/collections/{collection_name}/delete_documents")
async def delete_documents(collection_name: str, delete_request: DeleteDocuments):
    try:
        collection = collection_manager.get_collection(collection_name)
        return collection.delete_documents(delete_request.doc_ids)
    except Exception as e:
        logger.error(f"Error deleting documents: {str(e)}")
        raise HTTPException(
            status_code=500, detail=f"Failed to delete documents: {str(e)}"
        )


@app.post("/collections")
async def create_collection(request: Request):
    data = await request.json()
    if "name" not in data:
        return jsonify({"error": "Name is required"}), 422
    name = data["name"]
    if not name:
        return jsonify({"error": "Name cannot be empty"}), 422
    return collection_manager.create_collection(name)


@app.get("/collections")
async def list_collections():
    try:
        return list(collection_manager.collections.keys())
    except Exception as e:
        logger.error(f"Error listing collections: {str(e)}")
        raise HTTPException(
            status_code=500, detail=f"Failed to list collections: {str(e)}"
        )


@app.delete("/collections/{name}")
async def delete_collection(name: str):
    return collection_manager.delete_collection(name)


@app.put("/collections/{old_name}")
async def rename_collection(old_name: str, new_name: str = Query(...)):
    return collection_manager.rename_collection(old_name, new_name)


@app.get("/", response_class=HTMLResponse)
async def root(request: Request):
    with open("static/index.html", "r") as f:
        html_content = f.read()
    return HTMLResponse(content=html_content)


def load_existing_collections(collection_manager: CollectionManager):
    for collection_name in os.listdir(f"{COLLECTIONS_DIR}"):
        if os.path.isfile(os.path.join(f"{COLLECTIONS_DIR}", collection_name)):
            continue
        if os.path.exists(os.path.join(f"{COLLECTIONS_DIR}", collection_name)):
            collection = Collection(collection_name)
            collection.index = load_index_from_storage(
                StorageContext.from_defaults(
                    persist_dir=f"index_persist_dir/{collection_name}"
                )
            )
            collection.query_engine = collection.index.as_query_engine()
            collection_manager.collections[collection_name] = collection


if __name__ == "__main__":
    import uvicorn

    collection_manager = CollectionManager()
    load_existing_collections(collection_manager)
    uvicorn.run(app, host="0.0.0.0", port=8000)
