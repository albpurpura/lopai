import shutil
from fastapi import FastAPI, HTTPException, Request, File, UploadFile
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from llama_index.core import Document, VectorStoreIndex, SimpleDirectoryReader, Settings
from llama_index.embeddings.huggingface import HuggingFaceEmbedding
from llama_index.llms.ollama import Ollama
from llama_index.vector_stores.docarray import DocArrayHnswVectorStore
from llama_index.core import StorageContext, load_index_from_storage
import os
from fastapi.middleware.cors import CORSMiddleware
import logging
import requests
from typing import List

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


# Configuration
data_dir = "documents"
embedding_model = "BAAI/bge-base-en-v1.5"
vector_store_index_dir = "vector_store_index"
index_persist_dir = "index_persist_dir"
llm_model_name = "llama3.1"
# ollama_base_url = "http://ollama:11434"
ollama_base_url = "http://0.0.0.0:11434"

# LlamaIndex settings
Settings.embed_model = HuggingFaceEmbedding(model_name=embedding_model)
Settings.llm = Ollama(
    model=llm_model_name, request_timeout=360.0, base_url=ollama_base_url
)
vector_store = DocArrayHnswVectorStore(work_dir=index_persist_dir)


def load_or_create_index():
    if not os.path.exists(os.path.join(index_persist_dir, "docstore.json")):
        logger.info("Index not found, creating new index")
        storage_context = StorageContext.from_defaults(vector_store=vector_store)
        documents = SimpleDirectoryReader(data_dir).load_data()
        index = VectorStoreIndex.from_documents(documents)
        index.storage_context.persist(persist_dir=index_persist_dir)
        logger.info("Index saved to directory")
    else:
        logger.info("Index found, loading existing index")
        storage_context = StorageContext.from_defaults(persist_dir=index_persist_dir)
        index = load_index_from_storage(storage_context)
        logger.info("Index loaded successfully")
    return index


# Initialize index and query engine
try:
    index = load_or_create_index()
    query_engine = index.as_query_engine()
except Exception as e:
    logger.error(f"Failed to initialize index or query engine: {str(e)}")
    raise


@app.post("/query")
async def query(question: Question):
    try:
        # Test connection to Ollama
        try:
            response = requests.get(f"{ollama_base_url}/api/tags")
            if response.status_code != 200:
                raise Exception(
                    f"Ollama service returned status code {response.status_code}"
                )
        except requests.RequestException as e:
            logger.error(f"Failed to connect to Ollama service: {str(e)}")
            raise HTTPException(status_code=503, detail="Ollama service is unavailable")

        # Proceed with the query
        response = query_engine.query(question.text)
        file_names = [
            str(node.node.metadata)
            for node in response.source_nodes
        ]
        return {
            "question": question.text,
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
    except Exception as e:
        logger.error(f"Error processing query: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Internal server error: {str(e)}")


@app.post("/upload_files")
async def upload_files(files: List[UploadFile] = File(...)):
    try:
        global index
        tmp_dir = "tmp_uploads"
        os.makedirs(tmp_dir, exist_ok=True)

        # Fetch existing documents by filename
        existing_docs = {
            doc.metadata["file_name"]: doc_id
            for doc_id, doc in index.ref_doc_info.items()
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
            return JSONResponse(
                content={
                    "message": f"The following files already exist: {', '.join(files_to_update)}. Do you want to update them?",
                    "files_to_update": files_to_update,
                },
                status_code=409,
            )

        if new_files:
            # Only add new files to the index
            documents = SimpleDirectoryReader(tmp_dir, recursive=True).load_data()
            doc_objects = [
                Document(text=doc.text, metadata=doc.metadata) for doc in documents
            ]
            
            for doc in doc_objects:
                index.insert(doc)
            index.storage_context.persist(persist_dir=index_persist_dir)
            # updating index and reloading
            index = load_or_create_index()
            query_engine = index.as_query_engine()
    
        shutil.rmtree(tmp_dir)

        return JSONResponse(
            content={
                "message": f"Successfully added {len(new_files)} files to the index"
            }
        )
    except Exception as e:
        logger.error(f"Error uploading files: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Failed to upload files: {str(e)}")


@app.post("/update_files")
async def update_files(files: List[str]):
    try:
        global index
        for file_name in files:
            doc_id = next(
                (
                    doc_id
                    for doc_id, doc in index.ref_doc_info.items()
                    if doc.metadata["file_name"] == file_name
                ),
                None,
            )
            if doc_id:
                index.delete_ref_doc(doc_id)

        tmp_dir = "tmp_uploads"
        documents = SimpleDirectoryReader(tmp_dir, recursive=True).load_data()
        doc_objects = [
            Document(text=doc.text, metadata=doc.metadata) for doc in documents
        ]

        for doc in doc_objects:
            index.insert(doc)
        index.storage_context.persist(persist_dir=index_persist_dir)
        shutil.rmtree(tmp_dir)
        # updating index and reloading
        index = load_or_create_index()
        query_engine = index.as_query_engine()
    
        return JSONResponse(
            content={"message": f"Successfully updated {len(files)} files in the index"}
        )
    except Exception as e:
        logger.error(f"Error updating files: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Failed to update files: {str(e)}")


@app.get("/list_documents")
async def list_documents():
    try:
        doc_list = [
            {"id": node_id, "metadata": doc.metadata}
            for node_id, doc in index.ref_doc_info.items()
        ]
        return {"documents": doc_list}
    except Exception as e:
        logger.error(f"Error listing documents: {str(e)}")
        raise HTTPException(
            status_code=500, detail=f"Failed to list documents: {str(e)}"
        )


@app.delete("/delete_document/{doc_id}")
async def delete_document(doc_id: str):
    try:
        global index
        if doc_id in index.ref_doc_info:
            index.delete_ref_doc(doc_id)
            index.storage_context.persist(persist_dir=index_persist_dir)
            return JSONResponse(
                content={"message": f"Document {doc_id} deleted successfully"}
            )
            # updating index and reloading
            index = load_or_create_index()
            query_engine = index.as_query_engine()
        else:
            raise HTTPException(status_code=404, detail=f"Document {doc_id} not found")
    except Exception as e:
        logger.error(f"Error deleting document: {str(e)}")
        raise HTTPException(
            status_code=500, detail=f"Failed to delete document: {str(e)}"
        )


@app.get("/", response_class=HTMLResponse)
async def root(request: Request):
    with open("static/index.html", "r") as f:
        html_content = f.read()
    return HTMLResponse(content=html_content)


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8000)
