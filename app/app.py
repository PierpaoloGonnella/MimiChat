from flask import Flask, render_template, request, jsonify, session, redirect, url_for
import os
import requests
import json
import pdfplumber
from werkzeug.utils import secure_filename
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity
from uuid import uuid4
from datetime import datetime

# Configurazione di Flask
UPLOAD_FOLDER = 'uploads'
CONVERSATION_FOLDER = 'conversations'
ALLOWED_EXTENSIONS = {'pdf', 'txt'}
app = Flask(__name__)
app.secret_key = 'supersecretkey'
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER

# Ollama API endpoint
OLLAMA_API_URL = "http://localhost:11434/api/generate"

# Crea la cartella per le conversazioni se non esiste
if not os.path.exists(CONVERSATION_FOLDER):
    os.makedirs(CONVERSATION_FOLDER)

if not os.path.exists(UPLOAD_FOLDER):
    os.makedirs(UPLOAD_FOLDER)

# Funzione per verificare il tipo di file
def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

# Funzione per estrarre testo dai PDF
def extract_text_from_pdf(pdf_path):
    text = ""
    with pdfplumber.open(pdf_path) as pdf:
        for page in pdf.pages:
            text += page.extract_text() + "\n"
    return text

# Funzione per caricare documenti e convertirli in testo
def load_uploaded_documents():
    documents = {}
    for filename in os.listdir(app.config['UPLOAD_FOLDER']):
        file_path = os.path.join(app.config['UPLOAD_FOLDER'], filename)
        if filename.endswith(".pdf"):
            documents[filename] = extract_text_from_pdf(file_path)
        elif filename.endswith(".txt"):
            with open(file_path, 'r', encoding='utf-8') as f:
                documents[filename] = f.read()
    return documents

# Funzione per salvare la cronologia delle conversazioni
def save_conversation(session_id, conversation):
    file_path = os.path.join(CONVERSATION_FOLDER, f'session_{session_id}.json')
    with open(file_path, 'w', encoding='utf-8') as f:
        json.dump(conversation, f, ensure_ascii=False, indent=4)

# Funzione per caricare la cronologia delle conversazioni
def load_conversation(session_id):
    file_path = os.path.join(CONVERSATION_FOLDER, f'session_{session_id}.json')
    if os.path.exists(file_path):
        with open(file_path, 'r', encoding='utf-8') as f:
            return json.load(f)
    return []

# Funzione per ottenere la lista delle vecchie conversazioni
def list_conversations():
    conversations = []
    for filename in os.listdir(CONVERSATION_FOLDER):
        if filename.endswith('.json'):
            session_id = filename.split('_')[1].replace('.json', '')
            file_path = os.path.join(CONVERSATION_FOLDER, filename)
            timestamp = os.path.getmtime(file_path)
            formatted_time = datetime.fromtimestamp(timestamp).strftime('%Y-%m-%d %H:%M:%S')
            conversations.append({'session_id': session_id, 'timestamp': formatted_time})
    return conversations

# Simulazione del retrieval usando TF-IDF
class DocumentRetriever:
    def __init__(self, documents):
        self.documents = documents
        self.tfidf_vectorizer = TfidfVectorizer(stop_words=None)
        #self.tfidf_vectorizer = TfidfVectorizer(stop_words='english')
        self.doc_matrix = self.tfidf_vectorizer.fit_transform(documents.values())
    
    def retrieve(self, query, top_k=2):
        query_vector = self.tfidf_vectorizer.transform([query])
        similarity_scores = cosine_similarity(query_vector, self.doc_matrix).flatten()
        top_indices = similarity_scores.argsort()[-top_k:][::-1]
        top_documents = [(list(self.documents.keys())[i], list(self.documents.values())[i]) for i in top_indices]
        return top_documents

