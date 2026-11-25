# LexiGuide AI – Streamlit edition

AI-Powered Micro-Legal Assistant for Common Traffic & Civil Infractions.
Sections: Home, Ask Legal Question, Upload & Analyse Document, Traffic & Civil Issues, My Documents, History, Settings.

## Put it live on Streamlit Community Cloud (free)

1. Create a free account at https://github.com and make a **new public repository** (for example `lexiguide-ai`).
2. Click **Add file → Upload files**, drag in everything from this folder
   (`app.py`, `kb.json`, `requirements.txt`, `.streamlit/config.toml`, `README.md`, `.gitignore`), and commit.
   Do **not** upload your real API key.
3. Go to https://share.streamlit.io, sign in with GitHub and click **Create app → Deploy a public app from GitHub**.
   Choose your repository, branch `main`, and main file `app.py`.
4. Before or after deploying, open **App → Settings → Secrets** and paste:

       GEMINI_API_KEY = "your-key-from-aistudio.google.com/apikey"
       GEMINI_MODELS = "gemini-3.8-flash,gemini-3.5-flash-lite"

5. Click **Deploy**. Your site gets a public link like `https://your-app-name.streamlit.app`.

## Run on your own computer

    pip install -r requirements.txt
    streamlit run app.py

To use a key locally, copy `.streamlit/secrets.toml.example` to `.streamlit/secrets.toml` and edit it,
or paste the key in the app under Settings.

## Notes

- If a model is busy or retired, open **Settings → Test connection & auto-select model**.
- History and My Documents are kept per browser session only. Nothing is written to the server, so visitors never see each other’s data. Use "Download my activity" in Settings to keep a copy.
- Edit `kb.json` to add or correct knowledge-base entries. Fines follow the Motor Vehicles (Amendment) Act, 2019; verify them against official sources.
- General legal information only, not legal advice.
