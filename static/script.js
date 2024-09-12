const sidebar = document.getElementById('sidebar');
const sidebarToggle = document.getElementById('sidebarToggle');
const modal = document.getElementById('modal');
const modalTitle = document.getElementById('modalTitle');
const addDocumentsBtn = document.getElementById('addDocumentsBtn');
const cancelUpload = document.getElementById('cancelUpload');
const dropZone = document.getElementById('dropZone');
const fileList = document.getElementById('fileList');
const uploadBtn = document.getElementById('uploadBtn');
const searchInput = document.getElementById('searchInput');
const searchBtn = document.getElementById('searchBtn');
const searchResult = document.getElementById('searchResult');
const createCollectionBtn = document.getElementById('createCollectionBtn');
const collectionList = document.getElementById('collectionList');
const currentCollectionElement = document.getElementById('currentCollection');

let selectedFiles = [];
let currentCollection = null;

sidebarToggle.addEventListener('click', () => {
    sidebar.classList.toggle('-translate-x-full');
});

addDocumentsBtn.addEventListener('click', () => {
    if (!currentCollection) {
        alert('Please select a collection first.');
        return;
    }
    modalTitle.textContent = 'Add Documents';
    modal.classList.remove('hidden');
    modal.classList.add('flex');
});

cancelUpload.addEventListener('click', closeModal);

function closeModal() {
    modal.classList.remove('flex');
    modal.classList.add('hidden');
    fileList.innerHTML = '';
    selectedFiles = [];
}

dropZone.addEventListener('click', () => {
    const input = document.createElement('input');
    input.type = 'file';
    input.multiple = true;
    input.onchange = (e) => {
        handleFiles(e.target.files);
    };
    input.click();
});

dropZone.addEventListener('dragover', (e) => {
    e.preventDefault();
    dropZone.classList.add('bg-gray-200');
});

dropZone.addEventListener('dragleave', () => {
    dropZone.classList.remove('bg-gray-200');
});

dropZone.addEventListener('drop', (e) => {
    e.preventDefault();
    dropZone.classList.remove('bg-gray-200');
    handleFiles(e.dataTransfer.files);
});

function handleFiles(files) {
    selectedFiles = [...selectedFiles, ...files];
    updateFileList();
}

function updateFileList() {
    fileList.innerHTML = selectedFiles.map(file => `<div>${file.name}</div>`).join('');
}

uploadBtn.addEventListener('click', uploadFiles);

async function uploadFiles() {
    if (!currentCollection) {
        alert('Please select a collection first.');
        return;
    }

    if (fileList.children.length === 0) {
        alert('Please select at least one file to upload.');
        return;
    }

    uploadBtn.disabled = true;
    uploadBtn.innerHTML = '<i class="fas fa-spinner fa-spin mr-2"></i>Uploading...';

    const formData = new FormData();
    for (const file of selectedFiles) {
        formData.append('files', file);
    }

    try {
        const response = await fetch(`/collections/${currentCollection}/upload_files`, {
            method: 'POST',
            body: formData
        });

        if (!response.ok) {
            if (response.status === 409) {
                const result = await response.json();
                if (confirm(result.message)) {
                    await updateFiles(result.files_to_update);
                } else {
                    throw new Error('Upload cancelled');
                }
            } else {
                throw new Error('Upload failed');
            }
        }

        const result = await response.json();
        alert(result.message);
        closeModal();
        loadDocumentList();
    } catch (error) {
        console.error('Error:', error);
        alert('Failed to upload files. Please try again.');
    } finally {
        uploadBtn.disabled = false;
        uploadBtn.innerHTML = 'Upload';
    }
}

async function updateFiles(filesToUpdate) {
    try {
        const response = await fetch(`/collections/${currentCollection}/update_files`, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
            },
            body: JSON.stringify({ files: filesToUpdate }),
        });

        if (!response.ok) {
            throw new Error('Update failed');
        }

        const result = await response.json();
        alert(result.message);
        closeModal();
        loadDocumentList();
    } catch (error) {
        console.error('Error:', error);
        alert('Failed to update files. Please try again.');
    }
}