# Funzione per inviare messaggi a Ollama con RAG
def talk_to_ollama_with_rag(message, retriever, model="llama3.2:1b"):
    retrieved_docs = retriever.retrieve(message)
    context = "\n".join([doc_content for _, doc_content in retrieved_docs])
    
    augmented_message = f"Context:\n{context}\n\nPrompt:\n{message}"
    
    payload = {
        "model": model,
        "prompt": augmented_message,
        "stream": False
    }
    response = requests.post(OLLAMA_API_URL, json=payload)
    
    if response.status_code == 200:
        return response.json()['response']
    else:
        return "Sorry, I couldn't generate a response."

# Funzione per inviare messaggi a Ollama senza RAG
def talk_to_ollama(message, model="llama3.2:1b"):
    payload = {
        "model": model,
        "prompt": message,
        "stream": False
    }
    response = requests.post(OLLAMA_API_URL, json=payload)
    
    if response.status_code == 200:
        return response.json()['response']
    else:
        return "Sorry, I couldn't generate a response."

# Rotta principale che mostra la lista delle conversazioni salvate
@app.route('/')
def index():
    conversations = list_conversations()
    return render_template('index.html', conversations=conversations)

# Rotta per caricare una conversazione esistente
@app.route('/conversation/<session_id>')
def load_existing_conversation(session_id):
    session['session_id'] = session_id
    conversation_history = load_conversation(session_id)
    return render_template('chat.html', conversation_history=conversation_history)

# Rotta per avviare una nuova conversazione
@app.route('/new_conversation')
def new_conversation():
    session['session_id'] = str(uuid4())
    return redirect(url_for('chat'))

# Rotta per la pagina di chat (vuota quando si inizia una nuova conversazione)
@app.route('/chat')
def chat():
    # Se non è stata specificata una sessione, crea una nuova conversazione
    if 'session_id' not in session:
        session['session_id'] = str(uuid4())
    conversation_history = load_conversation(session['session_id'])
    return render_template('chat.html', conversation_history=conversation_history)

# Rotta per caricare i documenti
@app.route('/upload', methods=['POST'])
def upload_file():
    if 'file' not in request.files:
        return jsonify({'message': 'No file part in the request'}), 400
    file = request.files['file']
    if file.filename == '':
        return jsonify({'message': 'No file selected'}), 400
    if file and allowed_file(file.filename):
        filename = secure_filename(file.filename)
        file.save(os.path.join(app.config['UPLOAD_FOLDER'], filename))
        return jsonify({'message': f'File {filename} uploaded successfully.'}), 200
    else:
        return jsonify({'message': 'File type not allowed'}), 400

# Rotta per inviare un messaggio nella chat
@app.route('/send_message', methods=['POST'])
def send_message():
    user_message = request.json.get('message')
    use_rag = request.json.get('use_rag', False)
    
    # Carica la cronologia delle conversazioni
    conversation = load_conversation(session['session_id'])
    
    # Aggiungi il messaggio dell'utente alla cronologia
    conversation.append({'sender': 'user', 'message': user_message})
    
    documents = load_uploaded_documents()

    # Controlla se ci sono documenti per RAG
    if use_rag:
        if not documents or not any(documents.values()):  # Verifica se ci sono documenti validi
            bot_response = "Per utilizzare il RAG, è necessario caricare un documento valido."
        else:
            retriever = DocumentRetriever(documents)
            bot_response = talk_to_ollama_with_rag(user_message, retriever)
    else:
        bot_response = talk_to_ollama(user_message)
    
    # Aggiungi la risposta del bot alla cronologia
    conversation.append({'sender': 'bot', 'message': bot_response})
    
    # Salva la conversazione aggiornata
    save_conversation(session['session_id'], conversation)
    
    return jsonify({'response': bot_response})

@app.route('/conversations_list')
def conversations_list():
    # Restituisce la lista delle vecchie conversazioni in formato JSON
    conversations = list_conversations()
    return jsonify(conversations)

if __name__ == "__main__":
    if not os.path.exists(UPLOAD_FOLDER):
        os.makedirs(UPLOAD_FOLDER)
    app.run(host="0.0.0.0", port=5000, debug=True)
