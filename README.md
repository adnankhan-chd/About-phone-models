# Price From Photo

Upload or take a photo of an item and get an AI-estimated market price (low, typical, high).
Built with [Streamlit](https://streamlit.io) and Google Gemini Flash.

## Run locally

```bash
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

Get a free API key at https://aistudio.google.com/apikey, then create `.streamlit/secrets.toml`:

```toml
GEMINI_API_KEY = "your-key-here"
# Optional: change the model
# GEMINI_MODEL = "gemini-3.6-flash"
```

Start the app:

```bash
streamlit run app.py
```

## Deploy on Streamlit Community Cloud

1. Push this repo to GitHub (never commit `.streamlit/secrets.toml`).
2. Go to https://share.streamlit.io and sign in with GitHub.
3. Click **Create app**, pick your repo, branch `main`, and main file `app.py`.
4. Open **Advanced settings > Secrets** and paste: `GEMINI_API_KEY = "your-key-here"`
5. Click **Deploy**.

## Notes

- Photos are resized and sent to the Gemini API; nothing is stored by the app.
- Estimates are approximate and not a professional appraisal.
- Each session is limited to one request every 5 seconds. Set a quota on your API key to control cost.
- 
