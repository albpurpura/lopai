from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from llama_index.core import VectorStoreIndex, SimpleDirectoryReader, Settings
from llama_index.embeddings.huggingface import HuggingFaceEmbedding
from llama_index.llms.ollama import Ollama
from llama_index.vector_stores.docarray import DocArrayHnswVectorStore
from llama_index.core import StorageContext, load_index_from_storage
import os
from fastapi.middleware.cors import CORSMiddleware
import logging
import requests

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

class Question(BaseModel):
    text: str

# Configuration
data_dir = "documents"
embedding_model = "BAAI/bge-base-en-v1.5"
vector_store_index_dir = "vector_store_index"
index_persist_dir = "index_persist_dir"
llm_model_name = "llama3.1"
ollama_base_url = "http://ollama:11434"

# LlamaIndex settings
Settings.embed_model = HuggingFaceEmbedding(model_name=embedding_model)
Settings.llm = Ollama(model=llm_model_name, request_timeout=360.0, base_url=ollama_base_url)
vector_store = DocArrayHnswVectorStore(work_dir=index_persist_dir)

def load_or_create_index():
    if not os.path.exists(os.path.join(index_persist_dir, "docstore.json")):
        logger.info('Index not found, creating new index')
        storage_context = StorageContext.from_defaults(vector_store=vector_store)
        documents = SimpleDirectoryReader(data_dir).load_data()
        index = VectorStoreIndex.from_documents(documents)
        index.storage_context.persist(persist_dir=index_persist_dir)
        logger.info('Index saved to directory')
    else:
        logger.info('Index found, loading existing index')
        storage_context = StorageContext.from_defaults(persist_dir=index_persist_dir)
        index = load_index_from_storage(storage_context)
        logger.info('Index loaded successfully')
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
                raise Exception(f"Ollama service returned status code {response.status_code}")
        except requests.RequestException as e:
            logger.error(f"Failed to connect to Ollama service: {str(e)}")
            raise HTTPException(status_code=503, detail="Ollama service is unavailable")

        # Proceed with the query
        response = query_engine.query(question.text)
        return {
            "question": question.text,
            "answer": str(response),
        }
    except Exception as e:
        logger.error(f"Error processing query: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Internal server error: {str(e)}")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)