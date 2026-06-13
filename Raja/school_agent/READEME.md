# 1. Execute the 0:00–0:30 initialization step script
python seed.py

# 2. Fire up the local webserver
uvicorn app.main:app --reload


# .env
OPENAI_API_KEY=your_actual_openai_api_key_here
DATABASE_URL=sqlite:///./school.db


school_agent/
├── app/
│   ├── routers/
│   │   └── chat_mock.py
│   ├── services/
│   │   └── audit.py
│   ├── schemas.py
│   ├── main.py          <-- 🆕 CREATE THIS (FastAPI Core)
│   ├── database.py      <-- 🆕 CREATE THIS (DB Engine Setup)
│   ├── models.py        <-- 🆕 CREATE THIS (DB Tables)
│   └── config.py        <-- 🆕 CREATE THIS (Env variables wrapper)
├── .env                 <-- 🆕 CREATE THIS (Store secrets here)
└── seed.py              <-- 🆕 CREATE THIS (Initial script for Demo Step 1)
