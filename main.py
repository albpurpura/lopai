import os
import logging
from typing import List
from fastapi import FastAPI, HTTPException, Request, File, UploadFile, Query
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from llama_index.core import StorageContext, load_index_from_storage
from fastapi.middleware.cors import CORSMiddleware
import os
from collection_manager import CollectionManager
from collection import Collection
from dotenv import load_dotenv

load_dotenv()

COLLECTIONS_DIR = os.getenv("COLLECTIONS_DIR", "collections")

if not os.path.exists(COLLECTIONS_DIR):
    os.makedirs(COLLECTIONS_DIR)

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


if __name__ == "__main__":
    import uvicorn

    collection_manager = CollectionManager()
    uvicorn.run(app, host="0.0.0.0", port=8000)