async function loadDocumentList() {
    if (!currentCollection) {
        return;
    }

    try {
        const response = await fetch(`/collections/${currentCollection}/list_documents`);
        const data = await response.json();
        const documentList = document.getElementById('documentList');
        documentList.innerHTML = '';

        // Group documents by file_name
        const groupedDocuments = data.documents.reduce((acc, doc) => {
            const fileName = doc.metadata.file_name;
            if (!acc[fileName]) {
                acc[fileName] = [];
            }
            acc[fileName].push(doc);
            return acc;
        }, {});

        // Create list items for each unique file_name
        Object.entries(groupedDocuments).forEach(([fileName, docs]) => {
            const li = document.createElement('li');
            li.className = 'flex items-center mb-4';
            const docIds = docs.map(doc => doc.id).join(',');
            li.innerHTML = `
                <button class="delete-doc-btn text-red-500 hover:text-red-700 mr-2" data-ids="${docIds}">
                    <i class="fas fa-trash"></i>
                </button>
                <div class="flex-grow">
                    <div class="break-all">${fileName}</div>
                    <div class="text-sm text-gray-500">${docs.length} page${docs.length > 1 ? 's' : ''}</div>
                </div>
            `;
            documentList.appendChild(li);
        });

        // Add event listeners for delete buttons
        document.querySelectorAll('.delete-doc-btn').forEach(btn => {
            btn.addEventListener('click', async (e) => {
                const docIds = e.target.closest('.delete-doc-btn').dataset.ids.split(',');
                if (confirm('Are you sure you want to delete this document and all its pages?')) {
                    await deleteDocument(docIds);
                }
            });
        });
    } catch (error) {
        console.error('Error loading document list:', error);
    }
}

async function deleteDocument(docIds) {
    try {
        const response = await fetch(`/collections/${currentCollection}/delete_documents`, {
            method: 'DELETE',
            headers: {
                'Content-Type': 'application/json',
            },
            body: JSON.stringify({ doc_ids: docIds }),
        });
        if (response.ok) {
            alert('Document and all its pages deleted successfully');
            loadDocumentList();
        } else {
            throw new Error('Failed to delete document');
        }
    } catch (error) {
        console.error('Error deleting document:', error);
        alert('Failed to delete document. Please try again.');
    }
}

searchBtn.addEventListener('click', performSearch);

function prettifyFileInfo(fileInfo, text) {
    const truncatedText = text.length > 300 ? text.substring(0, 300) + '...' : text;

    const metadata = [];
    const skipKeys = ['file_path', 'file_size', 'last_modified_date', 'creation_date', 'text'];
    const sortedKeys = Object.keys(fileInfo).sort((a, b) => a.localeCompare(b));

    for (const key of sortedKeys) {
        const value = fileInfo[key];
        if (value && !skipKeys.includes(key)) {
            const prettyKey = key.replace(/_/g, ' ').replace(/\b\w/g, l => l.toUpperCase());
            metadata.push(`<span class="metadata-item"><strong>${prettyKey}:</strong> ${value}</span>`);
        }
    }

    return `
      <div class="search-result">
        <p class="result-text">${truncatedText}</p>
        <div class="metadata">${metadata.join(' ')}</div>
      </div>
    `;
}

function displaySourceNodes(sourceNodes) {
    return `
      <div class="search-results">
        ${sourceNodes.map(node => prettifyFileInfo(node.metadata, node.text)).join('')}
      </div>
    `;
}

function displaySearchResult(result) {
    searchResult.innerHTML = `
        <h3 class="font-bold mb-2">Answer:</h3>
        <p class="mb-4">${result.answer}</p>
        <h4 class="font-bold mb-2">Sources:</h4>
        ${displaySourceNodes(result.source_nodes)}
    `;
    searchResult.classList.remove('hidden');
}

