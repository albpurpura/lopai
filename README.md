## Step 1
Download some sample data to search like the Graham's essays collection.

```
git clone git@github.com:ofou/graham-essays.git
cd graham-essays
make
```

Create directory to store the data to index/search:
`mkdir ./documents`

## Step 2
Download data:
```
git clone git@github.com:ofou/graham-essays.git
cd graham-essays
make
cp essays/*.md <your local rag repo code>/documents
```

## Step 3
Start the system and wait for it to download the LLM and -- if it's the first time you run it -- to index the data. It will take a few minutes depending on your internet connection, keep an eye on the logs.
```
docker-copose up --build
```

## Step 4
Once running, the server will be ready to answer your questions at the `localhost:8000` address.

Example:

```
curl -X POST "http://0.0.0.0:8000/query" -H "Content-Type: application/json" -d '{"text": "when is the best time in your life to start a new company?"}'
```