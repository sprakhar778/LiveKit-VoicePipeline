# 1. Install
pip install -r requirements.txt

# First Time
uv run python app.py download-files

# 2. Copy and fill in your keys
cp .env.example .env

# 3. Run in dev mode (hot-reload)
python app.py dev


#uv run python server.py