async function performSearch() {
    if (!currentCollection) {
        alert('Please select a collection first.');
        return;
    }

    const query = searchInput.value.trim();
    if (!query) {
        alert('Please enter a search query.');
        return;
    }

    searchBtn.disabled = true;
    searchBtn.innerHTML = '<i class="fas fa-spinner fa-spin mr-2"></i>Searching...';

    try {
        const response = await fetch(`/collections/${currentCollection}/query`, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
            },
            body: JSON.stringify({ text: query }),
        });

        if (!response.ok) {
            throw new Error('Search failed');
        }

        const result = await response.json();
        displaySearchResult(result);
    } catch (error) {
        console.error('Error:', error);
        alert('Failed to perform search. Please try again.');
    } finally {
        searchBtn.disabled = false;
        searchBtn.innerHTML = 'Search';
    }
}

// Collection management
createCollectionBtn.addEventListener('click', createCollection);

async function createCollection() {
    const name = prompt('Enter a name for the new collection:');
    if (!name) return;

    try {
        const response = await fetch('/collections', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
            },
            body: JSON.stringify({ name }),
        });

        if (!response.ok) {
            const error = await response.json();
            alert(`Error creating collection: ${error.error}`);
            return;
        }

        const result = await response.json();
        alert(result.message);
        loadCollections();
    } catch (error) {
        console.error('Error creating collection:', error);
        alert('Failed to create collection. Please try again.');
    }
}

async function loadCollections() {
    try {
        const response = await fetch('/collections');
        if (!response.ok) {
            throw new Error('Failed to fetch collections');
        }
        const collections = await response.json();
        collectionList.innerHTML = '';
        collections.forEach(collection => {
            const li = document.createElement('li');
            li.className = 'flex items-center justify-between mb-2';
            li.innerHTML = `
                <span class="collection-name cursor-pointer underline break-all">${collection}</span>
                <div>
                    <button class="rename-collection text-blue-500 hover:text-blue-700 mr-2">
                        <i class="fas fa-edit"></i>
                    </button>
                    <button class="delete-collection text-red-500 hover:text-red-700">
                        <i class="fas fa-trash"></i>
                    </button>
                </div>
            `;
            collectionList.appendChild(li);

            li.querySelector('.collection-name').addEventListener('click', () => selectCollection(collection));
            li.querySelector('.rename-collection').addEventListener('click', () => renameCollection(collection));
            li.querySelector('.delete-collection').addEventListener('click', () => deleteCollection(collection));
        });
    } catch (error) {
        console.error('Error loading collections:', error);
        alert('Failed to load collections. Please try again.');
    }
}

function selectCollection(name) {
    currentCollection = name;
    currentCollectionElement.textContent = name;
    loadDocumentList();
}

async function renameCollection(oldName) {
    const newName = prompt(`Enter a new name for the collection "${oldName}":`);
    if (!newName) return;
  
    try {
      const response = await fetch(`/collections/${oldName}?new_name=${newName}`, {
        method: 'PUT',
        headers: {
          'Content-Type': 'application/json',
        },
      });
  
      if (!response.ok) {
        throw new Error('Failed to rename collection');
      }
  
      const result = await response.json();
      alert(result.message);
      loadCollections();
      if (currentCollection === oldName) {
        selectCollection(newName);
      }
    } catch (error) {
      console.error('Error renaming collection:', error);
      alert('Failed to rename collection. Please try again.');
    }
  }

async function deleteCollection(name) {
    if (!confirm(`Are you sure you want to delete the collection "${name}"?`)) return;

    try {
        const response = await fetch(`/collections/${name}`, {
            method: 'DELETE',
        });

        if (!response.ok) {
            throw new Error('Failed to delete collection');
        }

        const result = await response.json();
        alert(result.message);
        loadCollections();
        if (currentCollection === name) {
            currentCollection = null;
            currentCollectionElement.textContent = '';
            document.getElementById('documentList').innerHTML = '';
        }
    } catch (error) {
        console.error('Error deleting collection:', error);
        alert('Failed to delete collection. Please try again.');
    }
}

// Initial load of collections and documents
loadCollections();