# Usa un'immagine di base Python
FROM python:3.10-slim

# Imposta la directory di lavoro nel container
WORKDIR /app

# Existing steps
RUN apt-get update && apt-get install -y \
    gcc \
    libasound-dev \
    libportaudiocpp0 \
    wget \
    make \  
    && rm -rf /var/lib/apt/lists/*

# Scarica e installa manualmente PortAudio
RUN wget -q http://www.portaudio.com/archives/pa_stable_v19_20140130.tgz && \
    tar xzf pa_stable_v19_20140130.tgz && \
    cd portaudio && \
    ./configure && \
    make && \
    make install && \
    ldconfig && \
    cd .. && \
    rm -rf portaudio pa_stable_v19_20140130.tgz

# Copia i file requirements.txt e installa le dipendenze Python
COPY requirements.txt .
RUN pip install --upgrade pip
RUN pip install --no-cache-dir -r requirements.txt

# Copia tutto il contenuto della tua app nel container
COPY . .

# Espone la porta su cui Flask è in ascolto (5000)
EXPOSE 5000

# Imposta la variabile d'ambiente per Flask
ENV FLASK_APP=app.py
ENV FLASK_ENV=production

# Comando per avviare la tua app Flask
CMD ["flask", "run", "--host=0.0.0.0"]
