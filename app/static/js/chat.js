document.addEventListener('DOMContentLoaded', function () {
    const sendBtn = document.getElementById('send-btn');
    const userInput = document.getElementById('user-input');
    const chatBox = document.getElementById('chat-box');
    const useRAGCheckbox = document.getElementById('use-rag');
    const uploadForm = document.getElementById('upload-form');
    const fileUpload = document.getElementById('file-upload');
    const conversationSelect = document.getElementById('conversation-select');
    const fileChosen = document.getElementById('file-chosen');

    // Funzione per aggiungere i messaggi alla chat
    function addMessageToChat(message, sender) {
        const messageDiv = document.createElement('div');
        messageDiv.classList.add('message', sender);
        messageDiv.innerText = message;
        chatBox.appendChild(messageDiv);
        chatBox.scrollTop = chatBox.scrollHeight;
    }

    // Funzione per inviare i messaggi al server
    function sendMessage() {
        const message = userInput.value;
        const useRAG = useRAGCheckbox.checked;

        if (message.trim() === "") return;

        addMessageToChat(message, 'user');

        fetch('/send_message', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json'
            },
            body: JSON.stringify({ message: message, use_rag: useRAG })
        })
        .then(response => response.json())
        .then(data => {
            addMessageToChat(data.response, 'bot');
        })
        .catch(error => console.error('Error:', error));

        userInput.value = '';
    }

    // Gestisci il click del pulsante di invio
    sendBtn.addEventListener('click', sendMessage);

    // Gestisci l'invio del messaggio premendo "Enter"
    userInput.addEventListener('keypress', function (event) {
        if (event.key === 'Enter') {
            sendMessage();
        }
    });

    // Gestisci il caricamento dei file
    uploadForm.addEventListener('submit', function (event) {
        event.preventDefault();
        
        const formData = new FormData();
        formData.append('file', fileUpload.files[0]);

        fetch('/upload', {
            method: 'POST',
            body: formData
        })
        .then(response => response.json())
        .then(data => {
            alert(data.message);
        })
        .catch(error => console.error('Error:', error));
    });

    // Funzione per popolare il menu a tendina con le conversazioni
    function loadConversationList() {
        console.log("Fetching conversations list...");
        fetch('/conversations_list')
        .then(response => response.json())
        .then(conversations => {
            console.log("Conversations loaded:", conversations);
            // Ripuliamo il menu a tendina prima di ripopolarlo
            conversationSelect.innerHTML = '<option value="" disabled selected>Select a conversation</option>';
            conversations.forEach(conversation => {
                const option = document.createElement('option');
                option.value = conversation.session_id;
                option.textContent = `Conversation from ${conversation.timestamp}`;
                conversationSelect.appendChild(option);
            });
        })
        .catch(error => console.error('Error loading conversations:', error));
    }

    // Carica la lista delle vecchie conversazioni al caricamento della pagina
    loadConversationList();

    // Gestisci la selezione della conversazione
    conversationSelect.addEventListener('change', function () {
        const sessionId = conversationSelect.value;
        if (sessionId) {
            window.location.href = `/conversation/${sessionId}`;
        }
    });

    // Aggiornare il nome del file scelto per il caricamento
    fileUpload.addEventListener('change', function () {
        fileChosen.textContent = fileUpload.files.length > 0 ? fileUpload.files[0].name : "No file chosen";
    });
});
