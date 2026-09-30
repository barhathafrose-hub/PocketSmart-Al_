# PocketSmart AI

Budget and recommendation assistant for Home, Party and Jewelry planning (FastAPI + Gemini + Jinja2).

## Run
1. `python -m venv venv` then activate it
2. `pip install -r requirements.txt`
3. `.env` is already filled in. To change the key, edit `GEMINI_API_KEY` (create keys at https://aistudio.google.com)
3b. Optional check: `python test_gemini.py` (add an image path to test image input too)
4. `python main.py` and open http://127.0.0.1:8000

## Files
- `main.py`: routes, JWT login, sessions, CORS
- `gemini_utils.py`: planner config, prompts, Gemini call, fallback
- `database.py`: SQLite users and history
- `templates/`, `static/`: UI

Never commit `.env`. If Gemini fails, the app returns a default budget split instead of an error.
